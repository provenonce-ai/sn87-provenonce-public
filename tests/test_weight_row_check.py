"""The scores-to-weights comparison for the private plan and submit paths. Fakes only."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import weight_row_check as wrc  # noqa: E402

PINNED = {"uids": [10, 11], "u16_weights": [65535, 21845]}


def mismatch(code, *args, **kwargs):
    with pytest.raises(wrc.WeightRowMismatch) as info:
        wrc.require_row_equals_pinned(*args, **kwargs)
    assert info.value.code == code
    return info.value


def test_an_equal_row_passes_in_any_order():
    wrc.require_row_equals_pinned([10, 11], [65535, 21845], PINNED)
    wrc.require_row_equals_pinned([11, 10], [21845, 65535], PINNED)


def test_a_uid_map_translates_pinned_uids_to_row_uids():
    wrc.require_row_equals_pinned([1, 2], [65535, 21845], PINNED, uid_map={10: 1, 11: 2})
    mismatch("ROW_WEIGHTS_DIFFER", [1, 2], [21845, 65535], PINNED, uid_map={10: 1, 11: 2})
    mismatch("PINNED_UID_UNMAPPED", [1, 2], [65535, 21845], PINNED, uid_map={10: 1})
    mismatch("UID_MAP_NOT_ONE_TO_ONE", [1, 2], [65535, 21845], PINNED, uid_map={10: 1, 11: 1})


def test_a_different_value_or_uid_list_fails():
    mismatch("ROW_WEIGHTS_DIFFER", [10, 11], [65535, 21844], PINNED)
    mismatch("ROW_UIDS_DIFFER", [10, 12], [65535, 21845], PINNED)
    mismatch("ROW_UIDS_DIFFER", [10], [65535], PINNED)
    mismatch("ROW_UIDS_DIFFER", [10, 11, 12], [65535, 21845, 1], PINNED)


@pytest.mark.parametrize("pinned", [None, [], "x", {}, {"uids": [1]},
                                    {"uids": [1], "u16_weights": []},
                                    {"uids": [1.0], "u16_weights": [1]},
                                    {"uids": [True], "u16_weights": [1]},
                                    {"uids": [1, 1], "u16_weights": [1, 2]}])
def test_missing_or_malformed_pinned_weights_fail_closed(pinned):
    with pytest.raises(wrc.WeightRowMismatch):
        wrc.require_row_equals_pinned([1], [1], pinned)


def test_a_missing_pinned_row_is_a_refusal_not_an_unverified_pass():
    assert mismatch("PINNED_WEIGHTS_MISSING", [10], [1], None).code == "PINNED_WEIGHTS_MISSING"


def test_an_empty_pinned_row_fails_unless_allowed_and_the_row_is_empty():
    empty = {"uids": [], "u16_weights": []}
    mismatch("PINNED_ROW_EMPTY", [10], [1], empty)
    mismatch("PINNED_ROW_EMPTY", [], [], empty)
    mismatch("PINNED_ROW_EMPTY", [10], [1], empty, allow_empty=True)
    wrc.require_row_equals_pinned([], [], empty, allow_empty=True)


@pytest.mark.parametrize("dests,weights", [([1], []), ([1, 1], [2, 2]), ("a", "b"), (None, None),
                                           ([1.5], [1]), ([1], [True])])
def test_a_malformed_row_fails(dests, weights):
    with pytest.raises(wrc.WeightRowMismatch):
        wrc.require_row_equals_pinned(dests, weights, PINNED)


def test_same_weight_values_is_a_multiset_comparison_with_a_required_sum():
    pinned = {"uids": [1, 2], "u16_weights": [65535, 30000]}
    wrc.require_same_weight_values([30000, 65535], pinned, total=95535)
    for weights, total, code in (([65535, 30001], 95536, "ROW_WEIGHTS_DIFFER"),
                                 ([65535], 65535, "ROW_WEIGHTS_DIFFER"),
                                 ([65535, 30000], 1, "ROW_SUM_DIFFERS"),
                                 ([65535, 30000], None, "ROW_SUM_DIFFERS"),  # total is required
                                 ([65535, 30000], True, "ROW_SUM_DIFFERS"),
                                 ("x", 1, "ROW_MALFORMED")):
        with pytest.raises(wrc.WeightRowMismatch) as info:
            wrc.require_same_weight_values(weights, pinned, total=total)
        assert info.value.code == code
    with pytest.raises(TypeError):
        wrc.require_same_weight_values([30000, 65535], pinned)  # type: ignore[call-arg]
    with pytest.raises(wrc.WeightRowMismatch):
        wrc.require_same_weight_values([1], {"uids": [], "u16_weights": []}, total=1)
    with pytest.raises(wrc.WeightRowMismatch):
        wrc.require_same_weight_values([1], None, total=1)


@pytest.mark.parametrize("bad", [-1, 65536, 10**9])
def test_values_and_uids_outside_u16_fail(bad):
    mismatch("ROW_MALFORMED", [1], [bad], {"uids": [1], "u16_weights": [1]})
    mismatch("ROW_MALFORMED", [bad], [1], {"uids": [1], "u16_weights": [1]})
    mismatch("PINNED_WEIGHTS_MALFORMED", [1], [1], {"uids": [1], "u16_weights": [bad]})
    mismatch("PINNED_WEIGHTS_MALFORMED", [1], [1], {"uids": [bad], "u16_weights": [1]})
    wrc.require_row_equals_pinned([0, 65535], [0, 65535], {"uids": [0, 65535],
                                                           "u16_weights": [0, 65535]})


def test_uid_map_from_binding():
    miners = [{"staging_miner_id": "a", "expected_uid": 7},
              {"staging_miner_id": "b", "expected_uid": 9}]
    assert wrc.uid_map_from_binding({"1": "a", "2": "b"}, miners) == {1: 7, 2: 9}
    for bad_map, bad_miners in (({"1": "c"}, miners), (None, miners), ({"x": "a"}, miners),
                                ({"1": "a"}, [{"nope": 1}]), ({"1": "a"}, None)):
        with pytest.raises(wrc.WeightRowMismatch):
            wrc.uid_map_from_binding(bad_map, bad_miners)


def test_the_module_is_pure():
    import ast
    tree = ast.parse((SCRIPTS / "weight_row_check.py").read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "collections.abc", "typing"}, imported
    assert importlib.util.find_spec("weight_row_check") is not None
    assert copy.deepcopy(PINNED) == PINNED
