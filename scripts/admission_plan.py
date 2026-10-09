#!/usr/bin/env python3
"""Admission as plan versions: propose a new plan document, publish criteria, check a uid.

  uv run python scripts/admission_plan.py criteria --criteria-id ID --windows 5 \
      --min-valid-responses 12 --out criteria.json
  uv run python scripts/admission_plan.py check --criteria criteria.json --uid 3 \
      --hotkey SS58 --endpoint-record record.json --results RESULTS_DIR --netuid 582
  uv run python scripts/admission_plan.py propose --parent PLAN.json --uid 3 --stage shadow \
      --hotkey SS58 --endpoint-record record.json --out DIR

PROPOSALS ONLY. NOTHING HERE APPROVES, SIGNS, SUBMITS OR WRITES TO A CHAIN.

A plan version is a new document with a new digest. The parent document is read and never
changed. Every output carries ``status: PROPOSED_NEEDS_AUTHORITY_APPROVAL`` and an
``approval.reference`` field that this tool leaves empty: an approval is a record made outside
this repository, which cites the version's digest. The tool reads no ledger, holds no key and
imports no wallet, chain or network code.

Stages of an outside uid:

* ``local``    the uid runs the miner against local fixtures only. Nothing is queried or published.
* ``shadow``   the uid has an announced endpoint, is queried with the same fresh-window capsules
               as every other miner, is scored with the public scorer and the result is
               published, with weight 0. A shadow uid is never in a weight row.
* ``weighted`` the uid may be in a weight row. The proposal re-evaluates the criteria from the
               raw window results (it trusts no report), the criteria digest must be the one
               pinned in the parent plan, and the row needs a non-empty approval reference.

A weight row is composed only through ``compose_row``: it refuses a uid that is not eligible
and refuses a value that is not a plain number, so a shadow score object cannot be converted
into a weight.

This module is self-contained on purpose (standard library only), so a miner can run the
checker against the published criteria and their own published results.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STATUS = "PROPOSED_NEEDS_AUTHORITY_APPROVAL"
VERSION_SCHEMA = "sn87-admission-plan-version/0.1"
CRITERIA_SCHEMA = "sn87-admission-criteria/0.1"
RESULT_SCHEMA = "sn87-shadow-window-result/0.1"
REPORT_SCHEMA = "sn87-admission-criteria-report/0.1"
ENDPOINT_RECORD_SCHEMA = "sn87-endpoint-record/0.1"
ANNOUNCEMENT_SCHEMA = "sn87-miner-announcement/0.1"
STAGES = ("local", "shadow", "weighted")
VALIDATOR_UID = 0
MAX_FUTURE_SKEW_MS = 5 * 60 * 1000
SS58_RE = re.compile(r"\A[1-9A-HJ-NP-Za-km-z]{46,48}\Z")
APPROVAL_REF_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/#-]{0,127}\Z")
DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
NOT_CLAIMED = [
    "this document is a proposal: it is not approved and nothing was signed or submitted",
    "no chain read or write was made to produce it",
    "the existing approved plan document and its digest are unchanged",
    "a shadow uid is scored and published with weight 0 and is never in a weight row",
    "the criteria values are proposals until the approval record cites this version",
]


class AdmissionError(ValueError):
    """The proposal was refused; the message starts with a stable code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class ShadowUidInRow(AdmissionError):
    """A uid that is not eligible for a weight row was offered to ``compose_row``."""


# ------------------------------------------------------------------------------ digests
def canonical(value: Any) -> bytes:
    """The same byte form as the plan digest of the approved plan document."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_of(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def document_digest_ok(document: Mapping[str, Any]) -> bool:
    return document.get("plan_digest") == sha256_of(document.get("plan"))


# -------------------------------------------------------------------- endpoint record
@dataclass(frozen=True)
class EndpointCheck:
    """The result of checking an announced endpoint record. ``valid`` needs no reasons."""

    valid: bool
    hotkey: str | None
    endpoint: str | None
    signature: str  # VERIFIED, NOT_CHECKED or INVALID
    reasons: tuple[str, ...]
    record_digest: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "hotkey": self.hotkey, "endpoint": self.endpoint,
                "signature": self.signature, "reasons": list(self.reasons),
                "record_digest": self.record_digest}


def _flatten_record(record: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Accept the minimal record or the signed announcement shape; return (fields, signature)."""
    if "announcement" in record:
        inner = record["announcement"]
        return (dict(inner) if isinstance(inner, Mapping) else {}), (
            dict(record["signature"]) if isinstance(record.get("signature"), Mapping) else None)
    return dict(record), None


def _endpoint_problem(endpoint: Any) -> str | None:
    if not isinstance(endpoint, str) or not endpoint \
            or not all(0x21 <= ord(c) <= 0x7E and c != "\\" for c in endpoint):
        return "ENDPOINT_NOT_VISIBLE_ASCII"
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return "ENDPOINT_UNPARSEABLE"
    if parts.scheme != "https" or not parts.hostname:
        return "ENDPOINT_NOT_HTTPS_ORIGIN"
    if parts.username or parts.password or parts.path not in ("", "/") or parts.query \
            or parts.fragment:
        return "ENDPOINT_NOT_AN_ORIGIN"
    if port == 0:
        return "ENDPOINT_PORT_ZERO"
    host = parts.hostname
    if host == "localhost" or host.endswith(".localhost"):
        return "ENDPOINT_LOCAL_HOST"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host.isdigit() or host.lower().startswith("0x"):
            return "ENDPOINT_NUMERIC_HOST_FORM"
        return None
    return None if address.is_global else "ENDPOINT_ADDRESS_NOT_GLOBAL"


def check_endpoint_record(
    record: Mapping[str, Any] | None, *, netuid: int, now_ms: int,
    expected_hotkey: str | None = None, expected_uid: int | None = None,
    signature_verifier: Callable[[Mapping[str, Any]], bool] | None = None,
) -> EndpointCheck:
    """Check the text of an endpoint record. Signature checking is injected, never assumed.

    ``signature_verifier`` gets the whole record and returns True or False. Without one the
    signature is reported ``NOT_CHECKED`` and the record is valid for the structural rules
    only; the criteria decide whether that is enough (``require_signature_verified``).
    """
    reasons: list[str] = []
    if not isinstance(record, Mapping):
        return EndpointCheck(False, None, None, "NOT_CHECKED", ("ENDPOINT_RECORD_MISSING",), None)
    fields, _ = _flatten_record(record)
    hotkey, endpoint = fields.get("hotkey"), fields.get("endpoint")
    schema = fields.get("schema_version")
    if schema not in (ENDPOINT_RECORD_SCHEMA, ANNOUNCEMENT_SCHEMA):
        reasons.append("ENDPOINT_SCHEMA_UNKNOWN")
    if fields.get("netuid") != netuid or type(fields.get("netuid")) is not int:
        reasons.append("ENDPOINT_NETUID_MISMATCH")
    if not isinstance(hotkey, str) or not SS58_RE.match(hotkey):
        reasons.append("ENDPOINT_HOTKEY_MALFORMED")
    elif expected_hotkey is not None and hotkey != expected_hotkey:
        reasons.append("ENDPOINT_HOTKEY_MISMATCH")
    if expected_uid is not None and "uid" in fields and fields["uid"] != expected_uid:
        reasons.append("ENDPOINT_UID_MISMATCH")
    problem = _endpoint_problem(endpoint)
    if problem:
        reasons.append(problem)
    expires, issued = fields.get("expires_at_ms"), fields.get("issued_at_ms")
    if type(expires) is not int or expires <= now_ms:
        reasons.append("ENDPOINT_RECORD_EXPIRED_OR_UNDATED")
    if issued is not None and (type(issued) is not int or issued > now_ms + MAX_FUTURE_SKEW_MS):
        reasons.append("ENDPOINT_RECORD_ISSUED_IN_FUTURE")
    signature = "NOT_CHECKED"
    if signature_verifier is not None:
        try:
            signature = "VERIFIED" if signature_verifier(record) is True else "INVALID"
        except Exception:  # noqa: BLE001 - a verifier failure is an invalid signature
            signature = "INVALID"
        if signature == "INVALID":
            reasons.append("ENDPOINT_SIGNATURE_INVALID")
    return EndpointCheck(not reasons, hotkey if isinstance(hotkey, str) else None,
                         endpoint if isinstance(endpoint, str) else None, signature,
                         tuple(reasons), sha256_of(record))


# ---------------------------------------------------------------------------- criteria
RULE_INTS = {"consecutive_windows": (1, 10_000), "min_valid_responses_per_window": (1, 1_000_000),
             "max_integrity_failures_per_window": (0, 1_000_000)}
RULE_BOOLS = ("require_endpoint_announcement_valid", "require_signature_verified",
              "results_must_be_shadow_with_weight_zero")


def _is_int(value: Any) -> bool:
    return type(value) is int


def validate_rules(rules: Any) -> str | None:
    """None when the rules are well formed, else a stable code. Never raises."""
    if not isinstance(rules, Mapping) or set(rules) != set(RULE_INTS) | set(RULE_BOOLS):
        return "CRITERIA_RULES_KEYS"
    for key, (low, high) in RULE_INTS.items():
        if not _is_int(rules[key]) or not low <= rules[key] <= high:
            return f"CRITERIA_RULE_INVALID_{key}"
    if any(type(rules[key]) is not bool for key in RULE_BOOLS):
        return "CRITERIA_RULE_NOT_BOOLEAN"
    if rules["results_must_be_shadow_with_weight_zero"] is not True:
        return "CRITERIA_SHADOW_RULE_MUST_BE_ON"
    return None


def make_criteria(*, criteria_id: str, consecutive_windows: int,
                  min_valid_responses_per_window: int,
                  max_integrity_failures_per_window: int = 0,
                  require_endpoint_announcement_valid: bool = True,
                  require_signature_verified: bool = True) -> dict[str, Any]:
    """The machine-checkable admission criteria. Values are explicit arguments, no defaults
    for the two numbers that carry the policy; the document says they are proposals."""
    if not isinstance(criteria_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", criteria_id):
        raise AdmissionError("CRITERIA_ID_INVALID")
    rules = {
        "consecutive_windows": consecutive_windows,
        "min_valid_responses_per_window": min_valid_responses_per_window,
        "max_integrity_failures_per_window": max_integrity_failures_per_window,
        "require_endpoint_announcement_valid": require_endpoint_announcement_valid,
        "require_signature_verified": require_signature_verified,
        "results_must_be_shadow_with_weight_zero": True,
    }
    problem = validate_rules(rules)
    if problem:
        raise AdmissionError(problem)
    body = {"schema_version": CRITERIA_SCHEMA, "status": STATUS, "criteria_id": criteria_id,
            "applies_to": "shadow to weighted", "rules": rules,
            "windows": "the current latest N consecutive window indexes, none missing",
            "not_claimed": ["the values are proposals until an approval record cites this digest"]}
    return {**body, "criteria_digest": sha256_of(body)}


def criteria_digest_ok(criteria: Any) -> bool:
    """Digest recomputes, schema matches and the rules are well formed (never raises)."""
    if not isinstance(criteria, Mapping):
        return False
    body = {k: v for k, v in criteria.items() if k != "criteria_digest"}
    return criteria.get("criteria_digest") == sha256_of(body) \
        and criteria.get("schema_version") == CRITERIA_SCHEMA \
        and validate_rules(criteria.get("rules")) is None


# ------------------------------------------------------------------- window results
def result_digest(record: Mapping[str, Any]) -> str:
    return sha256_of({k: v for k, v in record.items() if k != "record_digest"})


def build_window_result(*, uid: int, hotkey: str, netuid: int, window: int, seed: int,
                        queried: int, valid_responses: int, invalid_responses: int,
                        unavailable: int, integrity_failure_codes: Iterable[str],
                        estimate: Any, evaluable: int, admitted: int,
                        profile_id: str, endpoint_record_digest: str | None) -> dict[str, Any]:
    """One published shadow window result. ``weight`` is the constant 0 and ``stage`` the
    constant ``shadow``: the checker refuses a record that says otherwise."""
    codes = sorted(integrity_failure_codes)
    record = {
        "schema_version": RESULT_SCHEMA, "stage": "shadow", "weight": 0,
        "statement": "scored and published, not weighted; never in a weight row",
        "uid": uid, "hotkey": hotkey, "netuid": netuid, "window": window, "seed": seed,
        "profile_id": profile_id, "endpoint_record_digest": endpoint_record_digest,
        "queried": queried, "valid_responses": valid_responses,
        "invalid_responses": invalid_responses, "unavailable": unavailable,
        "integrity_failure_count": len(codes), "integrity_failure_codes": codes,
        "admitted": admitted, "evaluable": evaluable, "estimate": estimate,
    }
    return {**record, "record_digest": result_digest(record)}


RESULT_INTS = ("uid", "netuid", "window", "seed", "queried", "valid_responses",
               "invalid_responses", "unavailable", "integrity_failure_count", "admitted",
               "evaluable")


def result_shape_problem(record: Mapping[str, Any]) -> str | None:
    """Type and consistency checks on a window result. Never raises."""
    for key in RESULT_INTS:
        if not _is_int(record.get(key)) or record[key] < 0:
            return f"RESULT_FIELD_INVALID_{key}"
    codes = record.get("integrity_failure_codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes) \
            or len(codes) != record["integrity_failure_count"]:
        return "RESULT_FIELD_INVALID_integrity_failure_codes"
    if record["valid_responses"] + record["invalid_responses"] + record["unavailable"] \
            + record["integrity_failure_count"] != record["queried"]:
        return "RESULT_COUNTS_INCONSISTENT"
    if record["evaluable"] > record["admitted"]:
        return "RESULT_COUNTS_INCONSISTENT"
    return None


@dataclass
class CriteriaReport:
    """Evidence for an approval record. A proposal never trusts it: it recomputes."""

    uid: int
    passed: bool
    reasons: list[dict[str, Any]] = field(default_factory=list)
    windows_checked: list[int] = field(default_factory=list)
    criteria_digest: str | None = None
    hotkey: str | None = None
    endpoint: dict[str, Any] | None = None
    now_window: int | None = None
    result_digests: list[str] = field(default_factory=list)

    def as_document(self) -> dict[str, Any]:
        body = {"schema_version": REPORT_SCHEMA, "uid": self.uid, "hotkey": self.hotkey,
                "passed": self.passed, "verdict": "PASS" if self.passed else "FAIL",
                "reasons": self.reasons, "windows_checked": self.windows_checked,
                "now_window": self.now_window, "result_digests": self.result_digests,
                "criteria_digest": self.criteria_digest, "endpoint": self.endpoint,
                "statement": "a report is evidence for an approval record; it approves nothing"}
        return {**body, "report_digest": sha256_of(body)}


def evaluate_criteria(criteria: Any, results: Iterable[Any], endpoint: EndpointCheck | None,
                      *, uid: int, hotkey: str, now_window: int, netuid: int
                      ) -> CriteriaReport:
    """Evaluate a uid's published window results against the criteria. Fails closed: every
    problem is a reason, and one reason is enough to fail. Bad input gives a reason, not an
    exception.

    The windows checked are exactly ``now_window - N + 1`` to ``now_window``; every one must be
    present. ``now_window`` is the current window index chosen by the caller.
    """
    reasons: list[dict[str, Any]] = []

    def fail(code: str, **detail: Any) -> None:
        reasons.append({"code": code, **detail})

    if not criteria_digest_ok(criteria):
        fail("CRITERIA_DIGEST_OR_RULES_INVALID")
        return CriteriaReport(uid, False, reasons, [], None, hotkey, None, None)
    if not _is_int(now_window) or now_window < 0:
        fail("NOW_WINDOW_INVALID")
        return CriteriaReport(uid, False, reasons, [], criteria["criteria_digest"], hotkey)
    rules = criteria["rules"]
    needed = rules["consecutive_windows"]
    if rules["require_endpoint_announcement_valid"]:
        if endpoint is None:
            fail("ENDPOINT_RECORD_MISSING")
        else:
            if not endpoint.valid:
                for code in endpoint.reasons:
                    fail("ENDPOINT_" + code.removeprefix("ENDPOINT_"))
            if endpoint.hotkey is not None and endpoint.hotkey != hotkey:
                fail("ENDPOINT_HOTKEY_MISMATCH")
            if rules["require_signature_verified"] and endpoint.signature != "VERIFIED":
                fail("ENDPOINT_SIGNATURE_NOT_VERIFIED", signature=endpoint.signature)
    by_window: dict[int, Mapping[str, Any]] = {}
    for record in results:
        if not isinstance(record, Mapping) or record.get("schema_version") != RESULT_SCHEMA:
            fail("RESULT_SCHEMA_INVALID")
            continue
        if record.get("uid") != uid:
            continue  # another uid's record: not this uid's evidence, not an error
        window = record.get("window")
        if not _is_int(window) or window < 0:
            fail("RESULT_WINDOW_INVALID")
            continue
        if record.get("record_digest") != result_digest(record):
            fail("RESULT_DIGEST_INVALID", window=window)
            continue
        shape = result_shape_problem(record)
        if shape:
            fail(shape, window=window)
            continue
        if record["hotkey"] != hotkey:
            fail("RESULT_HOTKEY_MISMATCH", window=window)
            continue
        if record["netuid"] != netuid:
            fail("RESULT_NETUID_MISMATCH", window=window)
            continue
        if record["stage"] != "shadow" or record["weight"] != 0:
            fail("RESULT_NOT_SHADOW_WEIGHT_ZERO", window=window)
            continue
        if window > now_window:
            fail("RESULT_WINDOW_IN_THE_FUTURE", window=window)
            continue
        if window in by_window:
            fail("DUPLICATE_WINDOW", window=window)
            continue
        by_window[window] = record
    checked = list(range(max(0, now_window - needed + 1), now_window + 1))
    if now_window + 1 < needed:
        fail("INSUFFICIENT_WINDOWS", have=now_window + 1, need=needed)
    present: list[int] = []
    for window in checked:
        record = by_window.get(window)
        if record is None:
            fail("MISSING_WINDOW", window=window)
            continue
        present.append(window)
        if record["integrity_failure_count"] > rules["max_integrity_failures_per_window"]:
            fail("INTEGRITY_FAILURE", window=window, count=record["integrity_failure_count"],
                 codes=record["integrity_failure_codes"])
        if record["valid_responses"] < rules["min_valid_responses_per_window"]:
            fail("TOO_FEW_VALID_RESPONSES", window=window, have=record["valid_responses"],
                 need=rules["min_valid_responses_per_window"])
    return CriteriaReport(uid, not reasons, reasons, present, criteria["criteria_digest"],
                          hotkey, None if endpoint is None else endpoint.as_dict(), now_window,
                          [by_window[w]["record_digest"] for w in present])


# ------------------------------------------------------------------------ plan versions
def _base_uids(plan: Mapping[str, Any]) -> set[int]:
    uids: set[int] = set()
    would_set = plan.get("would_set")
    if isinstance(would_set, Mapping):
        uids |= {u for u in would_set.get("dests", []) if type(u) is int}
    binding = plan.get("binding")
    if isinstance(binding, Mapping):
        uids |= {m["expected_uid"] for m in binding.get("miners", [])
                 if isinstance(m, Mapping) and type(m.get("expected_uid")) is int}
    return uids


def _base_hotkeys(plan: Mapping[str, Any]) -> set[str]:
    binding = plan.get("binding")
    if not isinstance(binding, Mapping):
        return set()
    return {m["hotkey"] for m in binding.get("miners", [])
            if isinstance(m, Mapping) and isinstance(m.get("hotkey"), str)}


def _admission(plan: Mapping[str, Any]) -> dict[str, Any]:
    section = plan.get("admission")
    out = copy.deepcopy(dict(section)) if isinstance(section, Mapping) else {}
    out.setdefault("uids", {})
    return out


def approval_reference(document: Mapping[str, Any]) -> str:
    approval = document.get("approval")
    reference = approval.get("reference") if isinstance(approval, Mapping) else ""
    return reference if isinstance(reference, str) else ""


def propose_version(
    parent: Mapping[str, Any], *, uid: int, stage: str, hotkey: str | None = None,
    endpoint_check: EndpointCheck | None = None, criteria: Mapping[str, Any] | None = None,
    results: Iterable[Mapping[str, Any]] | None = None, now_window: int | None = None,
    netuid: int | None = None,
) -> dict[str, Any]:
    """Return a NEW plan version document; ``parent`` is not mutated and keeps its digest.

    For ``weighted`` the criteria are evaluated again here from the raw window ``results``;
    no report is accepted from the caller. The criteria digest must be the one pinned in the
    parent plan, and the hotkey must be the hotkey of the uid's shadow entry.
    """
    if stage not in STAGES:
        raise AdmissionError("STAGE_UNKNOWN", stage)
    if not document_digest_ok(parent):
        raise AdmissionError("PARENT_DIGEST_INVALID")
    parent_plan = parent["plan"]
    if "admission" in parent_plan:
        verify_version(parent)  # lineage, digests and entries of a version used as a parent
        if not approval_reference(parent):
            raise AdmissionError("PARENT_VERSION_NOT_APPROVED",
                                 "propose on top of an approved version only")
    if type(uid) is not int or not 0 <= uid <= 65535 or uid == VALIDATOR_UID:
        raise AdmissionError("UID_INVALID", str(uid))
    if uid in _base_uids(parent_plan):
        raise AdmissionError("UID_IN_APPROVED_BASE_PLAN", str(uid))
    admission = _admission(parent_plan)
    existing = admission["uids"].get(str(uid), {})
    current = existing.get("stage")
    entry: dict[str, Any] = {"stage": stage, "hotkey": hotkey}
    if stage in ("shadow", "weighted"):
        if not isinstance(hotkey, str) or not SS58_RE.match(hotkey):
            raise AdmissionError("HOTKEY_REQUIRED")
        if endpoint_check is None or not endpoint_check.valid \
                or endpoint_check.hotkey != hotkey:
            raise AdmissionError("ENDPOINT_RECORD_NOT_VALID_FOR_HOTKEY")
        taken = _base_hotkeys(parent_plan) | {
            e.get("hotkey") for k, e in admission["uids"].items() if k != str(uid)}
        if hotkey in taken:
            raise AdmissionError("HOTKEY_ALREADY_STAGED")
        entry["endpoint_record_digest"] = endpoint_check.record_digest
        entry["endpoint_signature"] = endpoint_check.signature
    if stage == "shadow":
        if criteria is not None:
            if not criteria_digest_ok(criteria):
                raise AdmissionError("CRITERIA_INVALID")
            pinned = admission.get("criteria_digest")
            if pinned not in (None, criteria["criteria_digest"]):
                raise AdmissionError("CRITERIA_PIN_CHANGE")
            admission["criteria_digest"] = criteria["criteria_digest"]
        if current == "weighted":
            entry["note"] = "moved down from weighted"
    if stage == "weighted":
        if current != "shadow":
            raise AdmissionError("WEIGHTED_NEEDS_SHADOW_FIRST", f"current stage {current!r}")
        if hotkey != existing.get("hotkey"):
            raise AdmissionError("HOTKEY_DIFFERS_FROM_SHADOW_ENTRY")
        if criteria is None or results is None or now_window is None \
                or not criteria_digest_ok(criteria):
            raise AdmissionError("CRITERIA_RESULTS_AND_WINDOW_REQUIRED")
        if admission.get("criteria_digest") != criteria["criteria_digest"]:
            raise AdmissionError("CRITERIA_NOT_PINNED_IN_PARENT")
        evaluated_netuid = netuid if netuid is not None else (
            parent_plan.get("would_set", {}).get("netuid")
            if isinstance(parent_plan.get("would_set"), Mapping) else None)
        if not _is_int(evaluated_netuid):
            raise AdmissionError("NETUID_REQUIRED")
        report = evaluate_criteria(criteria, list(results), endpoint_check, uid=uid,
                                   hotkey=hotkey, now_window=now_window,
                                   netuid=evaluated_netuid).as_document()
        if report["passed"] is not True or report["reasons"]:
            raise AdmissionError("CRITERIA_NOT_PASSED",
                                 ",".join(r["code"] for r in report["reasons"][:5]))
        entry["criteria_digest"] = criteria["criteria_digest"]
        entry["criteria_report_digest"] = report["report_digest"]
        entry["result_digests"] = report["result_digests"]
        entry["now_window"] = now_window
    admission["uids"][str(uid)] = entry
    new_plan = copy.deepcopy(dict(parent_plan))
    version = (parent.get("plan_version") or 1) + 1
    admission["uids"] = dict(sorted(admission["uids"].items(), key=lambda item: int(item[0])))
    new_plan["admission"] = admission
    new_plan["parent_plan_digest"] = parent["plan_digest"]
    new_plan["plan_version"] = version
    return {
        "schema_version": VERSION_SCHEMA, "status": STATUS, "plan_version": version,
        "plan_digest": sha256_of(new_plan), "parent_plan_digest": parent["plan_digest"],
        "plan": new_plan,
        "approval": {"reference": "",
                     "note": "left empty by this tool; an approval record outside this "
                             "repository cites plan_digest"},
        "not_claimed": NOT_CLAIMED,
    }


def version_digest_ok(document: Mapping[str, Any]) -> bool:
    return document.get("schema_version") == VERSION_SCHEMA and document_digest_ok(document)


def verify_version(document: Mapping[str, Any]) -> None:
    """Raise ``AdmissionError`` unless the whole version document is internally sound:
    digest, lineage fields, approval reference format, and every entry's required digests."""
    if not isinstance(document, Mapping) or not version_digest_ok(document):
        raise AdmissionError("VERSION_DIGEST_INVALID")
    plan = document["plan"]
    if not isinstance(plan, Mapping) or not DIGEST_RE.match(str(plan.get("parent_plan_digest"))) \
            or document.get("parent_plan_digest") != plan["parent_plan_digest"]:
        raise AdmissionError("VERSION_PARENT_DIGEST_MISSING")
    if not _is_int(plan.get("plan_version")) or plan["plan_version"] < 2 \
            or document.get("plan_version") != plan["plan_version"]:
        raise AdmissionError("VERSION_NUMBER_INVALID")
    reference = approval_reference(document)
    if reference and not APPROVAL_REF_RE.match(reference):
        raise AdmissionError("APPROVAL_REFERENCE_FORMAT")
    admission = plan.get("admission")
    if not isinstance(admission, Mapping) or not isinstance(admission.get("uids"), Mapping):
        raise AdmissionError("VERSION_ADMISSION_MISSING")
    pinned = admission.get("criteria_digest")
    base_uids, hotkeys = _base_uids(plan), set()
    for key, entry in admission["uids"].items():
        if not key.isdigit() or not isinstance(entry, Mapping) \
                or entry.get("stage") not in STAGES or int(key) in base_uids \
                or int(key) == VALIDATOR_UID:
            raise AdmissionError("VERSION_ENTRY_INVALID", key)
        if entry["stage"] in ("shadow", "weighted"):
            hotkey = entry.get("hotkey")
            if not isinstance(hotkey, str) or not SS58_RE.match(hotkey) or hotkey in hotkeys:
                raise AdmissionError("VERSION_ENTRY_HOTKEY_INVALID", key)
            hotkeys.add(hotkey)
        if entry["stage"] == "weighted":
            digests = (entry.get("criteria_digest"), entry.get("criteria_report_digest"))
            results = entry.get("result_digests")
            if not all(isinstance(d, str) and DIGEST_RE.match(d) for d in digests) \
                    or not isinstance(results, list) or not results \
                    or not all(isinstance(d, str) and DIGEST_RE.match(d) for d in results):
                raise AdmissionError("VERSION_WEIGHTED_ENTRY_WITHOUT_EVIDENCE", key)
            if pinned is None or entry["criteria_digest"] != pinned:
                raise AdmissionError("VERSION_CRITERIA_NOT_PINNED", key)


# --------------------------------------------------------------------- weight-row choke point
def eligible_row_uids(document: Mapping[str, Any]) -> tuple[int, ...]:
    """Uids that may appear in a weight row under this plan document.

    A version document is verified in full first (``verify_version``; a bad one raises).
    The base plan's uids are always eligible; a ``weighted`` uid only when the document carries
    an approval reference. Shadow and local uids never.
    """
    if document.get("schema_version") == VERSION_SCHEMA:
        verify_version(document)
    elif not document_digest_ok(document):
        raise AdmissionError("PLAN_DIGEST_INVALID")
    plan = document["plan"]
    uids = set(_base_uids(plan))
    if document.get("schema_version") == VERSION_SCHEMA and approval_reference(document):
        for key, entry in _admission(plan)["uids"].items():
            if entry.get("stage") == "weighted":
                uids.add(int(key))
    return tuple(sorted(uids))


def compose_row(document: Mapping[str, Any], scores: Mapping[int, Any]) -> dict[int, Any]:
    """The only function that turns per-uid values into a row for a plan document.

    It verifies the document, refuses a uid that is not eligible (``ShadowUidInRow``) and
    refuses a value that is not a finite, non-negative plain number (not a bool).
    """
    eligible = set(eligible_row_uids(document))
    row: dict[int, Any] = {}
    for uid, value in scores.items():
        if type(uid) is not int:
            raise AdmissionError("ROW_UID_NOT_INT")
        if uid not in eligible:
            stage = _admission(document["plan"])["uids"].get(str(uid), {}).get("stage")
            raise ShadowUidInRow("UID_NOT_ELIGIBLE_FOR_ROW", f"uid {uid} stage {stage!r}")
        if type(value) not in (int, float, Decimal):
            raise TypeError("ROW_VALUE_MUST_BE_A_PLAIN_NUMBER")
        if not Decimal(value).is_finite() or value < 0:
            raise AdmissionError("ROW_VALUE_MUST_BE_FINITE_AND_NON_NEGATIVE")
        row[uid] = value
    return dict(sorted(row.items()))


# ------------------------------------------------------------------------------- CLI
def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_new(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")


def announcement_verifier(*, netuid: int, now_ms: int, hotkey: str
                          ) -> Callable[[Mapping[str, Any]], bool] | None:
    """The miner announcement verifier of this repository, as a signature check.

    It verifies the signed record (schema, sr25519 signature, netuid, hotkey, endpoint rule,
    freshness) with ``miner_node.announcement.verify``. Rollback against earlier records is not
    checked here (no earlier record is passed). Returns None where that module is absent.
    """
    import importlib
    try:
        announcement = importlib.import_module("sn87_provenonce.miner_node.announcement")
        canonical_module = importlib.import_module("sn87_provenonce.canonical")
    except ImportError:
        return None

    def verify(record: Mapping[str, Any]) -> bool:
        try:
            announcement.verify(canonical_module.canonical_bytes(dict(record)), netuid=netuid,
                                now_ms=now_ms, expected_hotkey=hotkey, last_accepted=None)
        except Exception:  # noqa: BLE001 - any failure is an invalid signature
            return False
        return True

    return verify


def _load_verifier(spec: str | None) -> Callable[[Mapping[str, Any]], bool] | None:
    """Import ``module:function``. The caller names code to run; nothing is assumed."""
    if spec is None:
        return None
    module_name, _, function = spec.partition(":")
    if not module_name or not function:
        raise AdmissionError("VERIFIER_SPEC_INVALID", "expected MODULE:FUNCTION")
    import importlib
    return getattr(importlib.import_module(module_name), function)


def _load_results(path: Path) -> list[dict[str, Any]]:
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    out: list[dict[str, Any]] = []
    for file in files:
        loaded = _read_json(file)
        out.extend(loaded if isinstance(loaded, list) else [loaded])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("criteria", help="write a criteria document")
    c.add_argument("--criteria-id", required=True)
    c.add_argument("--windows", type=int, required=True)
    c.add_argument("--min-valid-responses", type=int, required=True)
    c.add_argument("--max-integrity-failures", type=int, default=0)
    c.add_argument("--allow-unverified-signature", action="store_true")
    c.add_argument("--out", type=Path, required=True)
    k = sub.add_parser("check", help="evaluate a uid against the criteria; exit 0 only on PASS")
    k.add_argument("--criteria", type=Path, required=True)
    k.add_argument("--results", type=Path, required=True, help="a result file or a directory")
    k.add_argument("--uid", type=int, required=True)
    k.add_argument("--hotkey", required=True)
    k.add_argument("--netuid", type=int, required=True)
    k.add_argument("--endpoint-record", type=Path, required=True)
    k.add_argument("--now-ms", type=int, required=True)
    k.add_argument("--now-window", type=int, required=True,
                   help="the current window index; the latest N windows up to it are checked")
    k.add_argument("--signature-verifier", metavar="MODULE:FUNCTION",
                   help="override: a callable that takes the endpoint record and returns True only "
                        "if its signature verifies. The default is the repository's miner "
                        "announcement verifier")
    k.add_argument("--report-out", type=Path)
    p = sub.add_parser("propose", help="write a new plan version document (a proposal)")
    p.add_argument("--parent", type=Path, required=True)
    p.add_argument("--uid", type=int, required=True)
    p.add_argument("--stage", choices=STAGES, required=True)
    p.add_argument("--hotkey")
    p.add_argument("--netuid", type=int, default=582)
    p.add_argument("--endpoint-record", type=Path)
    p.add_argument("--now-ms", type=int)
    p.add_argument("--criteria", type=Path)
    p.add_argument("--results", type=Path, help="window results, for --stage weighted")
    p.add_argument("--now-window", type=int)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "criteria":
            doc = make_criteria(criteria_id=args.criteria_id, consecutive_windows=args.windows,
                                min_valid_responses_per_window=args.min_valid_responses,
                                max_integrity_failures_per_window=args.max_integrity_failures,
                                require_signature_verified=not args.allow_unverified_signature)
            _write_new(args.out, doc)
            print(doc["criteria_digest"], STATUS)
            return 0
        if args.command == "check":
            criteria_doc = _read_json(args.criteria)
            needs_signature = isinstance(criteria_doc, dict) \
                and isinstance(criteria_doc.get("rules"), dict) \
                and criteria_doc["rules"].get("require_signature_verified") is not False
            verifier = _load_verifier(args.signature_verifier) or (
                announcement_verifier(netuid=args.netuid, now_ms=args.now_ms,
                                      hotkey=args.hotkey) if needs_signature else None)
            endpoint = check_endpoint_record(
                _read_json(args.endpoint_record), netuid=args.netuid, now_ms=args.now_ms,
                expected_hotkey=args.hotkey, expected_uid=args.uid, signature_verifier=verifier)
            report = evaluate_criteria(criteria_doc, _load_results(args.results),
                                       endpoint, uid=args.uid, hotkey=args.hotkey,
                                       now_window=args.now_window, netuid=args.netuid)
            document = report.as_document()
            if args.report_out:
                _write_new(args.report_out, document)
            print(document["verdict"], "uid", args.uid)
            for reason in document["reasons"]:
                print(" ", json.dumps(reason, sort_keys=True))
            return 0 if report.passed else 1
        parent = _read_json(args.parent)
        endpoint = None
        if args.endpoint_record:
            if args.now_ms is None:
                raise AdmissionError("NOW_MS_REQUIRED")
            endpoint = check_endpoint_record(_read_json(args.endpoint_record),
                                             netuid=args.netuid, now_ms=args.now_ms,
                                             expected_hotkey=args.hotkey, expected_uid=args.uid)
        version = propose_version(
            parent, uid=args.uid, stage=args.stage, hotkey=args.hotkey, endpoint_check=endpoint,
            criteria=_read_json(args.criteria) if args.criteria else None,
            results=_load_results(args.results) if args.results else None,
            now_window=args.now_window, netuid=args.netuid)
        out = args.out / f"PLAN_VERSION_{version['plan_version']}_uid{args.uid}_{args.stage}.json"
        _write_new(out, version)
        print(out)
        print(version["plan_digest"], STATUS)
        return 0
    except (AdmissionError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
