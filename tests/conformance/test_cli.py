from __future__ import annotations

import json
from pathlib import Path

from sn87_provenonce.cli import DEFAULT_VECTORS, main, run_demo, run_local_validator_demo

REPOSITORY_VECTORS = Path(__file__).resolve().parents[2] / "protocol" / "v0alpha1" / "test-vectors"


def test_demo_returns_passing_synthetic_gate() -> None:
    payload = run_demo(DEFAULT_VECTORS)
    assert payload["mode"] == "synthetic_local_conformance"
    assert payload["integrity_gate"]["passed"] is True


def test_demo_command_prints_machine_readable_result(capsys) -> None:
    assert main(["demo"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["challenge_id"] == "q-lane-one-0001"
    assert payload["response_state"] == "FINDINGS"
    assert payload["integrity_gate"]["passed"] is True


def test_packaged_vectors_match_repository_vectors() -> None:
    names = {
        "request.metadata-clean.json",
        "response.abstain.json",
        "response.findings.json",
        "response.no-material-deviation.json",
    }
    for name in names:
        packaged = DEFAULT_VECTORS.joinpath(name).read_bytes()
        assert packaged == (REPOSITORY_VECTORS / name).read_bytes()


def test_lane_one_command_prints_bounded_simulation(capsys) -> None:
    assert main(["simulate-lane-one"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claim_state"] == "IMPLEMENTED_TESTED_SIMULATION_ONLY"
    assert payload["ranking"][0] == "evidence_first"
    assert payload["weight_intent"]["broadcast_capable"] is False


def test_local_validator_demo_is_bounded_and_exercises_rejection() -> None:
    payload = run_local_validator_demo(DEFAULT_VECTORS)
    assert payload["mode"] == "LOCAL_TRANSPORT_NEUTRAL_VALIDATOR"
    assert payload["claim_state"] == "IMPLEMENTED_TESTED_LOCAL_RUNTIME_ONLY"
    assert payload["report_commitment"].startswith("sha256:")
    assert payload["status_counts"] == {"INTEGRITY_FAILED": 1, "INTEGRITY_PASSED": 3}
    assert payload["scoring_performed"] is False
    assert payload["weight_plan_created"] is False
    assert payload["broadcast_capable"] is False


def test_local_validator_command_prints_machine_readable_result(capsys) -> None:
    assert main(["run-local-validator"]) == 0
    payload = json.loads(capsys.readouterr().out)
    rejected = [
        outcome for outcome in payload["outcomes"] if outcome["status"] == "INTEGRITY_FAILED"
    ]
    assert rejected[0]["integrity_gate"]["failures"] == ["SIGNATURE_INVALID"]
