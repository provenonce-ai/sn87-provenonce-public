"""Deterministic, transparent Lane One architecture simulation.

This module is deliberately outside the protocol namespace. Its fixtures and scoring
constants are public toy inputs for exercising system seams; they are not benchmark
truth, calibrated incentives, or proposed chain weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sn87_provenonce.protocol.v0alpha1 import (
    AssuranceFinding,
    AssuranceResponse,
    EvidenceReference,
    OracleClass,
    ResponseState,
    canonical_sha256,
)

SIMULATION_VERSION = "lane-one-transparent-toy/0alpha1"
REPORT_COMMITMENT_DOMAIN = "SN87:LANE_ONE_TRANSPARENT_TOY_REPORT:v0alpha1"
NO_VALID_WEIGHT_ROW = "NO_VALID_WEIGHT_ROW"
WEIGHT_SCALE = 1_000_000


@dataclass(frozen=True)
class ToyCase:
    case_id: str
    case_class: str
    visible_facts: dict[str, Any]
    expected_state: ResponseState

    @property
    def evidence_commitment(self) -> str:
        return canonical_sha256(
            self.visible_facts,
            domain="SN87:TRANSPARENT_TOY_EVIDENCE:v0alpha1",
        )


@dataclass(frozen=True)
class SimulatedAnswer:
    response: AssuranceResponse
    declared_confidence_bps: int


CASES = (
    ToyCase(
        case_id="toy-a-planted-defect",
        case_class="TYPE_A_PLANTED_DEFECT",
        visible_facts={"approval_evidence_present": True, "review_gate_present": False},
        expected_state=ResponseState.FINDINGS,
    ),
    ToyCase(
        case_id="toy-a-clean-control",
        case_class="TYPE_A_CLEAN_CONTROL",
        visible_facts={"approval_evidence_present": True, "review_gate_present": True},
        expected_state=ResponseState.NO_MATERIAL_DEVIATION,
    ),
    ToyCase(
        case_id="toy-a-equivalent-mutation",
        case_class="TYPE_A_EQUIVALENT_MUTATION",
        visible_facts={
            "approval_evidence_present": True,
            "audit_log_order": "reordered",
            "review_gate_present": False,
        },
        expected_state=ResponseState.FINDINGS,
    ),
    ToyCase(
        case_id="toy-a-insufficient-evidence",
        case_class="TYPE_A_INSUFFICIENT_EVIDENCE",
        visible_facts={"approval_evidence_present": False, "review_gate_present": None},
        expected_state=ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN,
    ),
)


def _finding(case: ToyCase, confidence_bps: int) -> AssuranceFinding:
    return AssuranceFinding(
        finding_id=f"finding-{case.case_id}",
        challenge_id=case.case_id,
        finding_type="MISSING_REVIEW_GATE",
        claim="The declared review gate is absent from the supplied toy Evidence.",
        severity=0.8,
        confidence=confidence_bps / 10_000,
        oracle_class=OracleClass.A,
        evidence=(
            EvidenceReference(
                commitment=case.evidence_commitment,
                predicate="review_gate_present=false",
            ),
        ),
        recommended_action="Restore the review gate before treating the toy run as conformant.",
    )


def _answer(case: ToyCase, state: ResponseState, confidence_bps: int) -> SimulatedAnswer:
    findings = (_finding(case, confidence_bps),) if state is ResponseState.FINDINGS else None
    evidence_requests = (
        ("approval_event",) if state is ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN else None
    )
    response = AssuranceResponse(
        challenge_id=case.case_id,
        response_state=state,
        rationale=f"Transparent toy response for {case.case_id}; no external assertion is made.",
        findings=findings,
        evidence_requests=evidence_requests,
    )
    return SimulatedAnswer(response=response, declared_confidence_bps=confidence_bps)


def _miner_answer(miner_id: str, case: ToyCase) -> SimulatedAnswer:
    facts = case.visible_facts
    if miner_id == "evidence_first":
        if not facts["approval_evidence_present"]:
            return _answer(case, ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN, 9000)
        if facts["review_gate_present"] is False:
            return _answer(case, ResponseState.FINDINGS, 9200)
        return _answer(case, ResponseState.NO_MATERIAL_DEVIATION, 9000)

    if miner_id == "noisy":
        if case.case_class == "TYPE_A_EQUIVALENT_MUTATION":
            return _answer(case, ResponseState.NO_MATERIAL_DEVIATION, 6500)
        if case.case_class == "TYPE_A_CLEAN_CONTROL":
            return _answer(case, ResponseState.FINDINGS, 7200)
        if not facts["approval_evidence_present"]:
            return _answer(case, ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN, 7600)
        return _answer(case, ResponseState.FINDINGS, 8400)

    if miner_id == "alarmist":
        return _answer(case, ResponseState.FINDINGS, 9800)

    if miner_id == "abstainer":
        return _answer(case, ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN, 9000)

    raise ValueError(f"unknown simulated miner: {miner_id}")


def _evidence_supported(case: ToyCase, answer: SimulatedAnswer) -> bool:
    if answer.response.response_state is not ResponseState.FINDINGS:
        return answer.response.response_state is case.expected_state
    return (
        case.expected_state is ResponseState.FINDINGS
        and case.visible_facts["review_gate_present"] is False
        and answer.response.findings is not None
        and answer.response.findings[0].evidence[0].commitment == case.evidence_commitment
    )


def _score_case(case: ToyCase, answer: SimulatedAnswer) -> dict[str, int | bool]:
    state_correct = answer.response.response_state is case.expected_state
    evidence_supported = _evidence_supported(case, answer)
    confidence_target = 10_000 if state_correct else 0
    calibration_bps = 10_000 - abs(answer.declared_confidence_bps - confidence_target)
    outcome_points = 6000 if state_correct else 0
    evidence_points = 2000 if evidence_supported else 0
    calibration_points = calibration_bps // 10
    false_positive_penalty = (
        4000
        if answer.response.response_state is ResponseState.FINDINGS
        and case.expected_state is not ResponseState.FINDINGS
        else 0
    )
    unsupported_evidence_penalty = (
        6000
        if answer.response.response_state is ResponseState.FINDINGS and not evidence_supported
        else 0
    )
    score_bps = max(
        0,
        outcome_points
        + evidence_points
        + calibration_points
        - false_positive_penalty
        - unsupported_evidence_penalty,
    )
    return {
        "state_correct": state_correct,
        "evidence_supported": evidence_supported,
        "outcome_points": outcome_points,
        "evidence_points": evidence_points,
        "calibration_points": calibration_points,
        "false_positive_penalty": false_positive_penalty,
        "unsupported_evidence_penalty": unsupported_evidence_penalty,
        "score_bps": score_bps,
    }


def _score_miner(miner_id: str) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    answers: dict[str, SimulatedAnswer] = {}
    for case in CASES:
        answer = _miner_answer(miner_id, case)
        answers[case.case_id] = answer
        case_results.append(
            {
                "case_id": case.case_id,
                "response": answer.response.model_dump(mode="json", exclude_none=True),
                "declared_confidence_bps": answer.declared_confidence_bps,
                "score": _score_case(case, answer),
            }
        )

    defect_state = answers["toy-a-planted-defect"].response.response_state
    mutation_state = answers["toy-a-equivalent-mutation"].response.response_state
    robustness_points = 1000 if defect_state is mutation_state is ResponseState.FINDINGS else 0
    mean_case_score = sum(result["score"]["score_bps"] for result in case_results) // len(
        case_results
    )
    total_score = min(10_000, mean_case_score + robustness_points)
    return {
        "miner_id": miner_id,
        "score_bps": total_score,
        "mean_case_score_bps": mean_case_score,
        "equivalent_mutation_robustness_points": robustness_points,
        "case_results": case_results,
    }


def build_weight_intent(
    scores: dict[str, int], *, eligibility_floor_bps: int = 3000
) -> dict[str, Any]:
    """Build a deterministic local weight intent, never a chain-submission payload."""

    eligible = {
        miner_id: score for miner_id, score in scores.items() if score > eligibility_floor_bps
    }
    if not eligible:
        return {
            "status": NO_VALID_WEIGHT_ROW,
            "weights": None,
            "reason": "No simulated miner exceeded the local eligibility floor.",
        }

    adjusted = {
        miner_id: (score - eligibility_floor_bps) ** 2 for miner_id, score in eligible.items()
    }
    denominator = sum(adjusted.values())
    weights = {
        miner_id: numerator * WEIGHT_SCALE // denominator
        for miner_id, numerator in adjusted.items()
    }
    remainder_order = sorted(
        adjusted,
        key=lambda miner_id: (
            -(adjusted[miner_id] * WEIGHT_SCALE % denominator),
            miner_id,
        ),
    )
    unallocated = WEIGHT_SCALE - sum(weights.values())
    for miner_id in remainder_order[:unallocated]:
        weights[miner_id] += 1

    return {
        "status": "SIMULATED_WEIGHT_INTENT",
        "weights": dict(sorted(weights.items())),
        "weight_scale": WEIGHT_SCALE,
        "broadcast_capable": False,
    }


def run_lane_one_simulation(*, force_no_valid_row: bool = False) -> dict[str, Any]:
    """Run the deterministic toy exercise and return a self-committed report."""

    miner_ids = ("evidence_first", "noisy", "alarmist", "abstainer")
    results = [_score_miner(miner_id) for miner_id in miner_ids]
    scores = {result["miner_id"]: result["score_bps"] for result in results}
    weight_scores = {miner_id: 3000 for miner_id in miner_ids} if force_no_valid_row else scores
    body: dict[str, Any] = {
        "simulation_version": SIMULATION_VERSION,
        "claim_state": "IMPLEMENTED_TESTED_SIMULATION_ONLY",
        "boundaries": {
            "benchmark_truth": False,
            "chain_submission": False,
            "external_network": False,
            "production_evidence": False,
            "scoring_constants_normative": False,
        },
        "parameters": {
            "status": "LOCAL_PROVISIONAL_NON_NORMATIVE",
            "score_scale_bps": 10_000,
            "outcome_points": 6000,
            "evidence_points": 2000,
            "calibration_points_max": 1000,
            "equivalent_mutation_robustness_points": 1000,
            "false_positive_penalty": 4000,
            "unsupported_evidence_penalty": 6000,
            "eligibility_floor_bps_exclusive": 3000,
            "weight_transform": "square_above_floor",
        },
        "cases": [
            {
                "case_id": case.case_id,
                "case_class": case.case_class,
                "visible_facts": case.visible_facts,
                "expected_state": case.expected_state,
                "evidence_commitment": case.evidence_commitment,
            }
            for case in CASES
        ],
        "miner_results": results,
        "ranking": sorted(scores, key=lambda miner_id: (-scores[miner_id], miner_id)),
        "weight_intent_input": {
            "source": ("FORCED_BOUNDARY_VECTOR" if force_no_valid_row else "MINER_RESULT_SCORES"),
            "scores_bps": dict(sorted(weight_scores.items())),
        },
        "weight_intent": build_weight_intent(weight_scores),
    }
    return body | {
        "report_commitment": canonical_sha256(
            body,
            domain=REPORT_COMMITMENT_DOMAIN,
        )
    }
