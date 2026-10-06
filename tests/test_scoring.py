"""The one scorer, exercised through both bound classes."""

from copy import deepcopy
from dataclasses import replace

import _requires_executors  # noqa: F401
import pytest

from sn87_provenonce.classes import TYPE_C_RELEASE as TC
from sn87_provenonce.pilot.contracts import (
    capsule_from_fixture,
    validate_capsule,
    validate_differential,
)
from sn87_provenonce.pilot.reference import agreed_truth, make_differential
from sn87_provenonce.scoring import (
    EFFICIENCY_STATUS,
    Integrity,
    calibration,
    epoch_estimate,
    geometric,
    preference_row,
    score_response,
    wire,
)
from sn87_provenonce.simulation.type_c import FIXTURES

OK = Integrity(True, True, True, True, True, True)
P = TC.profile


def score(c, truth, d, integrity=OK):
    return score_response(TC, c, truth, d, integrity)


@pytest.mark.parametrize("index", range(len(FIXTURES)))
def test_type_c_references_and_capsule_contract(index):
    c = capsule_from_fixture(FIXTURES[index])
    validate_capsule(c)
    truth = agreed_truth(c)
    left, right = make_differential(c, "state_machine"), make_differential(c, "relational")
    assert left | {"method": "same"} == right | {"method": "same"}
    result = score(c, truth, left)
    assert result["valid"]
    assert result["score"] == pytest.approx(1e-6 if index == 4 else 1)


def test_required_rationale_and_unknown_reference():
    c = capsule_from_fixture(FIXTURES[1])
    d = make_differential(c, "state_machine")
    for altered in [d | {"rationale": ""}, d | {"state": "NO_MATERIAL_DEVIATION"}]:
        with pytest.raises(ValueError):
            validate_differential(c, altered)
    d["findings"][0]["evidence_refs"] = ["foreign-event"]
    assert score(c, agreed_truth(c), d)["score"] == 0


def test_duplicate_is_false_positive():
    c = capsule_from_fixture(FIXTURES[1])
    d = make_differential(c, "state_machine")
    d["findings"].append(deepcopy(d["findings"][0]))
    d["findings"][-1]["severity"] = "LOW"  # understating severity cannot reduce the cost
    result = score(c, agreed_truth(c), d)
    assert (result["fp_cost"], result["precision"], result["recall"]) == (1, 0.5, 1)
    assert result["dimensions"]["detection"] == pytest.approx(2 / 3)
    assert result["dimensions"]["calibration"] == 0.5


def test_missing_scope_evidence_is_zero_quality_not_integrity_failure():
    c = capsule_from_fixture(FIXTURES[1])
    d = make_differential(c, "state_machine")
    d["findings"][0]["evidence_refs"].remove("$completeness")
    result = score(c, agreed_truth(c), d)
    assert result["valid"] and result["dimensions"]["evidence"] == 0 and result["score"] < 0.1


def test_abstention_and_na_calibration():
    for index in (0, 1):
        c = capsule_from_fixture(FIXTURES[index])
        truth = agreed_truth(c)
        d = make_differential(c, "state_machine")
        d.update(state="INSUFFICIENT_EVIDENCE_ABSTAIN", findings=[], rationale="Incomplete basis")
        result = score(c, truth, d)
        assert result["dimensions"]["detection"] == 0
        assert result["dimensions"]["calibration"] == "NA"
        assert result["score"] == pytest.approx(1e-6)
    d.update(state="NO_MATERIAL_DEVIATION")
    result = score(c, truth, d)
    assert result["recall"] == 0 and result["score"] == pytest.approx(1e-6)


def test_inactive_dimensions_are_na():
    c = capsule_from_fixture(FIXTURES[0])
    result = score(c, agreed_truth(c), make_differential(c, "state_machine"))
    assert result["dimensions"]["utility"] == result["dimensions"]["robustness"] == "NA"
    assert result["rule_score"] == "NA"
    # Eq.11 keeps its neutral factor numerically; its status says it is inactive.
    assert result["eta"] == 1.0 and result["efficiency"] == EFFICIENCY_STATUS
    assert result["cost_coefficients"] == ["0", "0", "0", "0"]
    assert 0 not in wire(result)["dimensions"].values()


@pytest.mark.parametrize("failed", ["schema", "policy", "signature", "nonce", "evidence",
                                    "deadline"])
def test_every_integrity_failure_is_zero(failed):
    c = capsule_from_fixture(FIXTURES[0])
    fields = {k: k != failed for k in ("schema", "policy", "signature", "nonce", "evidence",
                                       "deadline")}
    result = score(c, agreed_truth(c), make_differential(c, "state_machine"), Integrity(**fields))
    assert result["score"] == 0 and not result["valid"] and failed in result["failures"]


def test_confidence_required_and_recursive_response_invalid():
    c = capsule_from_fixture(FIXTURES[1])
    d = make_differential(c, "state_machine")
    del d["findings"][0]["confidence"]
    assert score(c, agreed_truth(c), d)["failures"] == ["schema"]
    d = make_differential(c, "state_machine")
    nested = value = {}
    for _ in range(1100):
        value["nested"] = value = {}
    d["unexpected"] = nested
    assert not score(c, agreed_truth(c), d)["valid"]


def test_composite_is_na_when_empty():
    assert calibration([]) is None and calibration([(1, 0), (0, 1)]) == 0
    assert geometric({}, {}, 1e-6) is None
    assert geometric({"detection": 1, "evidence": None}, {"detection": 0.6, "evidence": 0.25},
                     1e-6) == 1
    with pytest.raises(ValueError):
        geometric({"detection": float("nan")}, {"detection": 1}, 1e-6)


def test_epoch_floor_ceiling_and_quantile():
    assert epoch_estimate([], [], P)["estimate"] is None
    assert epoch_estimate([1] * 39, [True] * 39, P)["reason"] == "SAMPLE_FLOOR"
    result = epoch_estimate([1] * 40, [False] * 4 + [True] * 36, P)
    assert (result["estimate"], result["raw_invalid_or_missing_rate"]) == (0.9, 0.1)
    assert epoch_estimate([1] * 40, [False] * 5 + [True] * 35, P)["reason"] == "RAW_FAILURE_CEILING"
    trimmed = replace(P, tail=0.25, minimum=4)
    result = epoch_estimate([0, 0.2, 0.8, 1], [True] * 4, trimmed)
    assert (result["lower"], result["upper"], result["estimate"]) == (0, 0.8, 0.45)


def test_preference_row_is_wire_strings_or_explicit_absence():
    row = preference_row({"a": None, "b": 0.60}, P)
    assert row["state"] == "NO_VALID_PREFERENCE_ROW" and row["weights"] is None
    assert preference_row({"a": 1, "b": 0.8}, P)["weights"] == {"a": "0.79999999999999993",
                                                                "b": "0.20000000000000007"}
    assert wire(0.1 + 0.2) == "0.30000000000000004"  # binary64 round-trip, not decimal math
    with pytest.raises(ValueError):
        wire(float("inf"))
