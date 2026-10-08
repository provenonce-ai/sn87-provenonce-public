"""The one SN87 scorer: whitepaper v0.7.2 Eqs. 1, 3-7, 12, 13 and 14-15.

Every parameter comes from the bound class's committed profile; there are no defaults.
Eq. 2 (rule score), Eq. 8 (utility) and Eq. 10 (robustness) are defined in the paper but
inactive in every committed profile: their dimensions serialize as "NA", never 0. Eq. 11
keeps its neutral factor eta = 1 in the arithmetic, because every committed cost
coefficient is "0"; its status is reported as INACTIVE and no cost is invented. Measured
cost travels beside the score in the evidence bundle, never inside it.

Wire rule: ``wire`` is the one emitter. Every float leaves as ``format(x, ".17g")``, the
17-significant-digit round-trip of the binary64 value (not exact decimal arithmetic). It is
chosen because the chain dry run quantizes the Decimal reading and cross-checks it against
the SDK's float path: a lossless binary64 string makes both readings the same number.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from sn87_provenonce.profile import Profile

NA = "NA"
EFFICIENCY_STATUS = "INACTIVE_ZERO_COEFFICIENTS"


def wire(value: Any) -> Any:
    """Report-boundary encoding: floats become .17g decimal strings, nothing else changes."""
    if isinstance(value, float):
        return format(bounded_finite(value), ".17g")
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [wire(v) for v in value]
    return value


def bounded_finite(x: float) -> float:
    if not math.isfinite(x):
        raise ValueError("finite value required")
    return x


def bounded(x: float) -> float:
    if not math.isfinite(x) or not 0 <= x <= 1:
        raise ValueError("score must be finite in [0,1]")
    return x


@dataclass(frozen=True)
class Integrity:
    """Eq. 1 predicates, supplied by verified transport, never by a miner."""

    schema: bool
    policy: bool
    signature: bool
    nonce: bool
    evidence: bool
    deadline: bool

    @property
    def gate(self) -> int:
        if any(type(x) is not bool for x in asdict(self).values()):
            raise ValueError("integrity predicates must be booleans")
        return int(all(asdict(self).values()))


@dataclass(frozen=True)
class ClassBinding:
    """Everything a task class contributes; the scorer and pipeline stay generic."""

    class_id: str
    profile: Profile
    schema: str
    validate_capsule: Callable[[dict[str, Any]], None]
    validate_differential: Callable[[dict[str, Any], dict[str, Any]], None]
    defect_severity: dict[str, str]
    reference: Callable[[dict[str, Any]], dict[str, Any]]
    candidates: dict[str, Callable[[dict[str, Any]], dict[str, Any]]]
    generate: Callable[[str], dict[str, Any]]
    baseline: Callable[[dict[str, Any]], dict[str, Any]]
    # "reference": the method also computes truth (common control); "candidate": proven to
    # see only the public contract. ``role`` is the default; ``roles`` overrides per method.
    role: str = "reference"
    roles: dict[str, str] = field(default_factory=dict)

    def role_of(self, method: str) -> str:
        return self.roles.get(method, self.role)


def calibration(claims: list[tuple[float, int]]) -> float | None:
    """Eq. 7; absent confidence claims are not applicable."""
    if not claims:
        return None
    for p, y in claims:
        bounded(p)
        if y not in (0, 1):
            raise ValueError("binary outcome required")
    return bounded(1 - math.fsum((p - y) ** 2 for p, y in claims) / len(claims))


def geometric(
    dimensions: dict[str, float | None], weights: dict[str, float], epsilon: float
) -> float | None:
    """Eq. 12 over grounded applicable dimensions only; empty is NA, never one.

    Eq. 9 (per-perturbation base score) has no separate code; it is not on the weight path.
    """
    if not 0 < epsilon < 1 or any(not math.isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("invalid composite profile")
    active = [
        (bounded(value), weights.get(key, 0.0))
        for key, value in dimensions.items()
        if value is not None and weights.get(key, 0.0) > 0
    ]
    total = math.fsum(weight for _, weight in active)
    if not total:
        return None
    return bounded(
        math.exp(math.fsum(w / total * math.log(max(v, epsilon)) for v, w in active))
    )


def evidence_credit(profile: Profile, required: list[str], cited: list[str]) -> float:
    """Evidence quality of one matched finding.

    A profile without ``scoring_rules`` gets the original binary credit: 1 when
    every required reference is cited, whatever else is cited. Under ``PRECISION_TIMES_RECALL``
    it is (|cited & required| / |cited|) * (|cited & required| / |required|), so surplus
    references lower it and citing every event no longer matches citing exactly the witness.
    """
    needed, seen = set(required), set(cited)
    if profile.evidence_credit is None or not needed:  # nothing required: credit 1, as before
        return float(needed <= seen)
    hits = len(needed & seen)
    return hits * hits / (len(seen) * len(needed)) if hits else 0.0


def state_payoff_score(profile: Profile, truth_state: str, response_state: str,
                       composite: float) -> tuple[float, dict[str, Any]]:
    """Score under the 3 x 3 state-by-truth payoff matrix (ADR-0019).

    The cell caps the score. Only a correct FINDINGS response carries per-finding quality (the
    existing composite of detection, evidence and calibration); every other cell is the cell
    value, so a confidence claim cannot lift a wrong answer above a correct abstention. Valid
    responses keep the profile's epsilon floor, as before.
    """
    assert profile.state_payoff is not None
    try:
        cell = profile.state_payoff[truth_state][response_state]
    except KeyError:
        raise ValueError("unknown truth or response state") from None
    quality = composite if truth_state == response_state == "FINDINGS" else 1.0
    return bounded(max(cell * quality, profile.epsilon)), {
        "truth": truth_state, "response": response_state, "cell": cell, "quality": quality}


def score_response(
    binding: ClassBinding,
    capsule: dict[str, Any],
    truth: dict[str, Any],
    response: dict[str, Any] | None,
    integrity: Integrity,
) -> dict[str, Any]:
    """Eqs. 1, 3-7, 12 for one assigned response."""
    profile = binding.profile
    failures = [key for key, value in asdict(integrity).items() if not value]
    if response is None:
        failures.append("missing")
    else:
        try:
            binding.validate_differential(capsule, response)
        except (ValueError, TypeError, KeyError, RecursionError):
            failures.append("schema")
    if not integrity.gate or failures:
        return {"score": 0.0, "valid": False, "failures": sorted(set(failures)),
                "dimensions": {}, "precision": None, "recall": None, "fp_cost": 0.0,
                "matched": [], "unmatched": []}
    assert response is not None
    severity = profile.severity
    targets = {t["code"]: t for t in truth["defects"]}
    if len(targets) != len(truth["defects"]):
        raise ValueError("duplicate hidden truth code")
    matched, unmatched, confidences, evidence, tp_weights, fp_costs = [], [], [], [], [], []
    for index, finding in enumerate(response["findings"]):
        code = finding["code"]
        target = targets.get(code)
        is_match = target is not None and code not in matched
        if is_match:
            matched.append(code)
            weight = severity[target["severity"]]
            tp_weights.append(weight)
            evidence.append((weight, evidence_credit(
                profile, target["required_refs"], finding["evidence_refs"])))
        else:
            unmatched.append(index)
            sealed = binding.defect_severity.get(code, "HIGH")
            fp_costs.append(max(profile.false_positive_floor, severity[finding["severity"]],
                                severity[sealed]))
        if "confidence" in finding:
            confidences.append((float(finding["confidence"]), int(is_match)))
    tp, fp = math.fsum(tp_weights), math.fsum(fp_costs)
    precision = tp / (tp + fp) if matched or unmatched else 1.0
    total = math.fsum(severity[t["severity"]] for t in targets.values())
    recall = tp / total if total else None
    if response["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN":
        detection = 0.0
    elif total:
        detection = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    elif response["state"] == "NO_MATERIAL_DEVIATION":
        detection = 1.0
    else:
        detection = max(0.0, 1 - fp)
    # Incomplete capsules belong only to diagnostics. No quality credit is invented.
    if truth["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN":
        detection = 0.0
    dimensions = {
        "detection": detection,
        "evidence": math.fsum(w * q for w, q in evidence) / tp if tp else None,
        "calibration": calibration(confidences),
        "utility": None,
        "robustness": None,
    }
    composite = geometric(dimensions, profile.weights, profile.epsilon)
    eta = 1.0  # Eq. 11 with all committed coefficients "0" (enforced by the profile).
    score = 0.0 if composite is None else bounded(composite * eta)
    payoff = None
    if profile.state_payoff is not None:  # ADR-0019 rules, off when absent
        score, payoff = state_payoff_score(profile, truth["state"], response["state"], score)
    result = {
        "score": score,
        "valid": True,
        "failures": [],
        "dimensions": {k: NA if v is None else v for k, v in dimensions.items()},
        "precision": precision,
        "recall": recall,
        "fp_cost": fp,
        "matched": matched,
        "unmatched": unmatched,
        "eta": eta,
        "efficiency": EFFICIENCY_STATUS,
        "cost_coefficients": list(profile.coefficients),
        "rule_score": NA,
    }
    if payoff is not None:
        result["payoff"] = payoff
    return result


def epoch_estimate(scores: list[float], valid: list[bool], profile: Profile) -> dict[str, Any]:
    """Eq. 13 with uniform difficulty and freshness (the only values a profile may bind).

    Every assigned response stays in the sample; invalid or missing ones count as zero.
    """
    n = len(scores)
    if len(valid) != n or any(type(v) is not bool for v in valid):
        raise ValueError("assignment validity mismatch")
    tail, minimum, ceiling = profile.tail, profile.minimum, bounded(profile.invalid_ceiling)
    if not 0 <= tail < 0.5:
        raise ValueError("invalid estimator profile")
    rate = (n - sum(valid)) / n if n else None
    reason = ("EMPTY_ASSIGNMENT" if not n else "SAMPLE_FLOOR" if n < minimum
              else "RAW_FAILURE_CEILING" if rate > ceiling else None)
    if reason:
        return {"estimate": None, "eligible": False, "reason": reason, "assigned": n,
                "raw_invalid_or_missing_rate": rate}
    ordered = sorted(bounded(s) if ok else 0.0 for s, ok in zip(scores, valid, strict=True))

    def quantile(fraction: float) -> float:
        for index, score in enumerate(ordered, 1):
            if index / n >= fraction:
                return score
        return ordered[-1]

    lower = ordered[0] if not tail else quantile(tail)
    upper = ordered[-1] if not tail else quantile(1 - tail)
    estimate = math.fsum(min(upper, max(lower, s)) for s in ordered) / n
    return {"estimate": bounded(estimate), "eligible": True, "reason": None, "assigned": n,
            "raw_invalid_or_missing_rate": rate, "lower": lower, "upper": upper}


def preference_row(estimates: dict[str, float | None], profile: Profile) -> dict[str, Any]:
    """Eqs. 14-15. Weights leave as wire strings; no valid row is an explicit state."""
    theta, gamma = profile.theta, profile.gamma
    if not 0 <= theta < 1 or not math.isfinite(gamma) or gamma <= 0:
        raise ValueError("invalid threshold/sharpness")
    z = {
        identity: max(bounded(score) - theta, 0) ** gamma if score is not None else 0.0
        for identity, score in estimates.items()
    }
    total = math.fsum(z.values())
    if total == 0:
        return {"state": "NO_VALID_PREFERENCE_ROW", "weights": None, "z": z,
                "action": "DO_NOT_SUBMIT"}
    return {"state": "VALID_PREFERENCE_ROW",
            "weights": {k: wire(v / total) for k, v in z.items()}, "z": z,
            "action": "REQUIRES_TARGET_CONFORMANCE_AND_H1"}
