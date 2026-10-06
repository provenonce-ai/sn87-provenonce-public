"""Map one permitted source export to IC capsules and a disclosure record.

The mapping reads only the fields the permission allows (everything else is withheld before any
mapping code sees it), validates every capsule with the public contract, and rejects a whole
case with a stated reason instead of repairing it. Opaque free text never enters a capsule:
condition and artifact text become commitments.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sn87_provenonce import profile as profiles
from sn87_provenonce.canonical import canonical_bytes, evidence_commitment
from sn87_provenonce.institutional_v02 import contracts as ic

MAPPING_VERSION = "launch-approvals-to-institution/0.2@1"
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


def _text(value: str) -> str:
    return object_commitment(value, _DOMAIN + ":text")


def _scope(e: dict[str, Any]) -> dict[str, str]:  # SEND is the only action the contract admits
    return {"mission": e["mission"], "action": "SEND", "recipient": e["recipient"]}


_FIELDS = {
    "POLICY_VERSION": lambda e: {"effective_at": e["effective_ts"], "version_id": e["policy_ref"],
                                 "condition_commitment": _text(e["condition_text"])},
    "REVIEW": lambda e: {"condition_commitment": _text(e["condition_text"]), "scope": _scope(e),
                         "approved": e["approved"], "actor_id": e["reviewer"],
                         "artifact_commitment": _text(e["artifact_text"])},
    "APPROVAL": lambda e: {"review_ref": e["review_id"], "scope": _scope(e),
                           "artifact_commitment": _text(e["artifact_text"]),
                           "valid_until": e["valid_until"], "actor_id": e["approver"]},
    "APPROVAL_LINK": lambda e: {"local_token": e["token"], "approval_ref": e["approval_id"]},
    "HANDOFF": lambda e: {"from_actor": e["from_agent"], "to_actor": e["to_agent"],
                          "from_episode": e["from_step"], "to_episode": e["to_step"],
                          "carried_token": e["token"], "input_commitment": _text(e["input_text"]),
                          "output_commitment": _text(e["output_text"])},
    "ACTION": lambda e: {"episode": e["step"], "actor_id": e["agent"], "approval_token": e["token"],
                         "scope": _scope(e), "artifact_commitment": _text(e["artifact_text"])},
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
                mapping_version: str = MAPPING_VERSION,
                profile_commitment: str | None = None) -> dict[str, Any]:
    """One permitted source configuration; ``config_id`` commits to its four parts."""
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


def _capsule(case: dict[str, Any], window: dict[str, str], config: dict[str, Any]
             ) -> dict[str, Any]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    events = []
    for entry in case["log"]:
        if entry["type"] not in _KIND:
            raise ValueError("UNKNOWN_ENTRY_TYPE:" + str(entry["type"]))
        kind = _KIND[entry["type"]]
        by_kind.setdefault(kind, []).append(entry)
        events.append({"event_id": entry["id"], "kind": kind, "at": entry["ts"],
                       "source_system": _SYSTEM[kind], **_FIELDS[kind](entry)})
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
               mapping_version: str = MAPPING_VERSION, profile_commitment: str | None = None
               ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(capsules, disclosure) for one export under one permission."""
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
            capsules.append(_capsule(case, source["window"], config))
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
    canonical_bytes(disclosure)
    return capsules, disclosure
