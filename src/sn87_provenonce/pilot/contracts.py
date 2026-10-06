"""Public contract of class TYPE-C-RELEASE: capsule and differential validation only.

Truth and the reference methods live in ``pilot.reference`` (evaluator-only)."""

from __future__ import annotations

import re
from typing import Any

from sn87_provenonce.canonical import canonical_bytes, evidence_commitment
from sn87_provenonce.protocol.v0alpha1 import ResponseState
from sn87_provenonce.simulation.type_c import (
    EventKind,
    MutationProvenance,
    TypeCFixture,
    WorkflowEvent,
    workflow_contract,
)

STATES = {s.value for s in ResponseState}
SEVERITY = {"LOW": 0.25, "MEDIUM": 0.5, "HIGH": 1.0}
DEFECT_SEVERITY = {
    "MISSING_SUBMIT_EVENT": "HIGH",
    "MISSING_REVIEW_GATE": "HIGH",
    "MISSING_VALIDATION_GATE": "HIGH",
    "MISSING_RELEASE_EVENT": "MEDIUM",
    "DUPLICATE_SUBMIT_EVENT": "MEDIUM",
    "DUPLICATE_REVIEW_EVENT": "MEDIUM",
    "DUPLICATE_VALIDATION_EVENT": "MEDIUM",
    "DUPLICATE_RELEASE_EVENT": "MEDIUM",
    "INVALID_WORKFLOW_ORDER": "MEDIUM",
    "REVIEW_NOT_APPROVED": "HIGH",
    "EVIDENCE_CHAIN_BREAK": "HIGH",
    "EVENT_AFTER_RELEASE": "HIGH",
    "OBSERVATION_OUTSIDE_WORKFLOW": "LOW",
}


def capsule_from_fixture(
    f: TypeCFixture,
    *,
    qid: str | None = None,
    pipeline_id: str = "fixture-pipeline",
    nonce: str = "fixture-nonce-0001",
    timestamp: str = "2026-09-27T22:25:00Z",
) -> dict[str, Any]:
    qid = qid or f.fixture_id
    completeness = {"complete": f.evidence_complete, "scope": "ENTIRE_SYNTHETIC_RELEASE_TRACE"}
    c = {
        "schema_version": "gra/0.1",
        "qid": qid,
        "pipeline_id": pipeline_id,
        "completeness": completeness,
        "events": [event.to_dict() for event in f.events],
        "source_commitments": [f.events[0].input_commitment],
        "policy": workflow_contract()
        | {"qid": qid, "completeness": completeness, "oracle": "TYPE_C_TWO_REFERENCES"},
        "nonce": nonce,
        "timestamp": timestamp,
    }
    c["evidence_commitment"] = evidence_commitment(c)
    return c


def validate_capsule(c: dict[str, Any]) -> None:
    canonical_bytes(c)
    expected = {
        "schema_version",
        "qid",
        "pipeline_id",
        "completeness",
        "events",
        "source_commitments",
        "policy",
        "nonce",
        "timestamp",
        "evidence_commitment",
    }
    if set(c) != expected or c["schema_version"] != "gra/0.1":
        raise ValueError("capsule schema/version")
    for key in ("qid", "pipeline_id", "nonce"):
        if not isinstance(c[key], str) or re.fullmatch(r"[a-zA-Z0-9_-]{8,128}", c[key]) is None:
            raise ValueError("invalid capsule identity")
    if (
        c["completeness"]
        not in (
            {"complete": True, "scope": "ENTIRE_SYNTHETIC_RELEASE_TRACE"},
            {"complete": False, "scope": "ENTIRE_SYNTHETIC_RELEASE_TRACE"},
        )
        or type(c["completeness"]["complete"]) is not bool
    ):
        raise ValueError("invalid completeness boundary")
    policy = workflow_contract() | {
        "qid": c["qid"],
        "completeness": c["completeness"],
        "oracle": "TYPE_C_TWO_REFERENCES",
    }
    if c["policy"] != policy:
        raise ValueError("unrecognized policy")
    if not isinstance(c["events"], list) or not 1 <= len(c["events"]) <= 64:
        raise ValueError("event bounds")
    for event in c["events"]:
        if set(event) - {"event_id", "kind", "input_commitment", "output_commitment", "approved"}:
            raise ValueError("unknown event field")
        if "approved" in event and type(event["approved"]) is not bool:
            raise ValueError("approval must be boolean")
    to_fixture(c)
    if not isinstance(c["source_commitments"], list) or not c["source_commitments"]:
        raise ValueError("missing source commitments")
    if any(
        not isinstance(x, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", x) is None
        for x in c["source_commitments"]
    ):
        raise ValueError("invalid source commitment")
    if c["evidence_commitment"] != evidence_commitment(c):
        raise ValueError("broken evidence commitment")


def to_fixture(c: dict[str, Any]) -> TypeCFixture:
    events = tuple(
        WorkflowEvent(kind=EventKind(e["kind"]), **{k: v for k, v in e.items() if k != "kind"})
        for e in c["events"]
    )
    return TypeCFixture(
        c["qid"],
        "PRIVATE_OR_PUBLIC_UNCLASSIFIED",
        c["completeness"]["complete"],
        events,
        MutationProvenance(None, "PILOT_INPUT", "UNDECLARED_TO_MINER"),
    )


def validate_differential(c: dict[str, Any], d: dict[str, Any]) -> None:
    canonical_bytes(d)
    if (
        set(d)
        != {
            "schema_version",
            "qid",
            "capsule_commitment",
            "method",
            "state",
            "rationale",
            "findings",
        }
        or d["schema_version"] != "gra/0.1"
    ):
        raise ValueError("differential schema/version")
    if d["qid"] != c["qid"] or d["capsule_commitment"] != c["evidence_commitment"]:
        raise ValueError("differential not bound to capsule")
    if d["state"] not in STATES or not isinstance(d["method"], str) or not d["method"].strip():
        raise ValueError("invalid response state/method")
    if not isinstance(d["rationale"], str) or not 1 <= len(d["rationale"].strip()) <= 4096:
        raise ValueError("required rationale")
    if not isinstance(d["findings"], list) or len(d["findings"]) > 32:
        raise ValueError("finding bounds")
    if bool(d["findings"]) != (d["state"] == "FINDINGS"):
        raise ValueError("findings/state contradiction")
    valid_refs = {e["event_id"] for e in c["events"]} | {"$completeness"}
    for f in d["findings"]:
        if set(f) != {"code", "severity", "evidence_refs", "rationale", "confidence"}:
            raise ValueError("finding schema")
        if (
            not isinstance(f["code"], str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", f["code"]) is None
        ):
            raise ValueError("invalid finding code")
        if (
            f["severity"] not in SEVERITY
            or not isinstance(f["rationale"], str)
            or not f["rationale"].strip()
        ):
            raise ValueError("required finding severity/rationale")
        refs = f["evidence_refs"]
        if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
            raise ValueError("required distinct evidence refs")
        if not set(refs) <= valid_refs:
            raise ValueError("evidence reference outside capsule")
        if (
            not isinstance(f["confidence"], str)
            or re.fullmatch(r"(?:0(?:\.[0-9]{1,9})?|1(?:\.0{1,9})?)", f["confidence"]) is None
        ):
            raise ValueError("confidence must be bounded decimal string")
