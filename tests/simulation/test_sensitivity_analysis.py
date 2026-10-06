import json

import pytest

from sn87_provenonce.protocol.v0alpha1 import canonical_sha256
from sn87_provenonce.simulation.estimator_comparison import (
    ComponentValue,
    EstimatorKind,
    UnitRatio,
    create_estimator_spec,
)
from sn87_provenonce.simulation.lane_one_profile import ExactRatio
from sn87_provenonce.simulation.sensitivity_analysis import (
    MAX_ANALYSIS_JSON_BYTES,
    ComponentVector,
    SensitivityScenarioResult,
    analyze_sensitivity,
    create_sensitivity_analysis_spec,
    parse_sensitivity_analysis_spec,
)

PROFILE_COMMITMENT = canonical_sha256(
    {"profile": "sensitivity-test"}, domain="SN87:TEST_TASK_PROFILE:v0alpha1"
)


def ratio(numerator: int, denominator: int = 1) -> ExactRatio:
    return ExactRatio(numerator=numerator, denominator=denominator)


def vector(vector_id: str, detection: tuple[int, int], evidence: tuple[int, int]):
    return ComponentVector(
        vector_id=vector_id,
        components=(
            ComponentValue(
                component="detection",
                value=UnitRatio(numerator=detection[0], denominator=detection[1]),
            ),
            ComponentValue(
                component="evidence",
                value=UnitRatio(numerator=evidence[0], denominator=evidence[1]),
            ),
        ),
    )


def estimator(estimator_id: str, kind: EstimatorKind):
    return create_estimator_spec(
        estimator_id=estimator_id,
        task_profile_commitment=PROFILE_COMMITMENT,
        kind=kind,
        component_weights={"detection": ratio(1), "evidence": ratio(1)},
    )


def analysis_spec():
    return create_sensitivity_analysis_spec(
        task_profile_commitment=PROFILE_COMMITMENT,
        estimator_specs=(
            estimator("harmonic", EstimatorKind.WEIGHTED_HARMONIC_MEAN),
            estimator("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN),
        ),
        baseline=vector("baseline", (1, 2), (1, 2)),
        scenarios=(
            vector("detection-up", (1, 1), (1, 2)),
            vector("evidence-down", (1, 2), (1, 4)),
            vector("tradeoff", (1, 4), (1, 1)),
        ),
    )


def test_sensitivity_reports_exact_deltas_without_selection() -> None:
    result = analyze_sensitivity(spec=analysis_spec())
    arithmetic = result["sensitivity_results"][0]
    assert arithmetic["estimator_id"] == "arithmetic"
    assert arithmetic["baseline_estimate"] == {"numerator": 1, "denominator": 2}
    assert arithmetic["scenarios"][0] == {
        "scenario_id": "detection-up",
        "changed_components": ["detection"],
        "estimate": {"numerator": 3, "denominator": 4},
        "delta_from_baseline": {"numerator": 1, "denominator": 4},
        "direction": "INCREASED",
    }
    assert arithmetic["scenarios"][1]["delta_from_baseline"] == {
        "numerator": -1,
        "denominator": 8,
    }
    assert result["production_policy_selected"] is False
    assert result["estimator_preference_defined"] is False
    assert result["winner_selected"] is False
    assert result["ranking_defined"] is False
    assert result["weight_policy_defined"] is False


def test_componentwise_relations_are_pairwise_and_complete() -> None:
    result = analyze_sensitivity(spec=analysis_spec())
    relations = {
        (item["left_vector_id"], item["right_vector_id"]): item["relation"]
        for item in result["componentwise_relations"]
    }
    assert len(relations) == 6
    assert relations[("baseline", "detection-up")] == "RIGHT_COMPONENTWISE_DOMINATES"
    assert relations[("baseline", "evidence-down")] == "LEFT_COMPONENTWISE_DOMINATES"
    assert relations[("baseline", "tradeoff")] == "COMPONENTWISE_INCOMPARABLE"


def test_analysis_is_order_independent_and_self_committing() -> None:
    original = analysis_spec()
    reordered = create_sensitivity_analysis_spec(
        task_profile_commitment=PROFILE_COMMITMENT,
        estimator_specs=tuple(reversed(original.estimator_specs)),
        baseline=ComponentVector(
            vector_id=original.baseline.vector_id,
            components=tuple(reversed(original.baseline.components)),
        ),
        scenarios=tuple(reversed(original.scenarios)),
    )
    assert original == reordered
    assert analyze_sensitivity(spec=original) == analyze_sensitivity(spec=reordered)


def test_analysis_spec_is_strict_and_fail_closed() -> None:
    spec = analysis_spec()
    payload = spec.to_payload()
    assert parse_sensitivity_analysis_spec(json.dumps(payload)) == spec
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        parse_sensitivity_analysis_spec(json.dumps(payload | {"selected_estimator": "x"}))
    with pytest.raises(ValueError, match="boolean false"):
        parse_sensitivity_analysis_spec(json.dumps(payload | {"production_policy_selected": True}))
    for false_field in (
        "production_policy_selected",
        "estimator_preference_defined",
        "normative_scoring",
        "winner_selection_defined",
        "ranking_defined",
        "weight_policy_defined",
        "chain_action_defined",
    ):
        for numeric_false in (0, 0.0):
            with pytest.raises(ValueError, match="boolean false"):
                parse_sensitivity_analysis_spec(json.dumps(payload | {false_field: numeric_false}))
    incomplete = dict(payload)
    del incomplete["estimator_preference_defined"]
    with pytest.raises(ValueError, match="estimator_preference_defined"):
        parse_sensitivity_analysis_spec(json.dumps(incomplete))


def test_analysis_cardinality_is_bounded() -> None:
    baseline = vector("baseline", (1, 2), (1, 2))
    arithmetic = estimator("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN)
    scenarios = tuple(vector(f"scenario-{index}", (1, 2), (1, 2)) for index in range(257))
    with pytest.raises(ValueError, match="at most 256"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=(arithmetic,),
            baseline=baseline,
            scenarios=scenarios,
        )


def test_analysis_revalidates_copied_typed_models() -> None:
    spec = analysis_spec()
    bypassed_estimator = spec.estimator_specs[0].model_copy(update={"ranking_defined": True})
    with pytest.raises(ValueError, match="boolean false"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=(bypassed_estimator,),
            baseline=spec.baseline,
            scenarios=spec.scenarios,
        )

    bypassed_estimator_id = spec.estimator_specs[0].model_copy(update={"estimator_id": "e" * 129})
    with pytest.raises(ValueError, match="at most 128"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=(bypassed_estimator_id,),
            baseline=spec.baseline,
            scenarios=spec.scenarios,
        )

    bypassed_vector_id = spec.scenarios[0].model_copy(update={"vector_id": " scenario "})
    with pytest.raises(ValueError, match="surrounding whitespace"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=spec.estimator_specs,
            baseline=spec.baseline,
            scenarios=(bypassed_vector_id,),
        )

    oversized_vector = spec.scenarios[0].model_copy(
        update={"components": spec.scenarios[0].components * 33}
    )
    with pytest.raises(ValueError, match="at most 64"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=spec.estimator_specs,
            baseline=spec.baseline,
            scenarios=(oversized_vector,),
        )

    bypassed_analysis = spec.model_copy(
        update={"normative_scoring": True, "winner_selection_defined": True}
    )
    with pytest.raises(ValueError, match="boolean false"):
        analyze_sensitivity(spec=bypassed_analysis)

    bypassed_scenarios = spec.model_copy(update={"scenarios": spec.scenarios * 100})
    with pytest.raises(ValueError, match="at most 256"):
        analyze_sensitivity(spec=bypassed_scenarios)


def test_analysis_parser_bounds_bytes_and_integer_magnitude() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        parse_sensitivity_analysis_spec(" " * (MAX_ANALYSIS_JSON_BYTES + 1))

    payload = analysis_spec().to_payload()
    payload["baseline"]["components"][0]["value"]["numerator"] = 1 << 4096
    with pytest.raises(ValueError, match="4096 bits"):
        parse_sensitivity_analysis_spec(json.dumps(payload))


def test_analysis_rejects_lazy_or_unordered_nested_collections() -> None:
    spec = analysis_spec()
    bypassed_estimator = spec.estimator_specs[0].model_copy(update={"normative_scoring": True})
    with pytest.raises(ValueError, match="list or tuple"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=(item for item in (bypassed_estimator,)),  # type: ignore[arg-type]
            baseline=spec.baseline,
            scenarios=spec.scenarios,
        )

    bypassed_vector = spec.scenarios[0].model_copy(update={"vector_id": " scenario "})
    with pytest.raises(ValueError, match="list or tuple"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=spec.estimator_specs,
            baseline=spec.baseline,
            scenarios=(item for item in (bypassed_vector,)),  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="list or tuple"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=spec.estimator_specs,
            baseline=spec.baseline,
            scenarios={spec.scenarios[0]},  # type: ignore[arg-type]
        )

    huge_ratio = spec.scenarios[0].components[0].value.model_copy(update={"numerator": 1 << 4096})
    huge_component = spec.scenarios[0].components[0].model_copy(update={"value": huge_ratio})
    with pytest.raises(ValueError, match="list or tuple"):
        ComponentVector(
            vector_id="generator-vector",
            components=(item for item in (huge_component,)),  # type: ignore[arg-type]
        )


def test_analysis_rejects_misaligned_profiles_components_and_ids() -> None:
    baseline = vector("baseline", (1, 2), (1, 2))
    scenario = vector("scenario", (1, 1), (1, 2))
    arithmetic = estimator("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN)
    other_profile = create_estimator_spec(
        estimator_id="other",
        task_profile_commitment=canonical_sha256(
            {"profile": "other"}, domain="SN87:TEST_TASK_PROFILE:v0alpha1"
        ),
        kind=EstimatorKind.WEIGHTED_ARITHMETIC_MEAN,
        component_weights={"detection": ratio(1), "evidence": ratio(1)},
    )
    with pytest.raises(ValueError, match="bind the analysis task profile"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=(arithmetic, other_profile),
            baseline=baseline,
            scenarios=(scenario,),
        )
    with pytest.raises(ValueError, match="vector IDs must be unique"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=(arithmetic,),
            baseline=baseline,
            scenarios=(ComponentVector(vector_id="baseline", components=scenario.components),),
        )
    incomplete = ComponentVector(vector_id="incomplete", components=(scenario.components[0],))
    with pytest.raises(ValueError, match="same component names"):
        create_sensitivity_analysis_spec(
            task_profile_commitment=PROFILE_COMMITMENT,
            estimator_specs=(arithmetic,),
            baseline=baseline,
            scenarios=(incomplete,),
        )


def test_componentwise_equality_and_unchanged_sensitivity_are_explicit() -> None:
    baseline = vector("baseline", (1, 2), (1, 2))
    same = vector("same", (1, 2), (1, 2))
    spec = create_sensitivity_analysis_spec(
        task_profile_commitment=PROFILE_COMMITMENT,
        estimator_specs=(estimator("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN),),
        baseline=baseline,
        scenarios=(same,),
    )
    result = analyze_sensitivity(spec=spec)
    scenario = result["sensitivity_results"][0]["scenarios"][0]
    assert scenario["changed_components"] == []
    assert scenario["direction"] == "UNCHANGED"
    assert scenario["delta_from_baseline"] == {"numerator": 0, "denominator": 1}
    assert result["componentwise_relations"][0]["relation"] == "COMPONENTWISE_EQUAL"


@pytest.mark.parametrize(
    "changed_components, message",
    [
        ({"detection"}, "list or tuple"),
        (("evidence", "detection"), "canonically ordered"),
        (("detection", "detection"), "unique"),
        (("x" * 129,), "at most 128 characters"),
    ],
)
def test_scenario_result_requires_bounded_canonical_changed_components(
    changed_components, message
) -> None:
    with pytest.raises(ValueError, match=message):
        SensitivityScenarioResult(
            scenario_id="scenario",
            changed_components=changed_components,
            estimate={"numerator": 1, "denominator": 2},
            delta_from_baseline={"numerator": 0, "denominator": 1},
            direction="UNCHANGED",
        )


def test_vector_rejects_unicode_equivalent_component_names() -> None:
    with pytest.raises(ValueError, match="component names must be unique"):
        ComponentVector(
            vector_id="unicode-vector",
            components=(
                ComponentValue(component="é", value=UnitRatio(numerator=1, denominator=1)),
                ComponentValue(component="e\u0301", value=UnitRatio(numerator=1, denominator=2)),
            ),
        )


def test_runtime_entrypoint_rejects_wrong_type() -> None:
    with pytest.raises(TypeError, match="SensitivityAnalysisSpec"):
        analyze_sensitivity(spec={})  # type: ignore[arg-type]
