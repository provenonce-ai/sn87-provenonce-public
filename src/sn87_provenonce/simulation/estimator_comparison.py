"""Exact comparison of non-normative component estimators."""

from __future__ import annotations

import unicodedata
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
from sn87_provenonce.simulation.lane_one_profile import ExactRatio

ESTIMATOR_VERSION = "sn87/transparent-estimator/0alpha1"
COMPARISON_VERSION = "sn87/transparent-estimator-comparison/0alpha1"
ESTIMATOR_STATE = "EXPERIMENTAL_NON_NORMATIVE"
ESTIMATOR_COMMITMENT_DOMAIN = "SN87:TRANSPARENT_ESTIMATOR:v0alpha1"
COMPARISON_COMMITMENT_DOMAIN = "SN87:TRANSPARENT_ESTIMATOR_COMPARISON:v0alpha1"
Commitment = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ComponentName = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]


class EstimatorKind(StrEnum):
    WEIGHTED_ARITHMETIC_MEAN = "WEIGHTED_ARITHMETIC_MEAN"
    WEIGHTED_HARMONIC_MEAN = "WEIGHTED_HARMONIC_MEAN"


class StrictEstimatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UnitRatio(StrictEstimatorModel):
    numerator: StrictInt = Field(ge=0)
    denominator: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def reduce_and_bound(self) -> Self:
        value = Fraction(self.numerator, self.denominator)
        if value > 1:
            raise ValueError("unit ratio must be in [0, 1]")
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)
        return self

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class ComponentValue(StrictEstimatorModel):
    component: ComponentName
    value: UnitRatio

    @field_validator("value", mode="before")
    @classmethod
    def snapshot_value(cls, value: Any) -> Any:
        return value.model_dump(mode="json") if isinstance(value, UnitRatio) else value

    @field_validator("component")
    @classmethod
    def reject_component_whitespace(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        if normalized != normalized.strip():
            raise ValueError("component cannot have surrounding whitespace")
        return normalized


class EstimatorSpec(StrictEstimatorModel):
    estimator_version: Literal["sn87/transparent-estimator/0alpha1"]
    estimator_state: Literal["EXPERIMENTAL_NON_NORMATIVE"]
    estimator_id: StrictStr = Field(min_length=1, max_length=128)
    task_profile_commitment: Commitment
    kind: EstimatorKind
    component_weights: dict[ComponentName, ExactRatio] = Field(min_length=1)
    output_semantics: Literal["EXPERIMENTAL_COMPONENT_AGGREGATE"]
    normative_scoring: Literal[False]
    winner_selection_defined: Literal[False]
    ranking_defined: Literal[False]
    weight_policy_defined: Literal[False]
    chain_action_defined: Literal[False]

    @field_validator("component_weights", mode="before")
    @classmethod
    def snapshot_component_weights(cls, value: Any) -> Any:
        if type(value) is not dict:
            raise ValueError("component_weights must be provided as a dictionary")
        return {
            name: weight.model_dump(mode="json") if isinstance(weight, ExactRatio) else weight
            for name, weight in value.items()
        }

    @field_validator(
        "normative_scoring",
        "winner_selection_defined",
        "ranking_defined",
        "weight_policy_defined",
        "chain_action_defined",
        mode="before",
    )
    @classmethod
    def require_boolean_false(cls, value: Any) -> bool:
        if value is not False:
            raise ValueError("reserved boundary must be the boolean false")
        return False

    @field_validator("estimator_id")
    @classmethod
    def reject_estimator_whitespace(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        if normalized != normalized.strip():
            raise ValueError("estimator_id cannot have surrounding whitespace")
        return normalized

    @field_validator("component_weights")
    @classmethod
    def validate_component_names(cls, value: dict[str, ExactRatio]) -> dict[str, ExactRatio]:
        normalized: dict[str, ExactRatio] = {}
        for name, weight in value.items():
            clean_name = unicodedata.normalize("NFC", name)
            if not clean_name.strip() or clean_name != clean_name.strip():
                raise ValueError("component weight names must be non-empty and trimmed")
            if clean_name in normalized:
                raise ValueError("component weight names must be unique after NFC normalization")
            normalized[clean_name] = weight
        return dict(sorted(normalized.items()))

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def commitment(self) -> str:
        return canonical_sha256(self.to_payload(), domain=ESTIMATOR_COMMITMENT_DOMAIN)


def create_estimator_spec(
    *,
    estimator_id: str,
    task_profile_commitment: str,
    kind: EstimatorKind,
    component_weights: dict[str, ExactRatio],
) -> EstimatorSpec:
    return EstimatorSpec(
        estimator_version=ESTIMATOR_VERSION,
        estimator_state=ESTIMATOR_STATE,
        estimator_id=estimator_id,
        task_profile_commitment=task_profile_commitment,
        kind=kind,
        component_weights=component_weights,
        output_semantics="EXPERIMENTAL_COMPONENT_AGGREGATE",
        normative_scoring=False,
        winner_selection_defined=False,
        ranking_defined=False,
        weight_policy_defined=False,
        chain_action_defined=False,
    )


def parse_estimator_spec(value: str | bytes) -> EstimatorSpec:
    return EstimatorSpec.model_validate(parse_json_strict(value))


def _ratio_payload(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def estimate_components(
    *, spec: EstimatorSpec, components: tuple[ComponentValue, ...]
) -> dict[str, Any]:
    if not isinstance(spec, EstimatorSpec):
        raise TypeError("spec must be an EstimatorSpec")
    if any(not isinstance(item, ComponentValue) for item in components):
        raise TypeError("components must contain ComponentValue objects")
    spec = EstimatorSpec.model_validate(spec.model_dump(mode="json"))
    components = tuple(
        ComponentValue.model_validate(item.model_dump(mode="json")) for item in components
    )
    names = [item.component for item in components]
    if len(names) != len(set(names)):
        raise ValueError("component names must be unique")
    values = {item.component: item.value.fraction for item in components}
    if set(values) != set(spec.component_weights):
        raise ValueError("component values must exactly match estimator weight names")

    weights = {name: weight.fraction for name, weight in spec.component_weights.items()}
    total_weight = sum(weights.values(), Fraction(0, 1))
    if spec.kind is EstimatorKind.WEIGHTED_ARITHMETIC_MEAN:
        estimate = (
            sum((weights[name] * values[name] for name in weights), Fraction(0, 1)) / total_weight
        )
    elif spec.kind is EstimatorKind.WEIGHTED_HARMONIC_MEAN:
        estimate = (
            Fraction(0, 1)
            if any(values[name] == 0 for name in weights)
            else total_weight
            / sum((weights[name] / values[name] for name in weights), Fraction(0, 1))
        )
    else:  # pragma: no cover - closed enum protects this branch
        raise AssertionError(f"unsupported estimator kind: {spec.kind}")

    body = {
        "estimator_spec": spec.to_payload(),
        "estimator_commitment": spec.commitment,
        "component_vector": [
            {"component": name, "value": _ratio_payload(values[name])} for name in sorted(values)
        ],
        "estimate": _ratio_payload(estimate),
        "invariants": {
            "bounded_unit_interval": 0 <= estimate <= 1,
            "exact_arithmetic": True,
            "component_order_independent": True,
        },
        "normative_scoring": False,
        "winner_selected": False,
        "ranking_defined": False,
        "weight_policy_defined": False,
        "chain_action_defined": False,
    }
    return body | {
        "result_commitment": canonical_sha256(
            body, domain="SN87:TRANSPARENT_ESTIMATOR_RESULT:v0alpha1"
        )
    }


def compare_estimators(
    *, specs: tuple[EstimatorSpec, ...], components: tuple[ComponentValue, ...]
) -> dict[str, Any]:
    if len(specs) < 2:
        raise ValueError("comparison requires at least two estimator specs")
    if any(not isinstance(spec, EstimatorSpec) for spec in specs):
        raise TypeError("specs must contain EstimatorSpec objects")
    specs = tuple(EstimatorSpec.model_validate(spec.model_dump(mode="json")) for spec in specs)
    estimator_ids = [spec.estimator_id for spec in specs]
    if len(estimator_ids) != len(set(estimator_ids)):
        raise ValueError("estimator IDs must be unique")
    profile_commitments = {spec.task_profile_commitment for spec in specs}
    if len(profile_commitments) != 1:
        raise ValueError("all estimators must bind the same task profile")

    results = [
        estimate_components(spec=spec, components=components)
        for spec in sorted(specs, key=lambda item: item.estimator_id)
    ]
    body = {
        "comparison_version": COMPARISON_VERSION,
        "comparison_state": ESTIMATOR_STATE,
        "task_profile_commitment": next(iter(profile_commitments)),
        "results": results,
        "winner_selected": False,
        "ranking_defined": False,
        "production_policy_selected": False,
    }
    return body | {
        "comparison_commitment": canonical_sha256(body, domain=COMPARISON_COMMITMENT_DOMAIN)
    }
