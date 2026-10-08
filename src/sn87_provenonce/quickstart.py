"""The institution/0.2 quickstart: build, send, answer and score one public fixture per family.

Everything runs in one process, offline. A capsule from the public generator
(``institutional_v02.fixtures.build_case``) is sent as canonical bytes to the public miner
method (``miners.witness_ic.approval_witness``), the response comes back as canonical bytes,
and the public scorer (``scoring.score_response``) scores it against the truth committed in
``institutional_v02/public_fixture_truth.json``. The public tree has no reference executor, so
that file is the only source of truth here; each entry is bound to its capsule's evidence
commitment and the run refuses a capsule that does not match.

What this shows: the institution/0.2 capsule contract, the miner method, the byte boundary
(the same bytes ``scripts/miner_serve.py`` carries over localhost HTTP), and the scorer.
What it does not show: signed transport, the chain, or hidden instances. The six integrity
predicates are asserted true locally, not verified.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from sn87_provenonce import miners
from sn87_provenonce.canonical import canonical_bytes, parse_canonical
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as BINDING
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.scoring import Integrity, score_response, wire

TRUTH_SCHEMA = "sn87-public-fixture-truth/0.1"
FAMILIES = ("stale_authority", "fresh_review", "incomplete")
METHOD_ID = "approval_witness"
SCOPE = (
    "local, offline, in-process; unsigned wire bytes; synthetic public fixtures scored against "
    "published truth; no signed transport, no chain, no hidden instances"
)


def load_public_truth() -> dict[str, Any]:
    document = json.loads(
        files("sn87_provenonce.institutional_v02").joinpath("public_fixture_truth.json")
        .read_text(encoding="utf-8")
    )
    if document.get("schema") != TRUTH_SCHEMA or document.get("class_id") != BINDING.class_id:
        raise ValueError("public fixture truth file has an unexpected schema or class")
    return document


def run_case(family: str, truth_document: dict[str, Any]) -> dict[str, Any]:
    entry = truth_document["cases"][family]
    capsule = build_case(family)
    if capsule["evidence_commitment"] != entry["capsule_commitment"]:
        raise ValueError(f"{family}: capsule does not match the committed fixture truth")
    miner = miners.for_class(BINDING.class_id)[METHOD_ID]
    request_bytes = canonical_bytes(capsule)
    response_bytes = canonical_bytes(miner(parse_canonical(request_bytes)))
    response = parse_canonical(response_bytes)
    # Eq. 1 predicates are supplied by transport in a real round; there is none here.
    integrity = Integrity(True, True, True, True, True, True)
    row = score_response(BINDING, capsule, entry["truth"], response, integrity)
    return {
        "family": family,
        "capsule_commitment": capsule["evidence_commitment"],
        "request_bytes": len(request_bytes),
        "response_bytes": len(response_bytes),
        "miner_state": response["state"],
        "truth_state": entry["truth"]["state"],
        "row": wire(row),
    }


def run_quickstart() -> dict[str, Any]:
    truth_document = load_public_truth()
    return {
        "mode": "institution/0.2 local quickstart",
        "scope": SCOPE,
        "class_id": BINDING.class_id,
        "profile_id": BINDING.profile.profile_id,
        "miner_method": METHOD_ID,
        "cases": [run_case(family, truth_document) for family in FAMILIES],
    }


def render(result: dict[str, Any]) -> str:
    lines = [
        f"SN87 quickstart: {result['class_id']} (institution/0.2), profile {result['profile_id']}",
        f"scope: {result['scope']}",
        f"miner method: {result['miner_method']}",
        "",
    ]
    for case in result["cases"]:
        row = case["row"]
        lines += [
            f"case {case['family']}",
            f"  capsule {case['capsule_commitment']} ({case['request_bytes']} bytes sent, "
            f"{case['response_bytes']} bytes returned)",
            f"  miner state {case['miner_state']}; published truth {case['truth_state']}",
            f"  row: score={row['score']} valid={row['valid']} "
            f"precision={row['precision']} recall={row['recall']}",
            f"  dimensions: {json.dumps(row['dimensions'], sort_keys=True)}",
        ]
    lines += [
        "",
        "an abstain on an incomplete capsule earns the profile's epsilon floor, not a full score.",
        "integrity predicates are asserted locally; see the README for what this omits.",
    ]
    return "\n".join(lines)
