
import pytest

from sn87_provenonce.protocol.v0alpha1 import ResponseState, canonical_sha256
from sn87_provenonce.simulation.lane_one_measurement import (
    FalsePositiveAssessment,
    FindingClaim,
    PlantedDefect,
    measure_lane_one_case,
)
from sn87_provenonce.simulation.lane_one_profile import (
    ExactRatio,
    LaneOneTaskProfile,
    MeasurementComponent,
    PolicyBinding,
    create_lane_one_task_profile,
)


def policy(identifier: str) -> PolicyBinding:
    return PolicyBinding(
        identifier=identifier,
        commitment=canonical_sha256(
            {"identifier": identifier}, domain="SN87:TEST_POLICY:v0alpha1"
        ),
    )


def profile(
    *,
    enabled_components: tuple[MeasurementComponent, ...] | None = None,
    minimum_fp_cost_units: int = 1,
) -> LaneOneTaskProfile:
    return create_lane_one_task_profile(
        profile_id="lane-one-transparent-test",
        challenge_class="LANE_ONE",
        challenge_class_version="0alpha1",
        enabled_components=enabled_components
        or (
            MeasurementComponent.SEVERITY_WEIGHTED_PRECISION,
            MeasurementComponent.SEVERITY_WEIGHTED_RECALL,
            MeasurementComponent.F_BETA_DETECTION,
            MeasurementComponent.EVIDENCE_QUALITY,
            MeasurementComponent.BRIER_CALIBRATION,
            MeasurementComponent.CLEAN_CONTROL_OUTCOME,
        ),
        severity_policy_binding=policy("test-severity/0alpha1"),
        false_positive_policy_binding=policy("test-false-positive/0alpha1"),
        beta_squared=ExactRatio(numerator=1, denominator=1),
        calibration_policy_binding=policy("test-calibration/0alpha1"),
        minimum_fp_cost_units=minimum_fp_cost_units,
    )


def claim(
    claim_id: str,
    defect_ref: str | None,
    *,
    claimed: int = 1,
    evidence: bool = True,
    confidence: int = 9000,
) -> FindingClaim:
    return FindingClaim(claim_id, defect_ref, claimed, evidence, confidence)


def test_duplicate_reference_matches_once_and_becomes_false_positive() -> None:
    result = measure_lane_one_case(
        profile=profile(),
        response_state=ResponseState.FINDINGS,
        planted_defects=(PlantedDefect("d1", 100),),
        claims=(claim("a", "d1"), claim("b", "d1", claimed=5)),
        sealed_fp_assessments=(FalsePositiveAssessment("b", 7),),
    )
    assert result["matched"] == [{"claim_id": "a", "defect_id": "d1"}]
    assert result["unmatched"] == [
        {"claim_id": "b", "reason": "DUPLICATE_REFERENCE", "applied_cost_units": 7}
    ]
    assert result["true_positive_weight_units"] == 100
    assert result["false_positive_cost_units"] == 7


def test_unknown_non_null_reference_is_a_false_positive() -> None:
    result = measure_lane_one_case(
        profile=profile(),
        response_state=ResponseState.FINDINGS,
        planted_defects=(PlantedDefect("d1", 100),),
        claims=(claim("a", "not-a-defect", claimed=2),),
        sealed_fp_assessments=(FalsePositiveAssessment("a", 9),),
    )
    assert result["unmatched"] == [
        {"claim_id": "a", "reason": "UNKNOWN_REFERENCE", "applied_cost_units": 9}
    ]
    assert result["components"]["precision"] == {"numerator": 0, "denominator": 1}
    assert result["components"]["recall"] == {"numerator": 0, "denominator": 1}


def test_false_positive_cost_cannot_be_reduced_by_understating_severity() -> None:
    result = measure_lane_one_case(
        profile=profile(minimum_fp_cost_units=10),
        response_state=ResponseState.FINDINGS,
        planted_defects=(),
        claims=(claim("a", None, claimed=1),),
        sealed_fp_assessments=(FalsePositiveAssessment("a", 50),),
    )
    assert result["false_positive_cost_units"] == 50
    assert result["components"]["clean_control_pass"] is False


def test_clean_and_abstain_are_distinct() -> None:
    clean = measure_lane_one_case(
        profile=profile(),
        response_state=ResponseState.NO_MATERIAL_DEVIATION,
        planted_defects=(),
        claims=(),
    )
    abstain = measure_lane_one_case(
        profile=profile(),
        response_state=ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN,
        planted_defects=(),
        claims=(),
    )
    assert clean["components"]["clean_control_pass"] is True
    assert clean["components"]["detection_quality"] is None
    assert abstain["components"]["clean_control_pass"] is None
    assert abstain["components"]["detection_quality"] == {
        "numerator": 0,
        "denominator": 1,
    }


def test_component_measurement_is_exact_and_emits_no_composite() -> None:
    arguments = {
        "profile": profile(),
        "response_state": ResponseState.FINDINGS,
        "planted_defects": (PlantedDefect("d1", 100), PlantedDefect("d2", 50)),
        "claims": (
            claim("a", "d1", evidence=True, confidence=7500),
            claim("b", None, claimed=25, evidence=False, confidence=2500),
        ),
    }
    first = measure_lane_one_case(**arguments)
    second = measure_lane_one_case(**arguments)
    assert first == second
    assert first["components"]["precision"] == {"numerator": 4, "denominator": 5}
    assert first["components"]["recall"] == {"numerator": 2, "denominator": 3}
    assert first["components"]["detection_quality"] == {
        "numerator": 8,
        "denominator": 11,
    }
    assert first["components"]["evidence_quality"] == {"numerator": 1, "denominator": 1}
    assert first["components"]["calibration_quality"] == {
        "numerator": 15,
        "denominator": 16,
    }
    assert first["task_profile_commitment"] == arguments["profile"].commitment
    assert first["boundaries"]["composite_defined"] is False
    assert first["boundaries"]["weight_planning"] is False


def test_finding_state_and_identity_invariants_fail_closed() -> None:
    with pytest.raises(ValueError, match="requires at least one"):
        measure_lane_one_case(
            profile=profile(),
            response_state=ResponseState.FINDINGS,
            planted_defects=(),
            claims=(),
        )
    with pytest.raises(ValueError, match="claim IDs must be unique"):
        measure_lane_one_case(
            profile=profile(),
            response_state=ResponseState.FINDINGS,
            planted_defects=(),
            claims=(claim("a", None), claim("a", None)),
        )


def test_disabled_components_are_not_emitted() -> None:
    clean_only = create_lane_one_task_profile(
        profile_id="clean-only",
        challenge_class="LANE_ONE",
        challenge_class_version="0alpha1",
        enabled_components=(MeasurementComponent.CLEAN_CONTROL_OUTCOME,),
        severity_policy_binding=policy("test-severity/0alpha1"),
        false_positive_policy_binding=policy("test-false-positive/0alpha1"),
    )
    result = measure_lane_one_case(
        profile=clean_only,
        response_state=ResponseState.NO_MATERIAL_DEVIATION,
        planted_defects=(),
        claims=(),
    )
    assert result["components"] == {"clean_control_pass": True}
