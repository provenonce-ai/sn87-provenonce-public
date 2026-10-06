"""The one scoring-profile family: operative parameters come from the committed profile.

Each profile is a committed JSON document (``profiles/<id>.json``). Its commitment is pinned
here, so an edited file fails closed instead of silently changing a sealed run's meaning.
Every numeric scoring parameter is parsed from the document; the scoring functions have no
defaults. A value the code cannot apply (beta != 1, nonuniform difficulty or freshness,
activated cost coefficients, a utility or robustness function) is rejected, not ignored.
Decimal strings are parsed exactly and then mapped to the nearest binary64, the numeric
model the profiles themselves declare (``IEEE754_BINARY64_FINITE_FSUM``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sn87_provenonce.canonical import CANONICALIZER_ID, canonical_bytes, object_commitment

# profile_id -> (class_id, commitment domain, pinned commitment of the committed document)
REGISTRY = {
    "GRA-W03-3": (
        "TYPE-C-RELEASE",
        "SN87:SCORING_PROFILE:gra/0.1",
        "sha256:e732ea977497a6ccd5e9541c8fd98bc949086ade5cbeccb058a38312329eda21",
    ),
    "IC-FIRST-LIGHT-MIN-1": (
        "IC-APPROVAL-APPLICABILITY",
        "SN87:SCORING_PROFILE:institution/0.2",
        "sha256:7049f165bc9b4fae32133f2d37aa9a48f5bf13f3b4fa47ea94643e5633d3c766",
    ),
}
# Whitepaper equations defined but not applied by any committed profile.
INACTIVE = ("eq2_rule_score", "eq8_utility", "eq10_robustness")  # Eq.11: neutral eta, see scoring
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


class ProfileNotApplied(ValueError):
    """An operative value is missing, unparsed, unsupported or mismatched."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"PROFILE_NOT_APPLIED: {detail}")


def _number(document: dict[str, Any], *path: str) -> float:
    value: Any = document
    try:
        for key in path:
            value = value[key]
    except (KeyError, TypeError):
        raise ProfileNotApplied("missing " + ".".join(path)) from None
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise ProfileNotApplied("unparsed " + ".".join(path))
    return float(Decimal(value))


def _require(document: dict[str, Any], key: str, expected: Any) -> None:
    if document.get(key) != expected:
        raise ProfileNotApplied(f"unsupported {key}={document.get(key)!r}")


@dataclass(frozen=True)
class Profile:
    profile_id: str
    class_id: str
    commitment: str
    document: dict[str, Any] = field(repr=False, compare=False)
    weights: dict[str, float]
    epsilon: float
    theta: float
    gamma: float
    tail: float
    minimum: int
    invalid_ceiling: float
    severity: dict[str, float]
    false_positive_floor: float
    coefficients: tuple[str, ...]
    canonicalizer_id: str = CANONICALIZER_ID

    def truth_fields(self) -> dict[str, Any]:
        """The ``rule_reliability`` and ``deterministic`` values a truth record echoes.

        Both are copied verbatim from the bound, committed profile document, so a truth
        record cannot drift from its profile. No scorer reads them (issues #57, #58, #71).
        """
        rel, det = self.document.get("rule_reliability"), self.document.get("deterministic")
        if type(rel) is not str or _DECIMAL.fullmatch(rel) is None:
            raise ProfileNotApplied("unparsed reliability field")
        if type(det) is not bool:
            raise ProfileNotApplied("unsupported determinism field")
        return {"rule_reliability": rel, "deterministic": det}

    @classmethod
    def from_document(cls, document: dict[str, Any], *, class_id: str, domain: str) -> Profile:
        canonical_bytes(document)
        if document.get("cost_coefficients") != ["0", "0", "0", "0"]:
            raise ProfileNotApplied("COEFFICIENT_ACTIVATION_NOT_AUTHORIZED")
        for key, value in (("beta", "1"), ("difficulty", "1"), ("freshness", "1"),
                           ("utility", "NA_NO_DEFENSIBLE_FUNCTION"),
                           ("robustness", "DIAGNOSTIC_ONLY")):
            _require(document, key, value)
        minimum = document.get("minimum_assignments")
        if type(minimum) is not int or minimum < 1:
            raise ProfileNotApplied("minimum_assignments")
        dims = ("detection", "evidence", "calibration")
        if set(document.get("weights", {})) != set(dims):
            raise ProfileNotApplied("weights")
        return cls(
            profile_id=document["profile_id"],
            class_id=class_id,
            commitment=object_commitment(document, domain),
            document=document,
            weights={k: _number(document, "weights", k) for k in dims},
            epsilon=_number(document, "epsilon"),
            theta=_number(document, "theta"),
            gamma=_number(document, "gamma"),
            tail=_number(document, "tail_fraction"),
            minimum=minimum,
            invalid_ceiling=_number(document, "maximum_raw_invalid_or_missing_rate"),
            severity={k: _number(document, "severity", k) for k in ("LOW", "MEDIUM", "HIGH")},
            false_positive_floor=_number(document, "false_positive_floor"),
            coefficients=tuple(document["cost_coefficients"]),
        )


def load(profile_id: str) -> Profile:
    """Load a committed profile; fail closed if its bytes no longer match the pin."""
    if profile_id not in REGISTRY:
        raise ProfileNotApplied(f"unregistered profile {profile_id!r}")
    class_id, domain, pinned = REGISTRY[profile_id]
    path = Path(__file__).with_name("profiles") / f"{profile_id}.json"
    profile = Profile.from_document(json.loads(path.read_text("utf-8")),
                                    class_id=class_id, domain=domain)
    if profile.commitment != pinned or profile.profile_id != profile_id:
        raise ProfileNotApplied(f"{profile_id} document differs from its pinned commitment")
    return profile


def require_applied(profile: Profile, commitment: str) -> None:
    """A run bound to one profile commitment must be scored with exactly that profile."""
    if profile.commitment != commitment:
        raise ProfileNotApplied("run commitment differs from the scoring profile")
