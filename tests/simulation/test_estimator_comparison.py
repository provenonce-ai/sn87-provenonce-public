import json
from fractions import Fraction

import pytest

from sn87_provenonce.protocol.v0alpha1 import canonical_sha256
from sn87_provenonce.simulation.estimator_comparison import (
    ComponentValue,
    EstimatorKind,
    UnitRatio,
    compare_estimators,
    create_estimator_spec,
    estimate_components,
    parse_estimator_spec,
)
from sn87_provenonce.simulation.lane_one_profile import ExactRatio

PROFILE_COMMITMENT = canonical_sha256({"profile": "test"}, domain="SN87:TEST_TASK_PROFILE:v0alpha1")


def ratio(numerator: int, denominator: int = 1) -> ExactRatio:
    return ExactRatio(numerator=numerator, denominator=denominator)


def components(*values: tuple[str, int, int]) -> tuple[ComponentValue, ...]:
    return tuple(
        ComponentValue(
            component=name,
            value=UnitRatio(numerator=numerator, denominator=denominator),
        )
        for name, numerator, denominator in values
    )


def spec(estimator_id: str, kind: EstimatorKind):
    return create_estimator_spec(
        estimator_id=estimator_id,
        task_profile_commitment=PROFILE_COMMITMENT,
        kind=kind,
        component_weights={"detection": ratio(1), "evidence": ratio(1)},
    )


def test_arithmetic_and_harmonic_estimators_are_exact() -> None:
    vector = components(("detection", 1, 1), ("evidence", 1, 2))
    arithmetic = estimate_components(
        spec=spec("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN),
        components=vector,
    )
    harmonic = estimate_components(
        spec=spec("harmonic", EstimatorKind.WEIGHTED_HARMONIC_MEAN),
        components=tuple(reversed(vector)),
    )
    assert arithmetic["estimate"] == {"numerator": 3, "denominator": 4}
    assert harmonic["estimate"] == {"numerator": 2, "denominator": 3}
    assert arithmetic["winner_selected"] is False
    assert harmonic["ranking_defined"] is False


def test_harmonic_estimator_is_zero_sensitive() -> None:
    result = estimate_components(
        spec=spec("harmonic", EstimatorKind.WEIGHTED_HARMONIC_MEAN),
        components=components(("detection", 1, 1), ("evidence", 0, 1)),
    )
    assert result["estimate"] == {"numerator": 0, "denominator": 1}


def test_comparison_is_order_independent_and_selects_no_winner() -> None:
    arithmetic = spec("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN)
    harmonic = spec("harmonic", EstimatorKind.WEIGHTED_HARMONIC_MEAN)
    vector = components(("evidence", 1, 2), ("detection", 1, 1))
    first = compare_estimators(specs=(harmonic, arithmetic), components=vector)
    second = compare_estimators(specs=(arithmetic, harmonic), components=tuple(reversed(vector)))
    assert first == second
    assert first["winner_selected"] is False
    assert first["ranking_defined"] is False
    assert first["production_policy_selected"] is False


def test_estimator_rejects_mismatched_or_duplicate_components() -> None:
    estimator = spec("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN)
    with pytest.raises(ValueError, match="exactly match"):
        estimate_components(
            spec=estimator,
            components=components(("detection", 1, 1)),
        )
    with pytest.raises(ValueError, match="must be unique"):
        estimate_components(
            spec=estimator,
            components=components(("detection", 1, 1), ("detection", 1, 2)),
        )


def test_estimator_rejects_unicode_equivalent_component_names() -> None:
    with pytest.raises(ValueError, match="unique after NFC normalization"):
        create_estimator_spec(
            estimator_id="unicode-components",
            task_profile_commitment=PROFILE_COMMITMENT,
            kind=EstimatorKind.WEIGHTED_ARITHMETIC_MEAN,
            component_weights={"é": ratio(1), "e\u0301": ratio(1)},
        )

    estimator = create_estimator_spec(
        estimator_id="unicode-components",
        task_profile_commitment=PROFILE_COMMITMENT,
        kind=EstimatorKind.WEIGHTED_ARITHMETIC_MEAN,
        component_weights={"é": ratio(1)},
    )
    with pytest.raises(ValueError, match="component names must be unique"):
        estimate_components(
            spec=estimator,
            components=components(("é", 1, 1), ("e\u0301", 1, 2)),
        )


def test_comparison_requires_same_profile_and_unique_estimators() -> None:
    arithmetic = spec("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN)
    different_profile = create_estimator_spec(
        estimator_id="harmonic",
        task_profile_commitment=canonical_sha256(
            {"profile": "other"}, domain="SN87:TEST_TASK_PROFILE:v0alpha1"
        ),
        kind=EstimatorKind.WEIGHTED_HARMONIC_MEAN,
        component_weights={"detection": ratio(1), "evidence": ratio(1)},
    )
    vector = components(("detection", 1, 1), ("evidence", 1, 2))
    with pytest.raises(ValueError, match="same task profile"):
        compare_estimators(specs=(arithmetic, different_profile), components=vector)
    with pytest.raises(ValueError, match="IDs must be unique"):
        compare_estimators(specs=(arithmetic, arithmetic), components=vector)
    with pytest.raises(ValueError, match="at least two"):
        compare_estimators(specs=(arithmetic,), components=vector)


def test_estimator_artifact_is_complete_and_fail_closed() -> None:
    estimator = spec("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN)
    payload = estimator.to_payload()
    assert parse_estimator_spec(json.dumps(payload)) == estimator
    assert parse_estimator_spec(json.dumps(payload)).commitment == estimator.commitment
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        parse_estimator_spec(json.dumps(payload | {"winner": "arithmetic"}))
    with pytest.raises(ValueError, match="boolean false"):
        parse_estimator_spec(json.dumps(payload | {"ranking_defined": True}))
    for false_field in (
        "normative_scoring",
        "winner_selection_defined",
        "ranking_defined",
        "weight_policy_defined",
        "chain_action_defined",
    ):
        for numeric_false in (0, 0.0):
            with pytest.raises(ValueError, match="boolean false"):
                parse_estimator_spec(json.dumps(payload | {false_field: numeric_false}))
    incomplete = dict(payload)
    del incomplete["chain_action_defined"]
    with pytest.raises(ValueError, match="chain_action_defined"):
        parse_estimator_spec(json.dumps(incomplete))


def test_estimation_revalidates_copied_typed_models() -> None:
    estimator = spec("arithmetic", EstimatorKind.WEIGHTED_ARITHMETIC_MEAN)
    bypassed = estimator.model_copy(update={"normative_scoring": True})
    with pytest.raises(ValueError, match="boolean false"):
        estimate_components(
            spec=bypassed,
            components=components(("detection", 1, 1), ("evidence", 1, 2)),
        )
    valid_component = components(("detection", 1, 1))[0]
    invalid_ratio = valid_component.value.model_copy(update={"denominator": 0})
    bypassed_component = valid_component.model_copy(update={"value": invalid_ratio})
    with pytest.raises(ValueError, match="greater than 0"):
        estimate_components(
            spec=estimator,
            components=(bypassed_component, components(("evidence", 1, 2))[0]),
        )


def test_estimators_are_bounded_and_monotone_on_disclosed_grid() -> None:
    kinds = (
        EstimatorKind.WEIGHTED_ARITHMETIC_MEAN,
        EstimatorKind.WEIGHTED_HARMONIC_MEAN,
    )
    grid = (0, 1, 2, 3, 4)
    for kind in kinds:
        estimator = create_estimator_spec(
            estimator_id=kind.value.lower(),
            task_profile_commitment=PROFILE_COMMITMENT,
            kind=kind,
            component_weights={"detection": ratio(1), "evidence": ratio(2)},
        )
        for left in grid:
            for right in grid:
                current = estimate_components(
                    spec=estimator,
                    components=components(("detection", left, 4), ("evidence", right, 4)),
                )["estimate"]
                current_value = Fraction(current["numerator"], current["denominator"])
                assert 0 <= current_value <= 1
                if left < 4:
                    improved = estimate_components(
                        spec=estimator,
                        components=components(("detection", left + 1, 4), ("evidence", right, 4)),
                    )["estimate"]
                    improved_value = Fraction(improved["numerator"], improved["denominator"])
                    assert improved_value >= current_value
                if right < 4:
                    improved = estimate_components(
                        spec=estimator,
                        components=components(("detection", left, 4), ("evidence", right + 1, 4)),
                    )["estimate"]
                    improved_value = Fraction(improved["numerator"], improved["denominator"])
                    assert improved_value >= current_value
