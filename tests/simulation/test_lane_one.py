from __future__ import annotations

import json
import socket

from sn87_provenonce.simulation import (
    NO_VALID_WEIGHT_ROW,
    WEIGHT_SCALE,
    build_weight_intent,
    run_lane_one_simulation,
)


def test_report_is_byte_for_byte_deterministic() -> None:
    first = json.dumps(run_lane_one_simulation(), sort_keys=True, separators=(",", ":"))
    second = json.dumps(run_lane_one_simulation(), sort_keys=True, separators=(",", ":"))
    assert first == second


def test_simulation_covers_the_four_transparent_case_types() -> None:
    report = run_lane_one_simulation()
    assert {case["case_class"] for case in report["cases"]} == {
        "TYPE_A_PLANTED_DEFECT",
        "TYPE_A_CLEAN_CONTROL",
        "TYPE_A_EQUIVALENT_MUTATION",
        "TYPE_A_INSUFFICIENT_EVIDENCE",
    }
    assert report["ranking"][0] == "evidence_first"


def test_weight_intent_is_local_and_exactly_normalized() -> None:
    report = run_lane_one_simulation()
    intent = report["weight_intent"]
    assert intent["status"] == "SIMULATED_WEIGHT_INTENT"
    assert intent["broadcast_capable"] is False
    assert sum(intent["weights"].values()) == WEIGHT_SCALE


def test_no_valid_weight_row_never_fabricates_weights() -> None:
    direct = build_weight_intent({"a": 3000, "b": 2000})
    report = run_lane_one_simulation(force_no_valid_row=True)
    exercised = report["weight_intent"]
    assert direct["status"] == exercised["status"] == NO_VALID_WEIGHT_ROW
    assert direct["weights"] is exercised["weights"] is None
    assert report["weight_intent_input"] == {
        "source": "FORCED_BOUNDARY_VECTOR",
        "scores_bps": {
            "abstainer": 3000,
            "alarmist": 3000,
            "evidence_first": 3000,
            "noisy": 3000,
        },
    }


def test_simulation_performs_no_network_calls(monkeypatch) -> None:
    def deny_network(*args, **kwargs):
        raise AssertionError("simulation attempted network access")

    monkeypatch.setattr(socket, "socket", deny_network)
    report = run_lane_one_simulation()
    assert report["boundaries"]["external_network"] is False


def test_report_does_not_claim_benchmark_or_production_truth() -> None:
    report = run_lane_one_simulation()
    assert report["claim_state"] == "IMPLEMENTED_TESTED_SIMULATION_ONLY"
    assert report["parameters"]["status"] == "LOCAL_PROVISIONAL_NON_NORMATIVE"
    assert report["boundaries"] == {
        "benchmark_truth": False,
        "chain_submission": False,
        "external_network": False,
        "production_evidence": False,
        "scoring_constants_normative": False,
    }
