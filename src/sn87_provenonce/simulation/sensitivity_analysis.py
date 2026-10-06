"""Exact non-normative sensitivity and componentwise dominance analysis."""

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
from sn87_provenonce.simulation.estimator_comparison import (
    ComponentName,
    ComponentValue,
    EstimatorSpec,
    UnitRatio,
    estimate_components,
)

ANALYSIS_VERSION = "sn87/transparent-sensitivity-analysis/0alpha1"
ANALYSIS_STATE = "EXPERIMENTAL_NON_NORMATIVE"
ANALYSIS_COMMITMENT_DOMAIN = "SN87:TRANSPARENT_SENSITIVITY_ANALYSIS:v0alpha1"
RESULT_COMMITMENT_DOMAIN = "SN87:TRANSPARENT_SENSITIVITY_RESULT:v0alpha1"
MAX_ANALYSIS_JSON_BYTES = 1_000_000
MAX_RATIONAL_BITS = 4096
MAX_COMPONENTWISE_RELATIONS = 32_896
Commitment = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class ChangeDirection(StrEnum):
    DECREASED = "DECREASED"
    UNCHANGED = "UNCHANGED"
    INCREASED = "INCREASED"


class ComponentwiseRelation(StrEnum):
    LEFT_DOMINATES = "LEFT_COMPONENTWISE_DOMINATES"
    RIGHT_DOMINATES = "RIGHT_COMPONENTWISE_DOMINATES"
    EQUAL = "COMPONENTWISE_EQUAL"
    INCOMPARABLE = "COMPONENTWISE_INCOMPARABLE"


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class SignedRatio(StrictAnalysisModel):
    numerator: StrictInt
    denominator: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def reduce(self) -> Self:
        value = Fraction(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)
        return self


class ComponentVector(StrictAnalysisModel):
    vector_id: StrictStr = Field(min_length=1, max_length=128)
    components: tuple[ComponentValue, ...] = Field(min_length=1, max_length=64)

    @field_validator("components", mode="before")
    @classmethod
    def snapshot_components(cls, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise ValueError("components must be provided as a list or tuple")
        return [
            item.model_dump(mode="json") if isinstance(item, ComponentValue) else item
            for item in value
        ]

    @field_validator("vector_id")
    @classmethod
    def reject_vector_id_whitespace(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        if normalized != normalized.strip():
            raise ValueError("vector_id cannot have surrounding whitespace")
        return normalized

    @model_validator(mode="after")
    def canonicalize_components(self) -> Self:
        names = [component.component for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError("component names must be unique within a vector")
        object.__setattr__(
            self, "components", tuple(sorted(self.components, key=lambda item: item.component))
        )
        return self

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SensitivityAnalysisSpec(StrictAnalysisModel):
    analysis_version: Literal["sn87/transparent-sensitivity-analysis/0alpha1"]
    analysis_state: Literal["EXPERIMENTAL_NON_NORMATIVE"]
    task_profile_commitment: Commitment
    estimator_specs: tuple[EstimatorSpec, ...] = Field(min_length=1, max_length=16)
    baseline: ComponentVector
    scenarios: tuple[ComponentVector, ...] = Field(min_length=1, max_length=256)
    output_semantics: Literal["DESCRIPTIVE_ESTIMATOR_SENSITIVITY"]
    production_policy_selected: Literal[False]
    estimator_preference_defined: Literal[False]
    normative_scoring: Literal[False]
    winner_selection_defined: Literal[False]
    ranking_defined: Literal[False]
    weight_policy_defined: Literal[False]
    chain_action_defined: Literal[False]

    @model_validator(mode="before")
    @classmethod
    def reject_unbounded_integers(cls, value: Any) -> Any:
        def inspect(item: Any) -> None:
            if type(item) is int and abs(item).bit_length() > MAX_RATIONAL_BITS:
                raise ValueError(f"integer inputs cannot exceed {MAX_RATIONAL_BITS} bits")
            if isinstance(item, dict):
                for nested in item.values():
                    inspect(nested)
            elif isinstance(item, (list, tuple)):
                for nested in item:
                    inspect(nested)
            elif isinstance(item, BaseModel):
                inspect(item.model_dump(mode="json"))

        inspect(value)
        return value

    @field_validator("estimator_specs", mode="before")
    @classmethod
    def snapshot_estimators(cls, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise ValueError("estimator_specs must be provided as a list or tuple")
        return [
            item.model_dump(mode="json") if isinstance(item, EstimatorSpec) else item
            for item in value
        ]

    @field_validator("baseline", mode="before")
    @classmethod
    def snapshot_baseline(cls, value: Any) -> Any:
        return value.model_dump(mode="json") if isinstance(value, ComponentVector) else value

    @field_validator("scenarios", mode="before")
    @classmethod
    def snapshot_scenarios(cls, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise ValueError("scenarios must be provided as a list or tuple")
        return [
            item.model_dump(mode="json") if isinstance(item, ComponentVector) else item
            for item in value
        ]

    @field_validator(
        "production_policy_selected",
        "estimator_preference_defined",
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

    @model_validator(mode="after")
    def enforce_common_analysis_boundary(self) -> Self:
        estimator_ids = [spec.estimator_id for spec in self.estimator_specs]
        if len(estimator_ids) != len(set(estimator_ids)):
            raise ValueError("estimator IDs must be unique")
        if any(
            spec.task_profile_commitment != self.task_profile_commitment
            for spec in self.estimator_specs
        ):
            raise ValueError("all estimators must bind the analysis task profile")

        vectors = (self.baseline, *self.scenarios)
        vector_ids = [vector.vector_id for vector in vectors]
        if len(vector_ids) != len(set(vector_ids)):
            raise ValueError("vector IDs must be unique")
        component_names = {item.component for item in self.baseline.components}
        if any(
            {item.component for item in vector.components} != component_names
            for vector in self.scenarios
        ):
            raise ValueError("all vectors must contain the same component names")
        if any(set(spec.component_weights) != component_names for spec in self.estimator_specs):
            raise ValueError("all estimator weights must exactly match vector components")

        object.__setattr__(
            self,
            "estimator_specs",
            tuple(sorted(self.estimator_specs, key=lambda item: item.estimator_id)),
        )
        object.__setattr__(
            self, "scenarios", tuple(sorted(self.scenarios, key=lambda item: item.vector_id))
        )
        return self

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def commitment(self) -> str:
        return canonical_sha256(self.to_payload(), domain=ANALYSIS_COMMITMENT_DOMAIN)


class SensitivityScenarioResult(StrictAnalysisModel):
    scenario_id: StrictStr = Field(min_length=1, max_length=128)
    changed_components: tuple[ComponentName, ...] = Field(max_length=64)
    estimate: UnitRatio
    delta_from_baseline: SignedRatio
    direction: ChangeDirection

    @field_validator("estimate", "delta_from_baseline", mode="before")
    @classmethod
    def snapshot_ratios(cls, value: Any) -> Any:
        return value.model_dump(mode="json") if isinstance(value, BaseModel) else value

    @field_validator("changed_components", mode="before")
    @classmethod
    def require_concrete_changed_components(cls, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise ValueError("changed components must be provided as a list or tuple")
        return value

    @field_validator("changed_components")
    @classmethod
    def require_canonical_changed_components(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("changed components must be unique and canonically ordered")
        return value


class EstimatorSensitivityResult(StrictAnalysisModel):
    estimator_id: StrictStr = Field(min_length=1, max_length=128)
    estimator_commitment: Commitment
    baseline_estimate: UnitRatio
    scenarios: tuple[SensitivityScenarioResult, ...] = Field(min_length=1, max_length=256)

    @field_validator("baseline_estimate", mode="before")
    @classmethod
    def snapshot_baseline_estimate(cls, value: Any) -> Any:
        return value.model_dump(mode="json") if isinstance(value, UnitRatio) else value

    @field_validator("scenarios", mode="before")
    @classmethod
    def snapshot_scenario_results(cls, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise ValueError("scenario results must be provided as a list or tuple")
        return [
            item.model_dump(mode="json") if isinstance(item, SensitivityScenarioResult) else item
            for item in value
        ]


class ComponentwiseRelationResult(StrictAnalysisModel):
    left_vector_id: StrictStr = Field(min_length=1, max_length=128)
    right_vector_id: StrictStr = Field(min_length=1, max_length=128)
    relation: ComponentwiseRelation


class SensitivityAnalysisResult(StrictAnalysisModel):
    analysis_spec: SensitivityAnalysisSpec
    analysis_commitment: Commitment
    sensitivity_results: tuple[EstimatorSensitivityResult, ...] = Field(min_length=1, max_length=16)
    componentwise_relations: tuple[ComponentwiseRelationResult, ...] = Field(
        min_length=1, max_length=MAX_COMPONENTWISE_RELATIONS
    )
    relation_semantics: Literal["PAIRWISE_COMPONENT_VALUES_ONLY"]
    production_policy_selected: Literal[False]
    estimator_preference_defined: Literal[False]
    normative_scoring: Literal[False]
    winner_selected: Literal[False]
    ranking_defined: Literal[False]
    weight_policy_defined: Literal[False]
    chain_action_defined: Literal[False]
    result_commitment: Commitment

    @field_validator("analysis_spec", mode="before")
    @classmethod
    def snapshot_analysis_spec(cls, value: Any) -> Any:
        return (
            value.model_dump(mode="json") if isinstance(value, SensitivityAnalysisSpec) else value
        )

    @field_validator("sensitivity_results", mode="before")
    @classmethod
    def snapshot_sensitivity_results(cls, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise ValueError("sensitivity results must be provided as a list or tuple")
        return [
            item.model_dump(mode="json") if isinstance(item, EstimatorSensitivityResult) else item
            for item in value
        ]

    @field_validator("componentwise_relations", mode="before")
    @classmethod
    def snapshot_componentwise_relations(cls, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise ValueError("componentwise relations must be provided as a list or tuple")
        return [
            item.model_dump(mode="json") if isinstance(item, ComponentwiseRelationResult) else item
            for item in value
        ]

    @field_validator(
        "production_policy_selected",
        "estimator_preference_defined",
        "normative_scoring",
        "winner_selected",
        "ranking_defined",
        "weight_policy_defined",
        "chain_action_defined",
        mode="before",
    )
    @classmethod
    def require_boolean_false(cls, value: Any) -> bool:
        if value is not False:
            raise ValueError("reserved result boundary must be the boolean false")
        return False

    @model_validator(mode="after")
    def verify_bindings_and_commitment(self) -> Self:
        if self.analysis_commitment != self.analysis_spec.commitment:
            raise ValueError("analysis result does not bind its embedded specification")
        body = self.model_dump(mode="json", exclude={"result_commitment"})
        if body != _sensitivity_analysis_body(self.analysis_spec):
            raise ValueError("sensitivity result does not match its embedded specification")
        if self.result_commitment != canonical_sha256(body, domain=RESULT_COMMITMENT_DOMAIN):
            raise ValueError("sensitivity result commitment mismatch")
        return self

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def create_sensitivity_analysis_spec(
    *,
    task_profile_commitment: str,
    estimator_specs: tuple[EstimatorSpec, ...],
    baseline: ComponentVector,
    scenarios: tuple[ComponentVector, ...],
) -> SensitivityAnalysisSpec:
    return SensitivityAnalysisSpec(
        analysis_version=ANALYSIS_VERSION,
        analysis_state=ANALYSIS_STATE,
        task_profile_commitment=task_profile_commitment,
        estimator_specs=estimator_specs,
        baseline=baseline,
        scenarios=scenarios,
        output_semantics="DESCRIPTIVE_ESTIMATOR_SENSITIVITY",
        production_policy_selected=False,
        estimator_preference_defined=False,
        normative_scoring=False,
        winner_selection_defined=False,
        ranking_defined=False,
        weight_policy_defined=False,
        chain_action_defined=False,
    )


def parse_sensitivity_analysis_spec(value: str | bytes) -> SensitivityAnalysisSpec:
    size = len(value.encode("utf-8")) if isinstance(value, str) else len(value)
    if size > MAX_ANALYSIS_JSON_BYTES:
        raise ValueError(f"analysis JSON cannot exceed {MAX_ANALYSIS_JSON_BYTES} bytes")
    return SensitivityAnalysisSpec.model_validate(parse_json_strict(value))


def _fraction(payload: dict[str, int]) -> Fraction:
    return Fraction(payload["numerator"], payload["denominator"])


def _signed_ratio_payload(value: Fraction) -> dict[str, int]:
    ratio = SignedRatio(numerator=value.numerator, denominator=value.denominator)
    return ratio.model_dump(mode="json")


def _component_map(vector: ComponentVector) -> dict[str, Fraction]:
    return {item.component: item.value.fraction for item in vector.components}


def _componentwise_relation(left: ComponentVector, right: ComponentVector) -> ComponentwiseRelation:
    left_values = _component_map(left)
    right_values = _component_map(right)
    if set(left_values) != set(right_values):
        raise ValueError("componentwise comparison requires matching component names")
    differences = [left_values[name] - right_values[name] for name in sorted(left_values)]
    if all(delta == 0 for delta in differences):
        return ComponentwiseRelation.EQUAL
    if all(delta >= 0 for delta in differences):
        return ComponentwiseRelation.LEFT_DOMINATES
    if all(delta <= 0 for delta in differences):
        return ComponentwiseRelation.RIGHT_DOMINATES
    return ComponentwiseRelation.INCOMPARABLE


def _sensitivity_analysis_body(spec: SensitivityAnalysisSpec) -> dict[str, Any]:
    """Derive the complete deterministic result body for one validated specification."""

    sensitivity_results: list[dict[str, Any]] = []
    for estimator in spec.estimator_specs:
        baseline_result = estimate_components(spec=estimator, components=spec.baseline.components)
        baseline_estimate = _fraction(baseline_result["estimate"])
        scenario_results: list[dict[str, Any]] = []
        baseline_components = _component_map(spec.baseline)
        for scenario in spec.scenarios:
            result = estimate_components(spec=estimator, components=scenario.components)
            estimate = _fraction(result["estimate"])
            delta = estimate - baseline_estimate
            direction = (
                ChangeDirection.INCREASED
                if delta > 0
                else ChangeDirection.DECREASED
                if delta < 0
                else ChangeDirection.UNCHANGED
            )
            scenario_components = _component_map(scenario)
            scenario_results.append(
                {
                    "scenario_id": scenario.vector_id,
                    "changed_components": [
                        name
                        for name in sorted(baseline_components)
                        if baseline_components[name] != scenario_components[name]
                    ],
                    "estimate": result["estimate"],
                    "delta_from_baseline": _signed_ratio_payload(delta),
                    "direction": direction.value,
                }
            )
        sensitivity_results.append(
            {
                "estimator_id": estimator.estimator_id,
                "estimator_commitment": estimator.commitment,
                "baseline_estimate": baseline_result["estimate"],
                "scenarios": scenario_results,
            }
        )

    vectors = (spec.baseline, *spec.scenarios)
    relations = [
        {
            "left_vector_id": left.vector_id,
            "right_vector_id": right.vector_id,
            "relation": _componentwise_relation(left, right).value,
        }
        for left_index, left in enumerate(vectors)
        for right in vectors[left_index + 1 :]
    ]
    return {
        "analysis_spec": spec.to_payload(),
        "analysis_commitment": spec.commitment,
        "sensitivity_results": sensitivity_results,
        "componentwise_relations": relations,
        "relation_semantics": "PAIRWISE_COMPONENT_VALUES_ONLY",
        "production_policy_selected": False,
        "estimator_preference_defined": False,
        "normative_scoring": False,
        "winner_selected": False,
        "ranking_defined": False,
        "weight_policy_defined": False,
        "chain_action_defined": False,
    }


def analyze_sensitivity(*, spec: SensitivityAnalysisSpec) -> dict[str, Any]:
    if not isinstance(spec, SensitivityAnalysisSpec):
        raise TypeError("spec must be a SensitivityAnalysisSpec")
    spec = SensitivityAnalysisSpec.model_validate(spec.model_dump(mode="json"))

    body = _sensitivity_analysis_body(spec)
    result = body | {"result_commitment": canonical_sha256(body, domain=RESULT_COMMITMENT_DOMAIN)}
    return SensitivityAnalysisResult.model_validate(result).to_payload()
