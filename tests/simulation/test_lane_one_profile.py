import json

import pytest

from sn87_provenonce.protocol.v0alpha1 import canonical_sha256
from sn87_provenonce.simulation.lane_one_profile import (
    PROFILE_VERSION,
    ExactRatio,
    MeasurementComponent,
    PolicyBinding,
    create_lane_one_task_profile,
    parse_lane_one_task_profile,
)


def binding(identifier: str) -> PolicyBinding:
    return PolicyBinding(
        identifier=identifier,
        commitment=canonical_sha256(identifier, domain="SN87:TEST_POLICY:v0alpha1"),
    )


def test_profile_is_canonical_and_self_committed() -> None:
    fields = {
        "profile_id": "lane-one-component-suite",
        "challenge_class": "LANE_ONE",
        "challenge_class_version": "0alpha1",
        "severity_policy_binding": binding("severity/0alpha1"),
        "false_positive_policy_binding": binding("false-positive/0alpha1"),
    }
    first = create_lane_one_task_profile(
        **fields,
        enabled_components=(
            MeasurementComponent.SEVERITY_WEIGHTED_RECALL,
            MeasurementComponent.SEVERITY_WEIGHTED_PRECISION,
            MeasurementComponent.F_BETA_DETECTION,
        ),
        beta_squared=ExactRatio(numerator=2, denominator=2),
    )
    second = create_lane_one_task_profile(
        **fields,
        enabled_components=(
            MeasurementComponent.F_BETA_DETECTION,
            MeasurementComponent.SEVERITY_WEIGHTED_PRECISION,
            MeasurementComponent.SEVERITY_WEIGHTED_RECALL,
        ),
        beta_squared=ExactRatio(numerator=1, denominator=1),
    )
    assert first.profile_version == PROFILE_VERSION
    assert first.to_payload() == second.to_payload()
    assert first.commitment == second.commitment
    assert first.to_payload()["profile_state"] == "EXPERIMENTAL_NON_NORMATIVE"
    assert first.to_payload()["composite_defined"] is False
    parsed = parse_lane_one_task_profile(json.dumps(first.to_payload()))
    assert parsed.to_payload() == first.to_payload()
    assert parsed.commitment == first.commitment


def test_profile_rejects_partial_detection_configuration() -> None:
    with pytest.raises(ValueError, match="requires precision and recall"):
        create_lane_one_task_profile(
            profile_id="invalid",
            challenge_class="LANE_ONE",
            challenge_class_version="0alpha1",
            enabled_components=(
                MeasurementComponent.F_BETA_DETECTION,
                MeasurementComponent.SEVERITY_WEIGHTED_RECALL,
            ),
            severity_policy_binding=binding("severity/0alpha1"),
            false_positive_policy_binding=binding("false-positive/0alpha1"),
            beta_squared=ExactRatio(numerator=1, denominator=1),
        )


def test_profile_rejects_unbound_calibration() -> None:
    with pytest.raises(ValueError, match="requires a calibration_policy_binding"):
        create_lane_one_task_profile(
            profile_id="invalid",
            challenge_class="LANE_ONE",
            challenge_class_version="0alpha1",
            enabled_components=(MeasurementComponent.BRIER_CALIBRATION,),
            severity_policy_binding=binding("severity/0alpha1"),
            false_positive_policy_binding=binding("false-positive/0alpha1"),
        )


def test_profile_rejects_duplicate_components_and_unknown_versions() -> None:
    base = {
        "profile_id": "invalid",
        "challenge_class": "LANE_ONE",
        "challenge_class_version": "0alpha1",
        "severity_policy_binding": binding("severity/0alpha1"),
        "false_positive_policy_binding": binding("false-positive/0alpha1"),
    }
    with pytest.raises(ValueError, match="must be unique"):
        create_lane_one_task_profile(
            **base,
            enabled_components=(
                MeasurementComponent.EVIDENCE_QUALITY,
                MeasurementComponent.EVIDENCE_QUALITY,
            ),
        )
    with pytest.raises(ValueError, match="profile_version"):
        parse_lane_one_task_profile(
            json.dumps(
                create_lane_one_task_profile(
                    **base,
                    enabled_components=(MeasurementComponent.EVIDENCE_QUALITY,),
                ).to_payload()
                | {"profile_version": "sn87/lane-one-task-profile/9"}
            )
        )


def test_artifact_parser_rejects_ambiguity_and_scope_expansion() -> None:
    valid = create_lane_one_task_profile(
        profile_id="evidence-only",
        challenge_class="LANE_ONE",
        challenge_class_version="0alpha1",
        enabled_components=(MeasurementComponent.EVIDENCE_QUALITY,),
        severity_policy_binding=binding("severity/0alpha1"),
        false_positive_policy_binding=binding("false-positive/0alpha1"),
    ).to_payload()
    expanded = valid | {"composite_defined": True}
    with pytest.raises(ValueError, match="Input should be False"):
        parse_lane_one_task_profile(json.dumps(expanded))
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        parse_lane_one_task_profile(json.dumps(valid | {"notes": "not part of the contract"}))
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_lane_one_task_profile('{"profile_version":"a","profile_version":"b"}')


def test_artifact_parser_requires_complete_strict_payload() -> None:
    valid = create_lane_one_task_profile(
        profile_id="evidence-only",
        challenge_class="LANE_ONE",
        challenge_class_version="0alpha1",
        enabled_components=(MeasurementComponent.EVIDENCE_QUALITY,),
        severity_policy_binding=binding("severity/0alpha1"),
        false_positive_policy_binding=binding("false-positive/0alpha1"),
    ).to_payload()
    missing_boundary = dict(valid)
    del missing_boundary["chain_action_defined"]
    with pytest.raises(ValueError, match="chain_action_defined"):
        parse_lane_one_task_profile(json.dumps(missing_boundary))
    with pytest.raises(ValueError, match="minimum_fp_cost_units"):
        parse_lane_one_task_profile(
            json.dumps(valid | {"minimum_fp_cost_units": True})
        )
