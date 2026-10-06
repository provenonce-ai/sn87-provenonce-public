"""Public contract of IC-APPROVAL-APPLICABILITY: capsule and differential validation only.

Truth and the reference methods live in ``references`` (evaluator-only)."""

from __future__ import annotations

import re

from sn87_provenonce.canonical import canonical_bytes, check_timestamp, evidence_commitment

SCHEMA = "institution/0.2"
STATES = {"FINDINGS", "NO_MATERIAL_DEVIATION", "INSUFFICIENT_EVIDENCE_ABSTAIN"}
SEVERITY = {"LOW": 0.25, "MEDIUM": 0.5, "HIGH": 1.0}
DEFECT_SEVERITY = {"STALE_APPROVAL": "HIGH"}
BASE = {"event_id", "kind", "at", "source_system"}
FIELDS = {
    "POLICY_VERSION": {"effective_at", "version_id", "condition_commitment"},
    "REVIEW": {
        "condition_commitment",
        "scope",
        "approved",
        "actor_id",
        "artifact_commitment",
    },
    "APPROVAL": {
        "review_ref",
        "scope",
        "artifact_commitment",
        "valid_until",
        "actor_id",
    },
    "APPROVAL_LINK": {"local_token", "approval_ref"},
    "HANDOFF": {
        "from_actor",
        "to_actor",
        "from_episode",
        "to_episode",
        "carried_token",
        "input_commitment",
        "output_commitment",
    },
    "ACTION": {"episode", "actor_id", "approval_token", "scope", "artifact_commitment"},
}


def _id(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
        raise ValueError("bounded identifier required")


def validate_capsule(c):
    canonical_bytes(c)
    if (
        set(c)
        != {
            "schema_version",
            "qid",
            "pipeline_id",
            "events",
            "source_commitments",
            "policy",
            "nonce",
            "timestamp",
            "evidence_commitment",
        }
        or c["schema_version"] != SCHEMA
    ):
        raise ValueError("capsule schema")
    for k in ("qid", "pipeline_id", "nonce"):
        _id(c[k])
    check_timestamp(c["timestamp"])
    p = c["policy"]
    if (
        not isinstance(p, dict)
        or set(p)
        != {
            "qid",
            "grammar",
            "agents",
            "reviewer",
            "approver",
            "episode_range",
            "completeness",
            "mapping_uncertainty",
        }
        or p["qid"] != c["qid"]
        or p["grammar"] != "FIRST_LIGHT_MINIMAL_TYPE_C_0.2"
        or p["episode_range"] != [1, 2, 3]
        or any(type(v) is not int for v in p["episode_range"])
    ):
        raise ValueError("policy binding")
    if (
        not isinstance(p["agents"], dict)
        or set(p["agents"]) != {"origin", "successor"}
        or p["agents"]["origin"] == p["agents"]["successor"]
    ):
        raise ValueError("two distinct agents")
    for v in [*p["agents"].values(), p["reviewer"], p["approver"]]:
        _id(v)
    if (
        not isinstance(p["completeness"], dict)
        or set(p["completeness"]) != set(FIELDS)
        or any(type(v) is not bool for v in p["completeness"].values())
    ):
        raise ValueError("declared record-class coverage")
    if p["mapping_uncertainty"] not in ("NONE", "DECLARED_AMBIGUITY"):
        raise ValueError("mapping declaration")
    if not isinstance(c["events"], list) or not 1 <= len(c["events"]) <= 64:
        raise ValueError("event bounds")
    ids = []
    for e in c["events"]:
        if (
            not isinstance(e, dict)
            or e.get("kind") not in FIELDS
            or set(e) != BASE | FIELDS[e["kind"]]
        ):
            raise ValueError("typed event schema")
        ids.append(e["event_id"])
        for k, v in e.items():
            if k in ("at", "effective_at", "valid_until"):
                check_timestamp(v)
            elif k in ("episode", "from_episode", "to_episode"):
                if type(v) is not int or v not in (1, 2, 3):
                    raise ValueError("episode integer")
            elif k == "approved":
                if type(v) is not bool:
                    raise ValueError("strict approval boolean")
            elif k.endswith("commitment"):
                if not isinstance(v, str) or re.fullmatch("sha256:[0-9a-f]{64}", v) is None:
                    raise ValueError("commitment")
            elif k == "scope":
                if (
                    not isinstance(v, dict)
                    or set(v) != {"mission", "action", "recipient"}
                    or v["action"] != "SEND"
                ):
                    raise ValueError("declared scope")
                for item in v.values():
                    _id(item)
            else:
                _id(v)
        if e["at"] > c["timestamp"]:
            raise ValueError("future observation")
    if len(set(ids)) != len(ids):
        raise ValueError("unique event ids")
    if (
        not isinstance(c["source_commitments"], list)
        or not 1 <= len(c["source_commitments"]) <= 32
        or any(
            not isinstance(v, str) or re.fullmatch("sha256:[0-9a-f]{64}", v) is None
            for v in c["source_commitments"]
        )
    ):
        raise ValueError("source commitments")
    if c["evidence_commitment"] != evidence_commitment(c):
        raise ValueError("broken evidence commitment")


def validate_differential(c, d):
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
        or d["schema_version"] != SCHEMA
    ):
        raise ValueError("differential schema")
    if d["qid"] != c["qid"] or d["capsule_commitment"] != c["evidence_commitment"]:
        raise ValueError("capsule binding")
    if d["state"] not in STATES or not isinstance(d["method"], str) or not d["method"].strip():
        raise ValueError("method/state")
    if not isinstance(d["rationale"], str) or not 1 <= len(d["rationale"].strip()) <= 4096:
        raise ValueError("rationale bounds")
    if (
        not isinstance(d["findings"], list)
        or len(d["findings"]) > 32
        or bool(d["findings"]) != (d["state"] == "FINDINGS")
    ):
        raise ValueError("findings/state")
    refs = {e["event_id"] for e in c["events"]} | {"$completeness"}
    for f in d["findings"]:
        if set(f) != {"code", "severity", "evidence_refs", "rationale", "confidence"}:
            raise ValueError("finding fields")
        if (
            not isinstance(f["code"], str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", f["code"]) is None
        ):
            raise ValueError("finding code")
        if (
            f["severity"] not in SEVERITY
            or not isinstance(f["rationale"], str)
            or not 1 <= len(f["rationale"].strip()) <= 4096
        ):
            raise ValueError("finding rationale/severity")
        right = f["evidence_refs"]
        if (
            not isinstance(right, list)
            or not right
            or any(not isinstance(x, str) for x in right)
            or len(right) != len(set(right))
            or not set(right) <= refs
        ):
            raise ValueError("evidence references")
        if (
            not isinstance(f["confidence"], str)
            or re.fullmatch(r"(?:0(?:\.[0-9]{1,9})?|1(?:\.0{1,9})?)", f["confidence"]) is None
        ):
            raise ValueError("required confidence")
