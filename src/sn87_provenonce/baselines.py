"""Matched public-contract baselines: what a competent implementer builds from the disclosed
contract alone. They import only public contract modules (never truth or reference code;
tests/test_separation.py proves it by import graph and at runtime), run on the public
capsule view, and are always reported beside the reference methods. They are never chain
participants. Null results (method == baseline) are kept and shown.

Both baselines cite every bounded event (plus the completeness scope) for each finding: the
binary evidence rule gives any superset of the required refs full credit (LIMITATIONS item 3),
and the baselines say so rather than hide it. The public Type C fixture set carries each
fixture's expected invariant in its provenance; that is public fixture metadata, and the
baselines never read it.
"""

from __future__ import annotations

from typing import Any

from sn87_provenonce.institutional_v02 import contracts as ic
from sn87_provenonce.pilot import contracts as tc

METHOD_ID = "public_contract_baseline"
ABSTAIN = "INSUFFICIENT_EVIDENCE_ABSTAIN"
DEFINITION = {
    "TYPE-C-RELEASE": "Checks the disclosed workflow grammar (cardinality, order, approval, "
    "contiguous commitments, terminal release, observation window) in one pass.",
    "IC-APPROVAL-APPLICABILITY": "Abstains on declared incompleteness or ambiguity; otherwise "
    "flags STALE_APPROVAL when an action's linked review condition differs from the governing "
    "policy in force at the action.",
}
_MISSING = {"SUBMIT": "MISSING_SUBMIT_EVENT", "REVIEW": "MISSING_REVIEW_GATE",
            "VALIDATE": "MISSING_VALIDATION_GATE", "RELEASE": "MISSING_RELEASE_EVENT"}
_DUPLICATE = {"SUBMIT": "DUPLICATE_SUBMIT_EVENT", "REVIEW": "DUPLICATE_REVIEW_EVENT",
              "VALIDATE": "DUPLICATE_VALIDATION_EVENT", "RELEASE": "DUPLICATE_RELEASE_EVENT"}


def _differential(c: dict[str, Any], codes: set[str], severity: dict[str, str],
                  state: str | None = None) -> dict[str, Any]:
    refs = sorted({e["event_id"] for e in c["events"]} | {"$completeness"})
    state = state or ("FINDINGS" if codes else "NO_MATERIAL_DEVIATION")
    return {
        "schema_version": c["schema_version"], "qid": c["qid"],
        "capsule_commitment": c["evidence_commitment"], "method": METHOD_ID, "state": state,
        "rationale": f"Public-contract baseline: {state}.",
        "findings": [{"code": code, "severity": severity[code], "evidence_refs": refs,
                      "rationale": "The disclosed contract rule fails in the bound record.",
                      "confidence": "1"} for code in sorted(codes)],
    }


def type_c_release(c: dict[str, Any]) -> dict[str, Any]:
    tc.validate_capsule(c)
    if not c["completeness"]["complete"]:
        return _differential(c, set(), tc.DEFECT_SEVERITY, ABSTAIN)
    events, order = c["events"], c["policy"]["required_event_order"]
    kinds = [e["kind"] for e in events]
    codes = {_MISSING[k] for k in order if k not in kinds}
    codes |= {_DUPLICATE[k] for k in order if kinds.count(k) > 1}
    if not codes and [kinds.index(k) for k in order] != sorted(kinds.index(k) for k in order):
        codes.add("INVALID_WORKFLOW_ORDER")
    links = zip(events, events[1:], strict=False)
    if any(a["output_commitment"] != b["input_commitment"] for a, b in links):
        codes.add("EVIDENCE_CHAIN_BREAK")
    if "REVIEW" in kinds and not any(e.get("approved") is True for e in events
                                     if e["kind"] == "REVIEW"):
        codes.add("REVIEW_NOT_APPROVED")
    release = kinds.index("RELEASE") if "RELEASE" in kinds else None
    if release is not None and release < len(kinds) - 1:
        codes.add("EVENT_AFTER_RELEASE")
    submit = kinds.index("SUBMIT") if "SUBMIT" in kinds else None
    if any(k == "OBSERVE" and (submit is None or release is None or not submit < i < release)
           for i, k in enumerate(kinds)):
        codes.add("OBSERVATION_OUTSIDE_WORKFLOW")
    return _differential(c, codes, tc.DEFECT_SEVERITY)


def ic_approval_applicability(c: dict[str, Any]) -> dict[str, Any]:
    ic.validate_capsule(c)
    policy = c["policy"]
    abstain = _differential(c, set(), ic.DEFECT_SEVERITY, ABSTAIN)
    if not all(policy["completeness"].values()) or policy["mapping_uncertainty"] != "NONE":
        return abstain
    by_id = {e["event_id"]: e for e in c["events"]}
    of = {k: [e for e in c["events"] if e["kind"] == k] for k in ic.FIELDS}
    for action in of["ACTION"]:
        links = [x for x in of["APPROVAL_LINK"] if x["local_token"] == action["approval_token"]]
        approval = by_id.get(links[0]["approval_ref"], {}) if len(links) == 1 else {}
        review = by_id.get(approval.get("review_ref"), {})
        governing = [v for v in of["POLICY_VERSION"]
                     if v["at"] < action["at"] and v["effective_at"] <= action["at"]]
        latest = max((v["effective_at"] for v in governing), default=None)
        current = [v for v in governing if v["effective_at"] == latest]
        if review.get("kind") != "REVIEW" or len(current) != 1:  # none, or an ambiguous tie
            return abstain
        current = current[0]
        if current["condition_commitment"] != review["condition_commitment"]:
            return _differential(c, {"STALE_APPROVAL"}, ic.DEFECT_SEVERITY)
    return _differential(c, set(), ic.DEFECT_SEVERITY)


BASELINES = {"TYPE-C-RELEASE": type_c_release,
             "IC-APPROVAL-APPLICABILITY": ic_approval_applicability}
