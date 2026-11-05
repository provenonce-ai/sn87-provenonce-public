"""Map one permitted source export to IC capsules and a disclosure record.

The mapping reads only the fields the permission allows (everything else is withheld before any
mapping code sees it), validates every capsule with the public contract, and rejects a whole
case with a stated reason instead of repairing it. Opaque free text never enters a capsule:
condition and artifact text become commitments.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from sn87_provenonce import profile as profiles
from sn87_provenonce.canonical import canonical_bytes, evidence_commitment
from sn87_provenonce.institutional_v02 import contracts as ic

MAPPING_VERSION = "launch-approvals-to-institution/0.2@1"
# Same mapping, text commitments keyed by a customer-held HMAC key. A separate version so a
# config, a bundle and a disclosure always say which scheme produced the commitments.
MAPPING_VERSION_HMAC = "launch-approvals-to-institution/0.2@2-hmac"
SCHEME_PLAIN = "plain-sha256/1"
SCHEME_HMAC = "hmac-sha256/1"
CUSTOMER_EXPORT = "CUSTOMER_EXPORT"
FICTIONAL = "FICTIONAL"
# The minimal set the repository needs. CUSTOMER_EXPORT is a real owner's data: text commitments
# are keyed. FICTIONAL is synthetic data that holds no secret (the committed fixtures and demo
# packs): plain commitments, and only when the source and permission both declare it fictional.
# There is no class for unlabelled or "internal" real data: it is refused until a class is added.
EXPORT_CLASSES = (CUSTOMER_EXPORT, FICTIONAL)
MIN_KEY_BYTES = 32
MIN_DISTINCT_KEY_BYTES = 16
SOURCE_SCHEMA_ID = "fictional-launch-approvals/1"
DISCLOSURE_SCHEMA = "sn87-source-disclosure/0.1"
PROFILE_ID = "IC-FIRST-LIGHT-MIN-1"
FIXTURES = Path(__file__).with_name("fixtures")
_DOMAIN = "SN87:SOURCE:" + SOURCE_SCHEMA_ID


def object_commitment(value: Any, domain: str) -> str:
    """Domain-separated sha256 over the canonical bytes (source domains, not capsule schemas)."""
    return "sha256:" + hashlib.sha256(domain.encode() + b"\x00" + canonical_bytes(value)
                                       ).hexdigest()
_KIND = {"policy_published": "POLICY_VERSION", "review_signed": "REVIEW",
         "approval_issued": "APPROVAL", "token_bound": "APPROVAL_LINK", "handoff": "HANDOFF",
         "step_executed": "ACTION"}
_SYSTEM = {"POLICY_VERSION": "src-governance", "REVIEW": "src-review", "APPROVAL": "src-authority",
           "APPROVAL_LINK": "src-handoff", "HANDOFF": "src-handoff", "ACTION": "src-work"}


class CommitmentKey:
    """A customer-held HMAC key. Never stored in the repo; the repr, str and pickling are
    redacted so the bytes cannot reach a log, an exception message or an output by accident."""
    __slots__ = ("_key",)

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, (bytes, bytearray)) or len(key) < MIN_KEY_BYTES:
            raise ValueError(f"COMMITMENT_KEY_INVALID: need at least {MIN_KEY_BYTES} bytes")
        if len(set(key)) < MIN_DISTINCT_KEY_BYTES:  # constant or patterned keys are guessable
            raise ValueError("COMMITMENT_KEY_INVALID: too little variety; use random bytes "
                             "(the key's entropy is the key holder's responsibility)")
        self._key = bytes(key)

    @classmethod
    def from_hex(cls, text: str) -> CommitmentKey:
        try:
            return cls(bytes.fromhex(text.strip()))
        except ValueError:
            raise ValueError("COMMITMENT_KEY_INVALID: not hex or too short") from None

    def mac(self, message: bytes) -> bytes:
        return hmac.new(self._key, message, hashlib.sha256).digest()

    def __repr__(self) -> str:
        return "CommitmentKey(<redacted>)"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("CommitmentKey is not serialisable")


def text_commitment(value: str, scheme: str = SCHEME_PLAIN,
                    key: CommitmentKey | bytes | None = None) -> str:
    """Commitment to one source text. Both schemes yield the public ``sha256:<hex>`` form; which
    scheme produced it is recorded by the mapping version, never inferred from the string."""
    if scheme == SCHEME_PLAIN:
        return object_commitment(value, _DOMAIN + ":text")
    if scheme == SCHEME_HMAC:
        if key is None:
            raise ValueError("COMMITMENT_KEY_REQUIRED")
        key = key if isinstance(key, CommitmentKey) else CommitmentKey(key)
        return "sha256:" + key.mac(
            (_DOMAIN + ":text:hmac/1").encode() + b"\x00" + canonical_bytes(value)).hex()
    raise ValueError("UNKNOWN_COMMITMENT_SCHEME")


def verify_text_commitment(value: str, commitment: str, scheme: str = SCHEME_PLAIN,
                           key: CommitmentKey | bytes | None = None) -> bool:
    """Constant-time check of a commitment under its recorded scheme (plain stays verifiable)."""
    expected = text_commitment(value, scheme, key).encode()
    try:
        given = commitment.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        return False  # not a commitment string at all: a mismatch, not an error
    return hmac.compare_digest(expected, given)


def resolve_export_class(source: dict[str, Any], permission: dict[str, Any],
                         export_class: str | None = None) -> str:
    """The one export class. The permission must declare it (absent: refused); the argument and
    the source may repeat it but never differ from it. The match is exact: an unknown or
    non-canonical value such as ``customer_export`` is refused, never treated as plain."""
    declared = permission.get("export_class")
    if declared is None:
        raise ValueError("EXPORT_CLASS_REQUIRED: the permission must declare export_class")
    seen = [v for v in (export_class, declared, source.get("export_class")) if v is not None]
    for value in seen:
        if type(value) is not str or value not in EXPORT_CLASSES:
            raise ValueError("EXPORT_CLASS_UNKNOWN")
    if len(set(seen)) > 1:
        raise ValueError("EXPORT_CLASS_CONFLICT")
    return declared


def _resolve_mode(source: dict[str, Any], permission: dict[str, Any], mapping_version: str | None,
                  key: CommitmentKey | bytes | None, export_class: str | None
                  ) -> tuple[str, str, CommitmentKey | None, str]:
    """(mapping_version, scheme, key, export_class). A customer export is always HMAC and is
    refused without a key. Plain commitments need the explicit FICTIONAL class, declared by the
    permission and consistent with the synthetic source; an explicit HMAC version or a supplied
    key selects HMAC for either class."""
    klass = resolve_export_class(source, permission, export_class)
    if klass == FICTIONAL and not is_fictional(source, permission):
        raise ValueError("EXPORT_CLASS_FICTIONAL_MISMATCH")
    keyed = mapping_version == MAPPING_VERSION_HMAC or key is not None or klass == CUSTOMER_EXPORT
    if klass == CUSTOMER_EXPORT and mapping_version not in (None, MAPPING_VERSION_HMAC):
        raise ValueError("CUSTOMER_EXPORT_REQUIRES_HMAC_MAPPING")
    if not keyed:
        return mapping_version or MAPPING_VERSION, SCHEME_PLAIN, None, klass
    if mapping_version not in (None, MAPPING_VERSION_HMAC):
        raise ValueError("COMMITMENT_KEY_WITH_PLAIN_MAPPING_VERSION")
    if key is None:
        raise ValueError("COMMITMENT_KEY_REQUIRED: a customer export commits text with a "
                         "customer-held key")
    return (MAPPING_VERSION_HMAC, SCHEME_HMAC,
            key if isinstance(key, CommitmentKey) else CommitmentKey(key), klass)


def _scope(e: dict[str, Any]) -> dict[str, str]:  # SEND is the only action the contract admits
    return {"mission": e["mission"], "action": "SEND", "recipient": e["recipient"]}


_FIELDS = {
    "POLICY_VERSION": lambda e, t: {"effective_at": e["effective_ts"],
                                    "version_id": e["policy_ref"],
                                 "condition_commitment": t(e["condition_text"])},
    "REVIEW": lambda e, t: {"condition_commitment": t(e["condition_text"]), "scope": _scope(e),
                         "approved": e["approved"], "actor_id": e["reviewer"],
                         "artifact_commitment": t(e["artifact_text"])},
    "APPROVAL": lambda e, t: {"review_ref": e["review_id"], "scope": _scope(e),
                           "artifact_commitment": t(e["artifact_text"]),
                           "valid_until": e["valid_until"], "actor_id": e["approver"]},
    "APPROVAL_LINK": lambda e, t: {"local_token": e["token"], "approval_ref": e["approval_id"]},
    "HANDOFF": lambda e, t: {"from_actor": e["from_agent"], "to_actor": e["to_agent"],
                          "from_episode": e["from_step"], "to_episode": e["to_step"],
                          "carried_token": e["token"], "input_commitment": t(e["input_text"]),
                          "output_commitment": t(e["output_text"])},
    "ACTION": lambda e, t: {"episode": e["step"], "actor_id": e["agent"],
                            "approval_token": e["token"],
                         "scope": _scope(e), "artifact_commitment": t(e["artifact_text"])},
}


def load_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    """(FICTIONAL source document, its permission record)."""
    return (json.loads((FIXTURES / "fictional_launch_approvals.json").read_text("utf-8")),
            json.loads((FIXTURES / "fictional_launch_permission.json").read_text("utf-8")))


def permission_digest(permission: dict[str, Any]) -> str:
    """Identity of the grant. ``expires_at`` is excluded: a renewal is a time bound checked at
    execution, not a change of meaning; everything else (scope, fields, meaning) is bound."""
    return object_commitment({k: v for k, v in permission.items() if k != "expires_at"},
                             _DOMAIN + ":permission")


def make_config(source: dict[str, Any], permission: dict[str, Any], *,
                mapping_version: str | None = None,
                profile_commitment: str | None = None) -> dict[str, Any]:
    """One permitted source configuration; ``config_id`` commits to its four parts. The export
    class is part of the permission and so of ``permission_digest``; a permission without a
    valid class has no configuration. A customer export defaults to the keyed mapping version."""
    klass = resolve_export_class(source, permission)
    if mapping_version is None:
        mapping_version = MAPPING_VERSION_HMAC if klass == CUSTOMER_EXPORT else MAPPING_VERSION
    parts = {"source_schema_id": source["schema_id"], "permission_digest": permission_digest(
        permission), "mapping_version": mapping_version,
        "profile_commitment": profile_commitment or profiles.load(PROFILE_ID).commitment}
    return {"config_id": object_commitment(parts, _DOMAIN + ":config"), **parts,
            "permission_id": permission["permission_id"],
            "meaning_version": permission["meaning_version"]}


def _project(obj: Any, allowed: set[str], withheld: dict[str, int], read: set[str]) -> Any:
    """Copy of the source with every non-allowed key dropped (and counted)."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in allowed:
                read.add(key)
                out[key] = _project(value, allowed, withheld, read)
            else:
                withheld[key] = withheld.get(key, 0) + 1
        return out
    if isinstance(obj, list):
        return [_project(v, allowed, withheld, read) for v in obj]
    return obj


def _capsule(case: dict[str, Any], window: dict[str, str], config: dict[str, Any],
             t: Any = text_commitment) -> dict[str, Any]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    events = []
    for entry in case["log"]:
        if entry["type"] not in _KIND:
            raise ValueError("UNKNOWN_ENTRY_TYPE:" + str(entry["type"]))
        kind = _KIND[entry["type"]]
        by_kind.setdefault(kind, []).append(entry)
        events.append({"event_id": entry["id"], "kind": kind, "at": entry["ts"],
                       "source_system": _SYSTEM[kind], **_FIELDS[kind](entry, t)})
    unknown = [g for g in case["gaps"] if g not in _KIND]
    if unknown:
        raise ValueError("UNKNOWN_GAP:" + ",".join(map(str, unknown)))
    gaps = {_KIND[g] for g in case["gaps"]}
    capsule = {
        "schema_version": ic.SCHEMA, "qid": "src-" + case["case_ref"],
        "pipeline_id": case["pipeline"], "events": events,
        "source_commitments": [object_commitment(v, _DOMAIN + ":log:" + k)
                               for k, v in sorted(by_kind.items())],
        "policy": {"qid": "src-" + case["case_ref"], "grammar": "FIRST_LIGHT_MINIMAL_TYPE_C_0.2",
                   "agents": {"origin": case["origin_agent"], "successor": case["successor_agent"]},
                   "reviewer": case["reviewer_id"], "approver": case["approver_id"],
                   "episode_range": [1, 2, 3],
                   "completeness": {k: k not in gaps for k in ic.FIELDS},
                   "mapping_uncertainty": "NONE"},
        "nonce": "n-" + object_commitment([config["config_id"], case["case_ref"]],
                                          _DOMAIN + ":nonce")[7:31],
        "timestamp": window["closed_at"],
    }
    capsule["evidence_commitment"] = evidence_commitment(capsule)
    ic.validate_capsule(capsule)
    return capsule


def is_fictional(source: dict[str, Any], permission: dict[str, Any]) -> bool:
    """Synthetic provenance, as declared by both the source export and its permission."""
    return (permission.get("fictional") is True
            and str(source.get("schema_id", "")).startswith("fictional-"))


def _case_digest(case: dict[str, Any]) -> str:
    """Rejects are identified by index and a digest of the PROJECTED case (permitted fields
    only, canonical JSON, domain-separated), so a withheld value is never echoed or hashed."""
    try:
        return object_commitment(case, _DOMAIN + ":reject")
    except ValueError:  # a case the canonical profile cannot represent (float, non-NFC, oversize)
        return object_commitment({"unrepresentable": True}, _DOMAIN + ":reject")


def map_source(source: dict[str, Any], permission: dict[str, Any], *,
               mapping_version: str | None = None, profile_commitment: str | None = None,
               commitment_key: CommitmentKey | bytes | None = None,
               export_class: str | None = None
               ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(capsules, disclosure) for one export under one permission.

    ``export_class`` (or the same field on the permission or source) set to ``CUSTOMER_EXPORT``
    makes text commitments HMAC-SHA256 under ``commitment_key`` and refuses to run without it.
    The key is only ever used in memory; it is not recorded in any output."""
    mapping_version, scheme, ckey, klass = _resolve_mode(
        source, permission, mapping_version, commitment_key, export_class)
    config = make_config(source, permission, mapping_version=mapping_version,
                         profile_commitment=profile_commitment)
    allowed = set(permission["allowed_fields"])
    capsules, rejects = [], []
    withheld: dict[str, int] = {}
    mapped_fields: set[str] = set()
    entries_offered = entries_mapped = 0
    for index, raw in enumerate(source["cases"]):
        entries_offered += len(raw.get("log", []))
        case_withheld: dict[str, int] = {}
        read: set[str] = set()
        case = _project(raw, allowed, case_withheld, read)
        for key, count in case_withheld.items():  # withheld is reported for every offered case
            withheld[key] = withheld.get(key, 0) + count
        try:
            capsules.append(_capsule(
                case, source["window"], config,
                lambda text: text_commitment(text, scheme, ckey)))
        except KeyError as missing:
            rejects.append({"case_index": index, "case_digest": _case_digest(case),
                            "reason": f"MISSING_FIELD:{missing.args[0]}"})
        except (ValueError, TypeError) as error:
            rejects.append({"case_index": index, "case_digest": _case_digest(case),
                            "reason": f"CONTRACT_INVALID:{error}"})
        else:
            mapped_fields |= read
            entries_mapped += len(case["log"])
    disclosure = {
        "schema_version": DISCLOSURE_SCHEMA, "config": config, "export_id": source["export_id"],
        "window": source["window"], "label": "FICTIONAL",
        "offered": {"cases": len(source["cases"]), "entries": entries_offered},
        "mapped": {"cases": len(capsules), "entries": entries_mapped},
        "mapped_fields": sorted(mapped_fields), "withheld_fields": dict(sorted(withheld.items())),
        "rejects": rejects,
    }
    disclosure["commitment_scheme"] = scheme
    disclosure["export_class"] = klass
    canonical_bytes(disclosure)
    return capsules, disclosure
