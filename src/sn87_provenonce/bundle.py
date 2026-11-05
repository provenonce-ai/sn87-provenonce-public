"""One class-generic evaluation that emits the evidence bundle (``sn87-evidence-bundle/0.3``).

Docs cite the bundle and views render it; nothing else is a data source. The bundle
declares its mode before it speaks (FIXTURE, REPLAY or LIVE), carries the profile, class and
canonicalizer identities, keeps cost beside the scores, and marks every inactive or
unmeasured value "NA" rather than 0.
"""

from __future__ import annotations

import copy
import hashlib
import math
import time
from collections.abc import Iterable
from typing import Any

from sn87_provenonce.baselines import DEFINITION
from sn87_provenonce.baselines import METHOD_ID as BASELINE
from sn87_provenonce.canonical import canonical_bytes, object_commitment, parse_canonical
from sn87_provenonce.gate_registry import registered
from sn87_provenonce.miners import for_class as public_miners_for_class
from sn87_provenonce.profile import INACTIVE, REGISTRY, require_applied
from sn87_provenonce.scoring import (
    EFFICIENCY_STATUS,
    NA,
    ClassBinding,
    Integrity,
    epoch_estimate,
    preference_row,
    score_response,
    wire,
)

# 0.2 added the optional, FIXTURE-only `cases` section; 0.3 adds `manifest.profile_document` and
# `manifest.profile_commitment_domain` (the committed profile, so a reader verifies the gate
# values against `profile_commitment` instead of copying them). Every earlier field is unchanged.
# The optional `weight_gate` section (the baseline-headroom gate, below) is additive and is
# emitted only when asked for: adding it by default would change the bytes, and so the pinned
# digests, of every existing bundle.
SCHEMA = "sn87-evidence-bundle/0.3"
MODES = {"FIXTURE": "PUBLIC_FIXTURE", "REPLAY": "SEALED_RUN_REPLAY", "LIVE": "LIVE_NETWORK"}
DIMENSIONS = ("detection", "evidence", "calibration", "utility", "robustness")
COST_UNITS = {"wall_time": "ms", "cpu_time": "ms", "bytes_in": "bytes", "bytes_out": "bytes",
              "model_tokens": "tokens", "oracle_time": "ms"}
# Code unchanged since the First Light row was applied is labelled with that row; later modules
# whose arithmetic reproduces the First Light row on replay are labelled as equivalent, not as
# deployed.
FIRST_LIGHT = "FIRST_LIGHT_TESTNET_582_BLOCK_8102381"
EQUIVALENT = "REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381"

# Four columns: implemented (module:symbol or None), enabled by profile, tested (pytest node
# id or NOT_TESTED), deployed (evidence label or None). tests/test_bundle.py resolves every
# reference, so this matrix cannot drift from the code without failing CI. It is serialised into
# every bundle, so rows that cite tests or scripts of the private source repository name them as
# they are.
STATUS_MATRIX = [
    ("Eq.1 integrity gate", "sn87_provenonce.scoring:Integrity", True,
     "tests/test_scoring.py::test_every_integrity_failure_is_zero", EQUIVALENT),
    ("Eq.3-6 detection and binary evidence credit", "sn87_provenonce.scoring:score_response",
     True, "tests/test_scoring.py::test_duplicate_is_false_positive", EQUIVALENT),
    ("Eq.7 calibration", "sn87_provenonce.scoring:calibration", True,
     "tests/test_scoring.py::test_abstention_and_na_calibration", EQUIVALENT),
    ("Eq.12 composite (Eq.9 per-perturbation base: no separate code)",
     "sn87_provenonce.scoring:geometric", True,
     "tests/test_scoring.py::test_composite_is_na_when_empty", EQUIVALENT),
    ("Eq.13 epoch estimate", "sn87_provenonce.scoring:epoch_estimate", True,
     "tests/test_scoring.py::test_epoch_floor_ceiling_and_quantile", EQUIVALENT),
    ("Eq.14-15 preference row", "sn87_provenonce.scoring:preference_row", True,
     "tests/test_golden.py::test_first_light_row_reproduces", EQUIVALENT),
    ("Eq.2 rule score", None, False, "NOT_TESTED", None),
    ("Eq.8 utility", None, False, "NOT_TESTED", None),
    ("Eq.10 robustness", None, False, "NOT_TESTED", None),
    ("Eq.11 efficiency (neutral eta=1 only)", "sn87_provenonce.scoring:EFFICIENCY_STATUS",
     False, "tests/test_scoring.py::test_inactive_dimensions_are_na", None),
    ("Committed profile applied", "sn87_provenonce.profile:load", True,
     "tests/test_profile.py::test_profile_drives_result", None),
    ("Canonicalizer gra/0.1", "sn87_provenonce.canonical:canonical_bytes", True,
     "tests/test_gra_canonical.py::test_canonical_attacks_rejected", EQUIVALENT),
    ("Signed transport and replay protection", "sn87_provenonce.pilot.transport:verify_bytes",
     True, "tests/transport/test_signed_endpoint.py", FIRST_LIGHT),
    ("Chain target dry run", "scripts/pilot_chain_dry_run.py:dry_run", True,
     "tests/test_golden.py::test_first_light_row_reproduces", FIRST_LIGHT),
    ("Plain weight submission (approval-gated)",
     "scripts/pilot_chain_weights_institutional_v02.py:make_manifest", True,
     "tests/pilot/test_institutional_v02_scripts.py", FIRST_LIGHT),
    ("Commit-reveal submission", None, False, "NOT_TESTED", None),
    ("Matched public-contract baseline (reported, never weighted)",
     "sn87_provenonce.baselines:BASELINES", True,
     "tests/test_separation.py::test_baseline_matches_truth_and_null_result_is_kept", None),
    ("Truth/candidate separation (import graph)", "sn87_provenonce.baselines:METHOD_ID", True,
     "tests/test_separation.py::test_baseline_import_closure_excludes_evaluator_only", None),
    ("Truth/candidate separation (runtime: baseline code neither imports nor needs truth; "
     "no process isolation)", "sn87_provenonce.bundle:run_baseline", True,
     "tests/test_separation.py::test_baseline_runs_with_evaluator_only_modules_blocked", None),
    ("Cost record beside scores", "sn87_provenonce.bundle:cost_record", True,
     "tests/test_bundle.py::test_fixture_bundle_end_to_end", None),
]


def status_matrix() -> list[dict[str, Any]]:
    keys = ("item", "implemented", "enabled", "tested", "deployed")
    return [dict(zip(keys, row, strict=True)) for row in STATUS_MATRIX]


def status_markdown() -> str:
    """The status matrix as the table in docs/protocol/implementation-status.md."""
    def cell(v: Any) -> str:
        return "no" if v is None or v is False else "yes" if v is True else f"`{v}`"

    rows = ["| Item | Implemented | Enabled by profile | Tested | Deployed |",
            "|---|---|---|---|---|"]
    rows += ["| " + " | ".join([item, *map(cell, rest)]) + " |" for item, *rest in STATUS_MATRIX]
    return "\n".join(rows) + "\n"


def cost_record(measured: dict[str, tuple[float, str]],
                missing: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Six cost dimensions, each measured (value, source) or missing with a reason."""
    if set(measured) | set(missing) != set(COST_UNITS) or set(measured) & set(missing):
        raise ValueError("every cost dimension is measured or missing, exactly once")
    return {
        key: {"value": measured[key][0], "unit": unit, "source": measured[key][1],
              "missing": None} if key in measured
        else {"value": NA, "unit": unit, "source": None, "missing": missing[key]}
        for key, unit in COST_UNITS.items()
    }


def _sum_costs(records: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    total = {}
    for key, unit in COST_UNITS.items():
        cells = [r[key] for r in records]
        reasons = sorted({c["missing"] for c in cells if c["missing"]})
        sources = sorted({c["source"] for c in cells if c["source"]})
        total[key] = (
            {"value": NA, "unit": unit, "source": None,
             "missing": "; ".join(reasons) or "NO_ASSIGNMENTS", "n": len(cells)}
            if reasons or not cells else
            {"value": math.fsum(c["value"] for c in cells), "unit": unit,
             "source": "; ".join(sources), "missing": None, "n": len(cells)}
        )
    return total


def _dimension_means(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for key in DIMENSIONS:
        values = [r["dimensions"][key] for r in records if r["valid"]
                  and r["dimensions"].get(key, NA) != NA]
        out[key] = ({"value": math.fsum(values) / len(values), "n": len(values)} if values
                    else {"value": NA, "n": 0})
    return out


def _case_record(record: dict[str, Any], response: dict[str, Any] | None) -> dict[str, Any]:
    """One method's per-case values: exactly what Eqs. 3-7, 12 and 13 need, nothing more."""
    dimensions = record["dimensions"]
    return {
        "valid": record["valid"],
        "failures": record["failures"],
        "state": response["state"] if record["valid"] and response is not None else NA,
        "dimensions": {k: dimensions.get(k, NA) for k in DIMENSIONS},
        "precision": NA if record["precision"] is None else record["precision"],
        "recall": NA if record["recall"] is None else record["recall"],
        "fp_cost": record["fp_cost"],
        "score": record["score"],
    }


def run_baseline(binding: ClassBinding, cases: list[dict[str, Any]]
                 ) -> dict[str, dict[str, Any]]:
    """Run the matched baseline on the public capsule view only (a fresh canonical copy)."""
    observed = {}
    for case in cases:
        view = parse_canonical(canonical_bytes(case["capsule"]))
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        response = binding.baseline(view)
        wall, cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
        # The baseline runs in-process on a public copy: schema and policy are checked by
        # scoring; signature, nonce, evidence and deadline are not applicable (no exchange),
        # so they are asserted true here, exactly as for a FIXTURE run.
        observed[case["qid"]] = {
            "response": response, "integrity": Integrity(*[True] * 6),
            "cost": cost_record(
                {"wall_time": (wall / 1e6, "perf_counter_ns"),
                 "cpu_time": (cpu / 1e6, "process_time_ns"),
                 "bytes_in": (float(len(canonical_bytes(view))), "canonical_capsule_bytes"),
                 "bytes_out": (float(len(canonical_bytes(response))),
                               "canonical_response_bytes")},
                {"model_tokens": "NOT_APPLICABLE_DETERMINISTIC_METHOD",
                 "oracle_time": "NOT_APPLICABLE_BASELINE_USES_NO_ORACLE"}),
        }
    return observed


def _compare(estimate: float | None, baseline: float | None) -> dict[str, Any]:
    """Headroom against one method; a null result is kept, not hidden. The binding gate that
    uses it is ``candidate_gate``."""
    if estimate is None or baseline is None:
        return {"estimate_delta": NA, "result": NA}
    delta = estimate - baseline
    return {"estimate_delta": delta, "result": "NULL_NO_HEADROOM" if delta == 0
            else "ABOVE_BASELINE" if delta > 0 else "BELOW_BASELINE"}


# ------------------------------------------------------------ the baseline-headroom gate
# A family earns weight only if a candidate does better than every public method on the scored
# instances. The gate below is INTENDED to apply before any weighting. It is a check the
# weighting tools must call (``require_weight_eligible``); it is not wired into any live weight
# path in this repository, and nothing here sets a weight. Whether the instances are hidden
# from a miner is a property of the family (LIMITATIONS item 17), not of this gate.
GATE_SCHEMA = "sn87-weight-gate/0.1"
CEILING = 1.0  # the top of the score range ([0,1], ``scoring.bounded``)
# The smallest lead that counts as "above". Estimates are compared as the exact values of their
# .17g wire strings; a lead smaller than this margin is a tie (NULL_NO_HEADROOM), so rounding
# noise or a one-instance wobble in the last place can never open a family. 0.001 is the
# resolution of a 1,000-instance sample (the committed profiles score far fewer instances per
# method, so the margin is a floor, not a statistical test).
MIN_MARGIN = 0.001
ELIGIBLE = "ABOVE_ALL_PUBLIC_METHODS"
GATE_NULL = "NULL_NO_HEADROOM"        # a public method is within the margin: refuse
GATE_BELOW = "BELOW_PUBLIC_METHOD"    # a public method beats the candidate: refuse
GATE_NOT_COMPARABLE = "NOT_COMPARABLE"  # a needed estimate is missing or not a float: refuse
GATE_PUBLIC = "IS_PUBLIC_METHOD"       # a published method: anyone can run it, it earns nothing
GATE_REFERENCE = "IS_REFERENCE_METHOD"  # a Provenonce reference algorithm: not a competitor
RETIRE_RECOMMENDED = "RETIRE_RECOMMENDED"
FAMILY_ACTIVE = "ACTIVE"
GATE_NOTE = ("Intended to apply before any weighting: not wired into any live weight path. "
             "A family is weight-eligible only if a candidate beats every public method by at "
             f"least {MIN_MARGIN}; a tie refuses.")


class WeightGateRefused(ValueError):
    """The weight gate refuses: the method is not above every public method."""


def public_methods(class_id: str) -> tuple[str, ...]:
    """Every public method of a class: the matched baseline and each published miner method.

    Raises ``WeightGateRefused`` for a class that is not bound in ``classes.BINDINGS``: an
    unknown class has no known public methods, and "only the baseline" would let it pass.
    """
    from sn87_provenonce.classes import BINDINGS  # noqa: PLC0415 - classes does not import bundle

    if class_id not in BINDINGS:
        raise WeightGateRefused(f"WEIGHT_GATE_CLASS_NOT_BOUND: {class_id!r}")
    entry = registered(class_id)
    extra = set(entry.methods) if entry else set()
    return (BASELINE, *sorted({*public_miners_for_class(class_id), *extra} - {BASELINE}))


def _estimate_ok(value: Any) -> bool:
    """A finite float in [0,1]. An int (``1``) is not a float estimate: it is NOT_COMPARABLE."""
    return isinstance(value, float) and math.isfinite(value) and 0.0 <= value <= 1.0


def candidate_gate(estimates: dict[str, float | None], candidate: str,
                   public: Iterable[str], *, min_effect: float = 0.0) -> dict[str, Any]:
    """Does ``candidate`` beat EVERY public method (the baseline and ``approval_witness``
    included) on the scored instances? ``estimates`` maps method id to its Eq. 13 estimate
    (None when the sample floor or the failure ceiling was not met).

    Eligible only if the candidate's estimate exceeds each other public method's by at least
    ``MIN_MARGIN``. A lead inside the margin is ``NULL_NO_HEADROOM`` (a tie); a public method
    ahead by the margin is ``BELOW_PUBLIC_METHOD``; a missing or unusable estimate (None, NaN,
    out of range, or not a float: an int is unusable) is ``NOT_COMPARABLE``. A method that is
    itself public (the baseline, a published miner method) is ``IS_PUBLIC_METHOD``: it cannot be
    above itself, and anyone can copy it. Every verdict except ``ABOVE_ALL_PUBLIC_METHODS``
    refuses. ``min_effect`` is a family's preregistered minimum lead (``registered_gate``): a lead
    below ``max(MIN_MARGIN, min_effect)`` and above ``-MIN_MARGIN`` is a tie.
    """
    need = max(MIN_MARGIN, min_effect)
    rivals = sorted(set(public) - {candidate})
    mine = estimates.get(candidate)
    compared, blocking, missing = {}, [], []
    if not _estimate_ok(mine):
        missing.append(candidate)
    for method in rivals:
        theirs = estimates.get(method)
        if not _estimate_ok(theirs):
            missing.append(method)
            compared[method] = {"estimate_delta": NA, "result": NA}
        elif _estimate_ok(mine):
            delta = mine - theirs
            result = ("ABOVE_BASELINE" if delta >= need
                      else "BELOW_BASELINE" if delta <= -MIN_MARGIN else GATE_NULL)
            compared[method] = {"estimate_delta": delta, "result": result}
            if result != "ABOVE_BASELINE":
                blocking.append(method)
    if candidate in set(public):
        verdict = GATE_PUBLIC
    elif missing:
        verdict = GATE_NOT_COMPARABLE
    elif any(compared[m]["result"] == "BELOW_BASELINE" for m in rivals):
        verdict = GATE_BELOW
    elif blocking:
        verdict = GATE_NULL
    else:
        verdict = ELIGIBLE
    return {"method": candidate, "verdict": verdict, "weight_eligible": verdict == ELIGIBLE,
            "compared_with": rivals, "compared": compared,
            "blocked_by": sorted(set(blocking) | (set(missing) - {candidate})),
            "estimate_missing": sorted(missing)}


def registered_gate(estimates: dict[str, float | None], candidate: str,
                    class_id: str) -> dict[str, Any]:
    """``candidate_gate`` against the family's REGISTERED closed baseline list and minimum effect.

    The caller does not supply the public set. A family that has registered nothing, or an
    ``estimates`` map that lacks any registered method, is refused: omitting a method cannot make
    a candidate look better. Works for a class bound nowhere (an inactive family); weighting still
    goes through ``require_weight_eligible``, which refuses an unbound class.
    """
    entry = registered(class_id)
    if entry is None:
        raise WeightGateRefused(f"WEIGHT_GATE_FAMILY_NOT_REGISTERED: {class_id!r}")
    missing = [m for m in entry.methods if m not in estimates]
    if missing:
        raise WeightGateRefused(f"WEIGHT_GATE_REGISTERED_METHOD_MISSING: {missing}")
    return candidate_gate(estimates, candidate, entry.methods, min_effect=entry.min_effect)


def family_gate(estimates: dict[str, float | None], class_id: str,
                roles: dict[str, str]) -> dict[str, Any]:
    """The family-level gate for ``class_id``. ``roles`` maps each non-baseline method to its role.

    Only a method with role ``candidate`` is a subject; a ``reference`` method (a Provenonce
    algorithm that also computes truth) gets ``IS_REFERENCE_METHOD`` and any other role
    ``NOT_COMPARABLE``. The family is weight-eligible only if at least one subject is
    ``ABOVE_ALL_PUBLIC_METHODS``. A family whose public methods are all evaluated and all within
    ``MIN_MARGIN`` of the ceiling is marked ``RETIRE_RECOMMENDED``: nothing can lead them by the
    margin, so further weighting on it measures nothing.
    """
    public = public_methods(class_id)
    entry = registered(class_id)
    effect = entry.min_effect if entry else 0.0
    subject_gates = {}
    for method, role in roles.items():
        if role == "candidate":
            subject_gates[method] = candidate_gate(estimates, method, public, min_effect=effect)
        else:
            verdict = GATE_REFERENCE if role == "reference" else GATE_NOT_COMPARABLE
            subject_gates[method] = {"method": method, "verdict": verdict,
                                     "weight_eligible": False, "role": role}
    not_evaluated = sorted(m for m in public if m not in estimates)
    saturated = (not not_evaluated and all(
        _estimate_ok(estimates[m]) and estimates[m] >= CEILING - MIN_MARGIN for m in public))
    eligible = sorted(m for m, g in subject_gates.items() if g["weight_eligible"])
    return {
        "schema_version": GATE_SCHEMA, "class_id": class_id, "note": GATE_NOTE,
        "ceiling": CEILING, "min_margin": MIN_MARGIN, "public_methods": list(public),
        "public_methods_not_evaluated": not_evaluated,
        "family": {"weight_eligible": bool(eligible) and not saturated,
                   "eligible_methods": [] if saturated else eligible,
                   "status": RETIRE_RECOMMENDED if saturated else FAMILY_ACTIVE},
        "methods": subject_gates,
    }


def _wire_estimate(cell: Any) -> float | None:
    value = cell.get("estimate") if isinstance(cell, dict) else None
    try:
        return None if value in (None, NA) else float(value)
    except (TypeError, ValueError):
        return None


def bundle_gate(bundle: dict[str, Any]) -> dict[str, Any]:
    """The gate computed from a finished bundle's own scores (``scores[method].estimate``).

    Works on any bundle, with or without the optional ``weight_gate`` section, so a weighting
    tool never has to trust an embedded verdict. Before the scores are trusted it checks what a
    bundle alone can show: the schema, a class bound in ``classes.BINDINGS``, the profile
    identity and commitment against the bound profile (and the carried profile document against
    its commitment), the baseline entry, and that ``scores`` and ``methods`` name the same
    methods. It cannot recompute the scores (that needs the cases and truth); a bundle from an
    untrusted source is still only as good as its source, as with any bundle.
    """
    from sn87_provenonce.classes import BINDINGS  # noqa: PLC0415

    def refuse(code: str) -> WeightGateRefused:
        return WeightGateRefused(f"WEIGHT_GATE_BUNDLE_{code}")

    try:
        manifest, methods, scores = bundle["manifest"], bundle["methods"], bundle["scores"]
        class_id = manifest["class_id"]
        roles = {m["method_id"]: m["role"] for m in methods}
        if bundle.get("schema_version") != SCHEMA:
            raise refuse("SCHEMA_UNKNOWN")
        if class_id not in BINDINGS:
            raise WeightGateRefused(f"WEIGHT_GATE_CLASS_NOT_BOUND: {class_id!r}")
        profile = BINDINGS[class_id].profile
        if (manifest["profile_id"] != profile.profile_id
                or manifest["profile_commitment"] != profile.commitment
                or manifest["profile_applied"] is not True):
            raise refuse("PROFILE_NOT_THE_BOUND_PROFILE")
        domain = REGISTRY[profile.profile_id][1]
        if (manifest["profile_commitment_domain"] != domain
                or object_commitment(manifest["profile_document"], domain) != profile.commitment):
            raise refuse("PROFILE_COMMITMENT_DOES_NOT_MATCH")
        if roles.get(BASELINE) != "baseline" or set(roles) != set(scores):
            raise refuse("METHODS_DO_NOT_MATCH_SCORES")
        estimates = {m: _wire_estimate(cell) for m, cell in scores.items()}
        subjects = {m: r for m, r in roles.items() if r != "baseline"}
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        if isinstance(error, WeightGateRefused):
            raise
        raise refuse("MALFORMED") from None
    return family_gate(estimates, class_id, subjects)


def require_weight_eligible(bundle: Any, method: str) -> None:
    """The check every weighting tool must call before it gives ``method`` any weight.

    Takes an evidence bundle only, never a bare gate dict: the gate is recomputed here from the
    bundle's scores (``bundle_gate``), and an embedded ``weight_gate`` section that differs from
    the recomputation refuses. Raises ``WeightGateRefused`` unless the family is weight-eligible
    and ``method`` is ``ABOVE_ALL_PUBLIC_METHODS``. Anything missing or malformed refuses.
    """
    if not (isinstance(bundle, dict) and "scores" in bundle):
        raise WeightGateRefused("WEIGHT_GATE_NEEDS_A_BUNDLE")
    gate = bundle_gate(bundle)
    if "weight_gate" in bundle and bundle["weight_gate"] != wire(gate):
        raise WeightGateRefused("WEIGHT_GATE_SECTION_DIFFERS_FROM_SCORES")
    try:
        verdict, status = gate["methods"][method]["verdict"], gate["family"]["status"]
    except KeyError:
        raise WeightGateRefused("WEIGHT_GATE_METHOD_NOT_A_SUBJECT") from None
    if not (gate["family"]["weight_eligible"] is True and status != RETIRE_RECOMMENDED
            and verdict == ELIGIBLE and gate["methods"][method]["weight_eligible"] is True):
        raise WeightGateRefused(f"WEIGHT_GATE_REFUSES: {verdict} (family status {status})")


def evaluate(
    binding: ClassBinding,
    cases: Iterable[dict[str, Any]],
    observations: dict[str, dict[str, dict[str, Any]]],
    *,
    mode: str,
    run_id: str,
    profile_commitment: str,
    window: dict[str, str],
    source_digest: str,
    uids: dict[str, int] | None = None,
    chain_dry_run: dict[str, Any] | None = None,
    per_case: bool = False,
    weight_gate: bool = False,
) -> dict[str, Any]:
    """Score every assigned observation with the bound profile and emit one bundle.

    ``weight_gate=True`` adds the optional ``weight_gate`` section (see ``family_gate``). It is
    off by default so that every existing bundle keeps its bytes and its pinned digest.

    ``observations[method][qid]`` holds ``response`` (or None), ``integrity`` and ``cost``.
    Missing observations stay in the sample as zero; nothing is dropped or retried.
    """
    if mode not in MODES:
        raise ValueError("mode must be FIXTURE, REPLAY or LIVE")
    require_applied(binding.profile, profile_commitment)
    cases = list(cases)
    if set(observations) != set(binding.candidates) or BASELINE in binding.candidates:
        raise ValueError("observations must cover exactly the bound candidates")
    observations = observations | {BASELINE: run_baseline(binding, cases)}
    absent = {"response": None, "integrity": Integrity(*[False] * 6),
              "cost": cost_record({}, dict.fromkeys(COST_UNITS, "NOT_OBSERVED"))}
    scores, diagnostics, costs, estimates = {}, {}, {}, {}
    # Under a profile with the redundancy rule (ADR-0022) the preference row needs every
    # candidate's scored answers, so identities that answer alike share one weight.
    answers: dict[str, dict[str, Any]] = {}
    # Per-case records are opt-in and only for FIXTURE bundles whose caller has established
    # synthetic provenance (the public generator, or a verified-FICTIONAL source). Sealed
    # REPLAY/LIVE per-case data stays private until Provenonce decides otherwise.
    if per_case and mode != "FIXTURE":
        raise ValueError("PER_CASE_RECORDS_ARE_FIXTURE_ONLY")
    case_records: list[dict[str, Any]] = [
        {"qid": c["qid"], "track": c["track"], "family": c.get("family", NA), "methods": {}}
        for c in cases] if per_case else []
    for method in [*binding.candidates, BASELINE]:
        scored, diagnostic, method_costs = [], [], []
        for index, case in enumerate(cases):
            seen = observations[method].get(case["qid"], absent)
            record = score_response(binding, case["capsule"], case["truth"],
                                    seen["response"], seen["integrity"])
            if per_case:
                case_records[index]["methods"][method] = _case_record(record, seen["response"])
            method_costs.append(seen["cost"])
            if case["track"] == "scored" and method != BASELINE:
                # A reply the contract rejects scores zero and never groups (ADR-0022).
                answers.setdefault(method, {})[case["qid"]] = (
                    None if "schema" in record["failures"] else seen["response"])
            if case["track"] == "scored":
                scored.append(record)
            else:
                diagnostic.append(record["valid"] and seen["response"]["state"]
                                  == "INSUFFICIENT_EVIDENCE_ABSTAIN")
        estimate = epoch_estimate([r["score"] for r in scored], [r["valid"] for r in scored],
                                  binding.profile)
        estimates[method] = estimate["estimate"]
        scores[method] = {
            "admitted": len(scored),
            "evaluable": sum(r["valid"] for r in scored),
            "estimate": NA if estimate["estimate"] is None else estimate["estimate"],
            "eligible": estimate["eligible"],
            "reason": estimate["reason"],
            "lower": estimate.get("lower", NA),
            "upper": estimate.get("upper", NA),
            "raw_invalid_or_missing_rate": NA if estimate["raw_invalid_or_missing_rate"] is None
            else estimate["raw_invalid_or_missing_rate"],
            "dimensions": _dimension_means(scored),
        }
        diagnostics[method] = {"assigned": len(diagnostic),
                               "correct_abstentions": sum(diagnostic), "contest_weight": "0"}
        costs[method] = _sum_costs(method_costs)
    baseline_estimate = estimates.pop(BASELINE)  # never a chain participant
    row = preference_row(
        estimates, binding.profile,
        answers={m: answers.get(m, {}) for m in estimates}
        if binding.profile.fixed_outcome is not None else None)
    profile = binding.profile
    # `Profile` is frozen but its `document` dict is mutable: recompute the commitment from the
    # exact document about to be emitted, so a bundle never carries a differing profile.
    domain = REGISTRY[profile.profile_id][1]
    if object_commitment(profile.document, domain) != profile.commitment:
        raise ValueError("PROFILE_DOCUMENT_DIFFERS_FROM_COMMITMENT")
    bundle = wire({
        "schema_version": SCHEMA,
        "mode": mode,
        "claim": "CONFORMANCE_ONLY",
        "manifest": {
            "run_id": run_id,
            "class_id": binding.class_id,
            "profile_id": profile.profile_id,
            "profile_commitment": profile.commitment,
            # The committed document itself: sha256(domain 0x00 LP(canonical(document))) must
            # equal profile_commitment, so the Eq. 13-15 values a reader takes from it are bound.
            "profile_commitment_domain": domain,
            "profile_document": copy.deepcopy(profile.document),
            "profile_applied": True,
            "canonicalizer_id": profile.canonicalizer_id,
            "window": window,
            "source": {"kind": MODES[mode], "digest": source_digest},
            "common_control": True,
        },
        "methods": [{"method_id": m, "role": binding.role_of(m), "uid": (uids or {}).get(m)}
                    for m in binding.candidates]
        + [{"method_id": BASELINE, "role": "baseline", "uid": None}],
        "baseline": {"state": "CONFIGURED", "method_id": BASELINE,
                     "definition": DEFINITION[binding.class_id], "public_contract_only": True},
        "comparison": {m: _compare(e, baseline_estimate) for m, e in estimates.items()},
        "scores": scores,
        "inactive": dict.fromkeys(INACTIVE, NA),
        "efficiency": {"status": EFFICIENCY_STATUS, "eta": 1.0,
                       "coefficients": list(profile.coefficients)},
        "diagnostics": diagnostics,
        "row": {"state": row["state"], "weights": row["weights"], "z": row["z"]},
        "chain_dry_run": chain_dry_run,
        "chain_applied": None,
        "cost": costs,
        "status_matrix": status_matrix(),
    } | ({"cases": case_records} if per_case else {})
      | ({"weight_gate": family_gate(
            estimates | {BASELINE: baseline_estimate}, binding.class_id,
            {m: binding.role_of(m) for m in estimates})} if weight_gate else {}))
    canonical_bytes(bundle, max_bytes=4 * 1024 * 1024)
    return bundle


def sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value, max_bytes=64 * 1024 * 1024)
                                      ).hexdigest()


def observe(binding: ClassBinding, cases: list[dict[str, Any]], oracle_ns: list[int]
            ) -> dict[str, dict[str, dict[str, Any]]]:
    """Run every bound method in-process on the cases and measure it (integrity asserted)."""
    observations: dict[str, dict[str, dict[str, Any]]] = {}
    for method, candidate in binding.candidates.items():
        pure = binding.role_of(method) == "candidate"  # a candidate never touches the oracle
        observations[method] = {}
        for case, oracle in zip(cases, oracle_ns, strict=True):
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            integrity, raised = Integrity(*[True] * 6), False
            try:
                response = candidate(case["capsule"])
            except Exception:  # noqa: BLE001 - a miner-owned method's failure is its own zero
                if not pure:
                    raise  # reference failures are ours: fail loudly, never score them
                response, raised = None, True
            if response is None and not pure:
                raise ValueError("REFERENCE_METHOD_RETURNED_NONE")  # ours: fail loudly
            if response is None:
                integrity = Integrity(False, True, True, True, True, True)
            wall, cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
            measured = {"wall_time": (wall / 1e6, "perf_counter_ns"),
                        "cpu_time": (cpu / 1e6, "process_time_ns"),
                        "bytes_in": (float(len(canonical_bytes(case["capsule"]))),
                                     "canonical_capsule_bytes")}
            if response is not None:
                measured["bytes_out"] = (float(len(canonical_bytes(response))),
                                         "canonical_response_bytes")
            missing = {"model_tokens": "NOT_APPLICABLE_DETERMINISTIC_METHOD"}
            if response is None:
                missing["bytes_out"] = ("NO_RESPONSE_METHOD_RAISED" if raised
                                        else "NO_RESPONSE_METHOD_RETURNED_NONE")
            if pure:
                missing["oracle_time"] = "NOT_APPLICABLE_CANDIDATE_USES_NO_ORACLE"
            else:
                measured["oracle_time"] = (oracle / 1e6, "perf_counter_ns_reference")
            observations[method][case["qid"]] = {
                "response": response, "integrity": integrity,
                "cost": cost_record(measured, missing)}
    return observations


def fixture_run(binding: ClassBinding, *, at: str = "2026-09-28T00:00:00Z") -> dict[str, Any]:
    """A FIXTURE dry run: the profile's full assignment, public generator, local candidates.

    Integrity is asserted, not proven (no network exchange), which is why the mode is
    FIXTURE. Wall and CPU time, bytes in and out, and reference (oracle) time are measured
    on this machine; model tokens are not applicable to deterministic methods.
    """
    document = binding.profile.document
    plan = [(family, "scored") for family, count in document["assignment"].items()
            for _ in range(count)]
    plan += [(family, "diagnostic") for family, count in document["diagnostics"].items()
             for _ in range(count)]
    cases, oracle_ns = [], []
    for index, (family, track) in enumerate(plan):
        capsule = binding.generate(family, index)
        started = time.perf_counter_ns()
        truth = binding.reference(capsule)
        oracle_ns.append(time.perf_counter_ns() - started)
        cases.append({"qid": capsule["qid"], "track": track, "family": family,
                      "capsule": capsule, "truth": truth})
    observations = observe(binding, cases, oracle_ns)
    return evaluate(
        binding, cases, observations, mode="FIXTURE",
        run_id=f"fixture-{binding.class_id.lower()}", profile_commitment=binding.profile.commitment,
        window={"opened_at": at, "closed_at": at},
        source_digest=sha256([c["capsule"]["evidence_commitment"] for c in cases]),
        per_case=True,  # the public synthetic generator: provenance established
    )
