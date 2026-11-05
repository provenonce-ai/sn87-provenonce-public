"""The step from scores to weights: a check that tools building or submitting a row must call.

PURE. No network, no chain, no wallet, no clock, no file read. Standard library only.

The public verifier (``verify_attestation.check_weights``) compares an attested weight row with
the weight row a recomputed validator receipt pins. These functions make the same comparison
for the tools that BUILD or SUBMIT a row, with one difference: they fail closed. The
verifier may answer UNVERIFIED when no pinned weights could be recomputed; a plan or a
submission may not proceed on a row nobody compared, so a missing, empty, malformed, out-of-range
or different pinned row raises ``WeightRowMismatch`` here.

What each caller compares against matters. A caller given an independent artifact (the pinned
weights of a recomputed validator receipt) makes a real check, including of row order. A caller
that can only compare a plan with the values the plan itself records gets a consistency check,
which catches an inconsistent plan but not one forged consistently, and is not independent
evidence. Every caller must refuse an empty pinned row.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class WeightRowMismatch(ValueError):
    """The row to be set does not equal the pinned weights, or the pinned weights are unusable."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def _is_int(value: Any) -> bool:
    return type(value) is int


def _int_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_int(v) for v in value)


def _u16_list(value: Any) -> bool:
    return _int_list(value) and all(0 <= v <= 65535 for v in value)


def _pinned_lists(pinned: Any) -> tuple[list[int], list[int]]:
    if not isinstance(pinned, Mapping):
        raise WeightRowMismatch("PINNED_WEIGHTS_MISSING", "no pinned weights were supplied")
    uids, u16 = pinned.get("uids"), pinned.get("u16_weights")
    if not (_u16_list(uids) and _u16_list(u16) and len(uids) == len(u16)):
        raise WeightRowMismatch("PINNED_WEIGHTS_MALFORMED",
                                "uids and u16_weights must be equal-length lists of ints in "
                                "0..65535")
    return uids, u16


def _row_lists(dests: Any, weights: Any) -> tuple[list[int], list[int]]:
    if not (_u16_list(dests) and _u16_list(weights) and len(dests) == len(weights)):
        raise WeightRowMismatch("ROW_MALFORMED",
                                "dests and weights must be equal-length lists of ints in "
                                "0..65535")
    if len(set(dests)) != len(dests):
        raise WeightRowMismatch("ROW_DUPLICATE_UID", f"dests {dests}")
    return dests, weights


def require_row_equals_pinned(dests: Any, weights: Any, pinned: Any, *,
                              uid_map: Mapping[int, int] | None = None,
                              allow_empty: bool = False) -> None:
    """Raise unless the row (``dests``, ``weights``) equals the pinned weights.

    ``pinned`` is ``{"uids": [...], "u16_weights": [...]}`` as the validator receipt pins it.
    ``uid_map`` maps a pinned uid to the uid the row uses (the staging uid to the live uid);
    without it the uids compare as they are. Row order does not matter, uids and values do.
    An empty pinned row raises unless ``allow_empty`` and the row is empty too.
    """
    row_uids, row_values = _row_lists(dests, weights)
    pinned_uids, pinned_values = _pinned_lists(pinned)
    if len(set(pinned_uids)) != len(pinned_uids):
        raise WeightRowMismatch("PINNED_WEIGHTS_MALFORMED", f"duplicate uid in {pinned_uids}")
    if not pinned_uids:
        if allow_empty and not row_uids:
            return
        raise WeightRowMismatch("PINNED_ROW_EMPTY",
                                f"the pinned row is empty and the row is {row_uids}")
    if uid_map is not None:
        try:
            pinned_uids = [uid_map[u] for u in pinned_uids]
        except KeyError as error:
            raise WeightRowMismatch("PINNED_UID_UNMAPPED", f"no mapping for {error}") from None
        if len(set(pinned_uids)) != len(pinned_uids):
            raise WeightRowMismatch("UID_MAP_NOT_ONE_TO_ONE", f"mapped uids {pinned_uids}")
    if set(row_uids) != set(pinned_uids):
        raise WeightRowMismatch("ROW_UIDS_DIFFER", f"row uids {row_uids}, pinned {pinned_uids}")
    expected = dict(zip(pinned_uids, pinned_values, strict=True))
    found = dict(zip(row_uids, row_values, strict=True))
    if found != expected:
        raise WeightRowMismatch("ROW_WEIGHTS_DIFFER",
                                f"row {dict(sorted(found.items()))}, "
                                f"pinned {dict(sorted(expected.items()))}")


def uid_map_from_binding(uid_to_method: Any, miners: Any) -> dict[int, int]:
    """Pinned (staging) uid to live uid: ``uid_to_method`` names the method behind each pinned
    uid and each binding miner row names the live uid of a method (``staging_miner_id``).
    Raises ``WeightRowMismatch`` if either side is unusable or a method has no binding row."""
    try:
        live = {row["staging_miner_id"]: row["expected_uid"] for row in miners}
        mapping = {int(uid): live[method] for uid, method in uid_to_method.items()}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise WeightRowMismatch("PINNED_UID_UNMAPPED",
                                "uid_to_method and the binding do not line up") from None
    return mapping


def require_same_weight_values(weights: Any, pinned: Any, *, total: Any) -> None:
    """Weaker form, for a document that carries the pinned row but not the uid labels.

    A consistency check against the document, not against an independent artifact. Raises
    unless the row's u16 values are the pinned u16 values (as a multiset, because the row is in
    live uid order and the pinned row in staging order) and ``total`` equals their sum.
    ``total`` is required: ``None`` raises. It cannot tell which uid holds which value, so a
    permutation passes; ``require_row_equals_pinned`` does tell, where the labels are available.
    """
    if not _u16_list(weights):
        raise WeightRowMismatch("ROW_MALFORMED", "weights must be a list of ints in 0..65535")
    _, pinned_values = _pinned_lists(pinned)
    if not pinned_values:
        raise WeightRowMismatch("PINNED_ROW_EMPTY", "the pinned row is empty")
    if sorted(weights) != sorted(pinned_values):
        raise WeightRowMismatch("ROW_WEIGHTS_DIFFER",
                                f"row weights {weights}, pinned {pinned_values}")
    if not _is_int(total) or total != sum(pinned_values):
        raise WeightRowMismatch("ROW_SUM_DIFFERS",
                                f"recorded {total!r}, pinned {sum(pinned_values)}")
