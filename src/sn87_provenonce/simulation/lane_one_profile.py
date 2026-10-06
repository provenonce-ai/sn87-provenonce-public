"""Versioned, non-normative configuration for Lane One component measurement."""

from __future__ import annotations

from enum import StrEnum
from fractions import Fraction
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from sn87_provenonce.protocol.v0alpha1 import canonical_sha256, parse_json_strict

PROFILE_VERSION = "sn87/lane-one-task-profile/0alpha1"
PROFILE_COMMITMENT_DOMAIN = "SN87:LANE_ONE_TASK_PROFILE:v0alpha1"
PROFILE_STATE = "EXPERIMENTAL_NON_NORMATIVE"
Commitment = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class MeasurementComponent(StrEnum):
    SEVERITY_WEIGHTED_PRECISION = "SEVERITY_WEIGHTED_PRECISION"
    SEVERITY_WEIGHTED_RECALL = "SEVERITY_WEIGHTED_RECALL"
    F_BETA_DETECTION = "F_BETA_DETECTION"
    EVIDENCE_QUALITY = "EVIDENCE_QUALITY"
    BRIER_CALIBRATION = "BRIER_CALIBRATION"
    CLEAN_CONTROL_OUTCOME = "CLEAN_CONTROL_OUTCOME"


class MatchingPolicy(StrEnum):
    EXACT_REFERENCE_ONE_TO_ONE = "EXACT_REFERENCE_ONE_TO_ONE"


class StrictProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactRatio(StrictProfileModel):
    numerator: StrictInt = Field(gt=0)
    denominator: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def reduce_ratio(self) -> Self:
        value = Fraction(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)
        return self

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class PolicyBinding(StrictProfileModel):
    identifier: StrictStr = Field(min_length=1)
    commitment: Commitment

    @field_validator("identifier")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("policy identifier cannot have surrounding whitespace")
        return value


class LaneOneTaskProfile(StrictProfileModel):
    """Bind one transparent measurement run to explicit component policies."""

    profile_version: Literal["sn87/lane-one-task-profile/0alpha1"]
    profile_state: Literal["EXPERIMENTAL_NON_NORMATIVE"]
    profile_id: StrictStr = Field(min_length=1)
    challenge_class: StrictStr = Field(min_length=1)
    challenge_class_version: StrictStr = Field(min_length=1)
    enabled_components: tuple[MeasurementComponent, ...] = Field(min_length=1)
    matching_policy: MatchingPolicy
    policy_binding_mode: Literal["IDENTITY_ONLY"]
    severity_policy_binding: PolicyBinding
    false_positive_policy_binding: PolicyBinding
    minimum_fp_cost_units: StrictInt = Field(gt=0)
    beta_squared: ExactRatio | None
    calibration_policy_binding: PolicyBinding | None
    normative_scoring: Literal[False]
    composite_defined: Literal[False]
    epoch_estimator_defined: Literal[False]
    eligibility_threshold_defined: Literal[False]
    ranking_defined: Literal[False]
    weight_policy_defined: Literal[False]
    chain_action_defined: Literal[False]

    @field_validator("profile_id", "challenge_class", "challenge_class_version")
    @classmethod
    def reject_identifier_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("identifier fields cannot have surrounding whitespace")
        return value

    @field_validator("enabled_components")
    @classmethod
    def canonicalize_components(
        cls, value: tuple[MeasurementComponent, ...]
    ) -> tuple[MeasurementComponent, ...]:
        if len(value) != len(set(value)):
            raise ValueError("enabled_components must be unique")
        return tuple(sorted(value, key=lambda component: component.value))

    @model_validator(mode="after")
    def require_complete_component_configuration(self) -> Self:
        enabled = set(self.enabled_components)
        detection_dependencies = {
            MeasurementComponent.SEVERITY_WEIGHTED_PRECISION,
            MeasurementComponent.SEVERITY_WEIGHTED_RECALL,
        }
        if MeasurementComponent.F_BETA_DETECTION in enabled:
            if self.beta_squared is None:
                raise ValueError("F_BETA_DETECTION requires beta_squared")
            if not detection_dependencies.issubset(enabled):
                raise ValueError("F_BETA_DETECTION requires precision and recall components")
        elif self.beta_squared is not None:
            raise ValueError("beta_squared is allowed only when F_BETA_DETECTION is enabled")
        if MeasurementComponent.BRIER_CALIBRATION in enabled:
            if self.calibration_policy_binding is None:
                raise ValueError("BRIER_CALIBRATION requires a calibration_policy_binding")
        elif self.calibration_policy_binding is not None:
            raise ValueError(
                "calibration_policy_binding is allowed only when BRIER_CALIBRATION is enabled"
            )
        return self

    def enables(self, component: MeasurementComponent) -> bool:
        return component in self.enabled_components

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def commitment(self) -> str:
        return canonical_sha256(self.to_payload(), domain=PROFILE_COMMITMENT_DOMAIN)


def create_lane_one_task_profile(
    *,
    profile_id: str,
    challenge_class: str,
    challenge_class_version: str,
    enabled_components: tuple[MeasurementComponent, ...],
    severity_policy_binding: PolicyBinding,
    false_positive_policy_binding: PolicyBinding,
    minimum_fp_cost_units: int = 1,
    beta_squared: ExactRatio | None = None,
    calibration_policy_binding: PolicyBinding | None = None,
) -> LaneOneTaskProfile:
    """Create an explicit non-normative profile with every reserved boundary closed."""

    return LaneOneTaskProfile(
        profile_version=PROFILE_VERSION,
        profile_state=PROFILE_STATE,
        profile_id=profile_id,
        challenge_class=challenge_class,
        challenge_class_version=challenge_class_version,
        enabled_components=enabled_components,
        matching_policy=MatchingPolicy.EXACT_REFERENCE_ONE_TO_ONE,
        policy_binding_mode="IDENTITY_ONLY",
        severity_policy_binding=severity_policy_binding,
        false_positive_policy_binding=false_positive_policy_binding,
        minimum_fp_cost_units=minimum_fp_cost_units,
        beta_squared=beta_squared,
        calibration_policy_binding=calibration_policy_binding,
        normative_scoring=False,
        composite_defined=False,
        epoch_estimator_defined=False,
        eligibility_threshold_defined=False,
        ranking_defined=False,
        weight_policy_defined=False,
        chain_action_defined=False,
    )


def parse_lane_one_task_profile(value: str | bytes) -> LaneOneTaskProfile:
    """Parse a complete profile artifact with duplicate-key and extra-field rejection."""

    return LaneOneTaskProfile.model_validate(parse_json_strict(value))
