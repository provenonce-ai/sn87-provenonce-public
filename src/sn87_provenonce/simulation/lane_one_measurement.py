"""Exact transparent Lane One measurement inputs without a normative composite."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from sn87_provenonce.protocol.v0alpha1 import ResponseState, canonical_sha256
from sn87_provenonce.simulation.lane_one_profile import (
    LaneOneTaskProfile,
    MeasurementComponent,
)

MEASUREMENT_VERSION = "lane-one-transparent-measurement/0alpha1"
CLAIM_STATE = "IMPLEMENTED_TESTED_TRANSPARENT_COMPONENT_MEASUREMENT_ONLY"


@dataclass(frozen=True)
class PlantedDefect:
    defect_id: str
    severity_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.defect_id, str) or not self.defect_id.strip():
            raise ValueError("defect_id must be non-empty")
        if (
            isinstance(self.severity_units, bool)
            or not isinstance(self.severity_units, int)
            or self.severity_units <= 0
        ):
            raise ValueError("severity_units must be a positive integer")


@dataclass(frozen=True)
class FindingClaim:
    claim_id: str
    defect_ref: str | None
    claimed_fp_cost_units: int
    evidence_valid: bool
    confidence_bps: int

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not self.claim_id.strip():
            raise ValueError("claim_id must be non-empty")
        if self.defect_ref is not None and (
            not isinstance(self.defect_ref, str) or not self.defect_ref.strip()
        ):
            raise ValueError("defect_ref must be non-empty when present")
        if (
            isinstance(self.claimed_fp_cost_units, bool)
            or not isinstance(self.claimed_fp_cost_units, int)
            or self.claimed_fp_cost_units < 0
        ):
            raise ValueError("claimed_fp_cost_units must be a nonnegative integer")
        if not isinstance(self.evidence_valid, bool):
            raise ValueError("evidence_valid must be a boolean")
        if (
            isinstance(self.confidence_bps, bool)
            or not isinstance(self.confidence_bps, int)
            or not 0 <= self.confidence_bps <= 10_000
        ):
            raise ValueError("confidence_bps must be an integer in [0, 10000]")


@dataclass(frozen=True)
class FalsePositiveAssessment:
    """Validator-hidden rule-based cost for a claim if it is unmatched."""

    claim_id: str
    cost_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not self.claim_id.strip():
            raise ValueError("assessment claim_id must be non-empty")
        if (
            isinstance(self.cost_units, bool)
            or not isinstance(self.cost_units, int)
            or self.cost_units < 0
        ):
            raise ValueError("assessment cost_units must be a nonnegative integer")


def _fraction(value: Fraction | None) -> dict[str, int] | None:
    if value is None:
        return None
    return {"numerator": value.numerator, "denominator": value.denominator}


def measure_lane_one_case(
    *,
    profile: LaneOneTaskProfile,
    response_state: ResponseState,
    planted_defects: tuple[PlantedDefect, ...],
    claims: tuple[FindingClaim, ...],
    sealed_fp_assessments: tuple[FalsePositiveAssessment, ...] = (),
) -> dict[str, Any]:
    """Measure disclosed components with exact rational arithmetic.

    Direct references are matched one-to-one in claim-id order. Every duplicate,
    missing, or unknown reference is an unmatched claim and therefore incurs false-
    positive cost. This function deliberately emits no composite, rank, or weight.
    """

    if not isinstance(profile, LaneOneTaskProfile):
        raise TypeError("profile must be a LaneOneTaskProfile")
    if not isinstance(response_state, ResponseState):
        raise TypeError("response_state must be a ResponseState")
    beta_squared = profile.beta_squared.fraction if profile.beta_squared else None
    defect_ids = [defect.defect_id for defect in planted_defects]
    if len(defect_ids) != len(set(defect_ids)):
        raise ValueError("planted defect IDs must be unique")
    claim_ids = [claim.claim_id for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claim IDs must be unique")
    if response_state is ResponseState.FINDINGS and not claims:
        raise ValueError("FINDINGS requires at least one claim")
    if response_state is not ResponseState.FINDINGS and claims:
        raise ValueError("claims are allowed only for FINDINGS")
    assessment_ids = [assessment.claim_id for assessment in sealed_fp_assessments]
    if len(assessment_ids) != len(set(assessment_ids)):
        raise ValueError("sealed false-positive assessment claim IDs must be unique")
    if not set(assessment_ids).issubset(claim_ids):
        raise ValueError("sealed false-positive assessments must reference supplied claims")
    sealed_costs = {
        assessment.claim_id: assessment.cost_units for assessment in sealed_fp_assessments
    }

    defects = {defect.defect_id: defect for defect in planted_defects}
    matched_defects: set[str] = set()
    matched: list[tuple[FindingClaim, PlantedDefect]] = []
    unmatched: list[dict[str, object]] = []
    false_positive_cost = 0

    for claim in sorted(claims, key=lambda item: item.claim_id):
        if claim.defect_ref is None:
            reason = "MISSING_REFERENCE"
        elif claim.defect_ref not in defects:
            reason = "UNKNOWN_REFERENCE"
        elif claim.defect_ref in matched_defects:
            reason = "DUPLICATE_REFERENCE"
        else:
            defect = defects[claim.defect_ref]
            matched_defects.add(defect.defect_id)
            matched.append((claim, defect))
            continue
        applied_cost = max(
            profile.minimum_fp_cost_units,
            claim.claimed_fp_cost_units,
            sealed_costs.get(claim.claim_id, 0),
        )
        false_positive_cost += applied_cost
        unmatched.append(
            {"claim_id": claim.claim_id, "reason": reason, "applied_cost_units": applied_cost}
        )

    total_truth_weight = sum(defect.severity_units for defect in planted_defects)
    true_positive_weight = sum(defect.severity_units for _claim, defect in matched)
    precision_denominator = true_positive_weight + false_positive_cost
    precision = (
        Fraction(true_positive_weight, precision_denominator)
        if precision_denominator
        else Fraction(1, 1)
    )
    recall = (
        Fraction(true_positive_weight, total_truth_weight) if total_truth_weight else None
    )
    detection = None
    clean_control_pass: bool | None = None
    if response_state is ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN:
        detection = Fraction(0, 1)
    elif total_truth_weight and beta_squared is not None:
        assert recall is not None
        denominator = beta_squared * precision + recall
        detection = (
            Fraction(0, 1)
            if denominator == 0
            else (Fraction(1, 1) + beta_squared) * precision * recall / denominator
        )
    else:
        clean_control_pass = response_state is ResponseState.NO_MATERIAL_DEVIATION

    evidence = (
        Fraction(
            sum(defect.severity_units for claim, defect in matched if claim.evidence_valid),
            true_positive_weight,
        )
        if true_positive_weight
        else None
    )
    calibration = None
    if claims:
        matched_claim_ids = {claim.claim_id for claim, _defect in matched}
        squared_errors = sum(
            (
                Fraction(claim.confidence_bps, 10_000)
                - Fraction(1 if claim.claim_id in matched_claim_ids else 0, 1)
            )
            ** 2
            for claim in claims
        )
        calibration = Fraction(1, 1) - squared_errors / len(claims)

    components: dict[str, Any] = {}
    if profile.enables(MeasurementComponent.SEVERITY_WEIGHTED_PRECISION):
        components["precision"] = _fraction(precision)
    if profile.enables(MeasurementComponent.SEVERITY_WEIGHTED_RECALL):
        components["recall"] = _fraction(recall)
    if profile.enables(MeasurementComponent.F_BETA_DETECTION):
        components["detection_quality"] = _fraction(detection)
    if profile.enables(MeasurementComponent.CLEAN_CONTROL_OUTCOME):
        components["clean_control_pass"] = clean_control_pass
    if profile.enables(MeasurementComponent.EVIDENCE_QUALITY):
        components["evidence_quality"] = _fraction(evidence)
    if profile.enables(MeasurementComponent.BRIER_CALIBRATION):
        components["calibration_quality"] = _fraction(calibration)

    body: dict[str, Any] = {
        "measurement_version": MEASUREMENT_VERSION,
        "claim_state": CLAIM_STATE,
        "task_profile": profile.to_payload(),
        "task_profile_commitment": profile.commitment,
        "response_state": response_state.value,
        "matched": [
            {"claim_id": claim.claim_id, "defect_id": defect.defect_id}
            for claim, defect in matched
        ],
        "unmatched": unmatched,
        "true_positive_weight_units": true_positive_weight,
        "false_positive_cost_units": false_positive_cost,
        "components": components,
        "boundaries": {
            "direct_reference_matching_only": True,
            "clean_control_penalty_defined": False,
            "composite_defined": False,
            "epoch_estimator_defined": False,
            "normative_scoring": False,
            "ranking": False,
            "weight_planning": False,
            "chain_submission": False,
        },
    }
    return body | {
        "measurement_commitment": canonical_sha256(
            body, domain="SN87:LANE_ONE_TRANSPARENT_MEASUREMENT:v0alpha1"
        )
    }
