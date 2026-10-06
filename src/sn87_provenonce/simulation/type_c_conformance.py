"""Deterministic candidate-Differential conformance against the transparent Type-C oracle."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable
from sn87_provenonce.protocol.v0alpha1 import (
    PROTOCOL_VERSION,
    AssuranceFinding,
    AssuranceResponse,
    EvidenceReference,
    OracleClass,
    ResponseState,
    canonical_sha256,
)
from sn87_provenonce.simulation.type_c import FIXTURES, TypeCFixture
from sn87_provenonce.simulation.type_c import (
    SIMULATION_VERSION as REFERENCE_ORACLE_VERSION,
)


def _type_c_reference():
    """The private Type C executor, imported at the call that needs it."""
    try:
        from sn87_provenonce.simulation import type_c_reference
    except ImportError as exc:
        raise PrivateReferenceExecutorUnavailable from exc
    return type_c_reference


CONFORMANCE_VERSION = "type-c-candidate-conformance/0alpha1"
REPORT_COMMITMENT_DOMAIN = "SN87:TYPE_C_CANDIDATE_CONFORMANCE_REPORT:v0alpha1"
CANDIDATE_COMMITMENT_DOMAIN = "SN87:TYPE_C_CANDIDATE_DIFFERENTIAL:v0alpha1"
CLAIM_STATE = "IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_CANDIDATE_CONFORMANCE_ONLY"
FIXTURE_EVIDENCE_PREDICATE = "type_c_fixture_input"


def candidate_contract() -> dict[str, object]:
    """Return the disclosed machine-checkable comparison contract."""

    return {
        "protocol_version": PROTOCOL_VERSION,
        "challenge_id_must_equal_fixture_id": True,
        "finding_challenge_id_must_equal_response": True,
        "response_state_must_equal_reference": True,
        "finding_types_must_exactly_equal_reference_defect_codes": True,
        "finding_types_must_be_unique": True,
        "finding_ids_must_be_unique": True,
        "finding_oracle_class": OracleClass.C.value,
        "finding_evidence_predicate": FIXTURE_EVIDENCE_PREDICATE,
        "finding_evidence_commitment": "fixture_input_commitment",
        "candidate_text_semantics_evaluated": False,
        "confidence_calibration_evaluated": False,
        "miner_commitment_evaluated": False,
        "normative_score_emitted": False,
    }


@dataclass(frozen=True)
class CandidateCase:
    candidate_id: str
    fixture_id: str
    response: AssuranceResponse
    expected_pass: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not isinstance(self.fixture_id, str):
            raise TypeError("candidate_id and fixture_id must be strings")
        if not self.candidate_id.strip() or not self.fixture_id.strip():
            raise ValueError("candidate_id and fixture_id must be non-empty")
        if not isinstance(self.response, AssuranceResponse):
            raise TypeError("candidate response must be an AssuranceResponse")
        if self.expected_pass is not None and not isinstance(self.expected_pass, bool):
            raise TypeError("candidate expected_pass must be a boolean or None")
        revalidated = AssuranceResponse.model_validate(self.response.model_dump(mode="python"))
        object.__setattr__(self, "response", revalidated)

    @property
    def commitment(self) -> str:
        return canonical_sha256(
            {
                "candidate_id": self.candidate_id,
                "fixture_id": self.fixture_id,
                "response": self.response.model_dump(mode="json", exclude_none=True),
            },
            domain=CANDIDATE_COMMITMENT_DOMAIN,
        )


def evaluate_candidate(case: CandidateCase, fixture: TypeCFixture) -> dict[str, object]:
    """Compare one typed candidate response with the independently agreed reference outcome."""

    if case.fixture_id != fixture.fixture_id:
        raise ValueError("candidate case and supplied fixture identities differ")
    reference = _type_c_reference().compare_reference_executions(fixture)
    reference_outcome = reference["agreed_outcome"]
    expected_codes = tuple(reference_outcome["defect_codes"])
    findings = case.response.findings or ()
    finding_ids = tuple(finding.finding_id for finding in findings)
    candidate_codes = tuple(sorted(finding.finding_type for finding in findings))
    oracle_class_binding = all(finding.oracle_class is OracleClass.C for finding in findings)
    evidence_binding = all(
        len(finding.evidence) == 1
        and finding.evidence[0].commitment == fixture.input_commitment
        and finding.evidence[0].predicate == FIXTURE_EVIDENCE_PREDICATE
        for finding in findings
    )
    checks = {
        "protocol_version_match": case.response.protocol_version == PROTOCOL_VERSION,
        "challenge_binding": case.response.challenge_id == fixture.fixture_id,
        "finding_challenge_binding": all(
            finding.challenge_id == case.response.challenge_id for finding in findings
        ),
        "response_state_match": case.response.response_state.value
        == reference_outcome["response_state"],
        "exact_finding_types_match": candidate_codes == expected_codes,
        "finding_id_uniqueness": len(finding_ids) == len(set(finding_ids)),
        "oracle_class_binding": oracle_class_binding,
        "evidence_binding": evidence_binding,
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    result = {
        "candidate_id": case.candidate_id,
        "fixture_id": case.fixture_id,
        "fixture_input_commitment": fixture.input_commitment,
        "candidate_commitment": case.commitment,
        "candidate_response": case.response.model_dump(mode="json", exclude_none=True),
        "reference_outcome": reference_outcome,
        "checks": checks,
        "failures": failures,
        "passed": not failures,
    }
    if case.expected_pass is not None:
        result["expected_pass"] = case.expected_pass
    return result


def _finding(
    fixture: TypeCFixture,
    candidate_id: str,
    defect_code: str,
    *,
    challenge_id: str | None = None,
    evidence_commitment: str | None = None,
) -> AssuranceFinding:
    bound_challenge = challenge_id or fixture.fixture_id
    return AssuranceFinding(
        finding_id=f"{candidate_id}:{defect_code}",
        challenge_id=bound_challenge,
        finding_type=defect_code,
        claim=f"Synthetic fixture violates {defect_code}.",
        severity=1.0,
        confidence=1.0,
        oracle_class=OracleClass.C,
        evidence=(
            EvidenceReference(
                commitment=evidence_commitment or fixture.input_commitment,
                predicate=FIXTURE_EVIDENCE_PREDICATE,
            ),
        ),
        recommended_action="Reject this synthetic workflow for conformance.",
    )


def _response_for_reference(fixture: TypeCFixture, candidate_id: str) -> AssuranceResponse:
    outcome = _type_c_reference().compare_reference_executions(fixture)["agreed_outcome"]
    state = ResponseState(outcome["response_state"])
    findings = (
        tuple(_finding(fixture, candidate_id, code) for code in outcome["defect_codes"])
        if state is ResponseState.FINDINGS
        else None
    )
    return AssuranceResponse(
        challenge_id=fixture.fixture_id,
        response_state=state,
        rationale="Deterministic response for the disclosed transparent fixture.",
        findings=findings,
    )


def _adversarial_cases(fixtures: dict[str, TypeCFixture]) -> tuple[CandidateCase, ...]:
    clean = fixtures["type-c-clean-control"]
    defect = fixtures["type-c-missing-review"]
    correct_defect = _response_for_reference(defect, "adversarial-template")
    correct_finding = correct_defect.findings[0]
    wrong_commitment = canonical_sha256(
        "wrong-evidence", domain="SN87:TYPE_C_CANDIDATE_TEST:v0alpha1"
    )
    return (
        CandidateCase(
            "adversarial-false-negative",
            defect.fixture_id,
            AssuranceResponse(
                challenge_id=defect.fixture_id,
                response_state=ResponseState.NO_MATERIAL_DEVIATION,
                rationale="Incorrectly declares the planted defect absent.",
            ),
            False,
        ),
        CandidateCase(
            "adversarial-false-positive",
            clean.fixture_id,
            AssuranceResponse(
                challenge_id=clean.fixture_id,
                response_state=ResponseState.FINDINGS,
                rationale="Incorrectly invents a finding on the clean control.",
                findings=(_finding(clean, "adversarial-false-positive", "FABRICATED_DEFECT"),),
            ),
            False,
        ),
        CandidateCase(
            "adversarial-indiscriminate-abstention",
            defect.fixture_id,
            AssuranceResponse(
                challenge_id=defect.fixture_id,
                response_state=ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN,
                rationale="Incorrectly abstains despite complete disclosed Evidence.",
            ),
            False,
        ),
        CandidateCase(
            "adversarial-wrong-defect-code",
            defect.fixture_id,
            correct_defect.model_copy(
                update={
                    "findings": (
                        _finding(
                            defect,
                            "adversarial-wrong-defect-code",
                            "UNSUPPORTED_DEFECT",
                        ),
                    )
                }
            ),
            False,
        ),
        CandidateCase(
            "adversarial-wrong-evidence",
            defect.fixture_id,
            correct_defect.model_copy(
                update={
                    "findings": (
                        correct_finding.model_copy(
                            update={
                                "finding_id": ("adversarial-wrong-evidence:MISSING_REVIEW_GATE"),
                                "evidence": (
                                    EvidenceReference(
                                        commitment=wrong_commitment,
                                        predicate=FIXTURE_EVIDENCE_PREDICATE,
                                    ),
                                ),
                            }
                        ),
                    )
                }
            ),
            False,
        ),
        CandidateCase(
            "adversarial-wrong-challenge",
            clean.fixture_id,
            AssuranceResponse(
                challenge_id="different-challenge",
                response_state=ResponseState.NO_MATERIAL_DEVIATION,
                rationale="Correct state bound to the wrong challenge.",
            ),
            False,
        ),
        CandidateCase(
            "adversarial-duplicate-finding",
            defect.fixture_id,
            correct_defect.model_copy(update={"findings": (correct_finding, correct_finding)}),
            False,
        ),
        CandidateCase(
            "adversarial-wrong-protocol-version",
            clean.fixture_id,
            AssuranceResponse(
                protocol_version="sn87/incompatible",
                challenge_id=clean.fixture_id,
                response_state=ResponseState.NO_MATERIAL_DEVIATION,
                rationale="Correct state under an incompatible protocol version.",
            ),
            False,
        ),
        CandidateCase(
            "adversarial-wrong-oracle-class",
            defect.fixture_id,
            correct_defect.model_copy(
                update={
                    "findings": (
                        correct_finding.model_copy(update={"oracle_class": OracleClass.A}),
                    )
                }
            ),
            False,
        ),
    )


def build_candidate_corpus() -> tuple[CandidateCase, ...]:
    fixtures = {fixture.fixture_id: fixture for fixture in FIXTURES}
    conformant = tuple(
        CandidateCase(
            candidate_id=f"reference-conformant:{fixture.fixture_id}",
            fixture_id=fixture.fixture_id,
            response=_response_for_reference(fixture, f"reference-conformant:{fixture.fixture_id}"),
            expected_pass=True,
        )
        for fixture in FIXTURES
    )
    return conformant + _adversarial_cases(fixtures)


@cache
def _candidate_cases() -> tuple[CandidateCase, ...]:
    return build_candidate_corpus()


def __getattr__(name: str) -> object:
    """``CANDIDATE_CASES`` is built on first use: the corpus needs the private executor."""
    if name == "CANDIDATE_CASES":
        return _candidate_cases()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def run_type_c_candidate_conformance() -> dict[str, Any]:
    """Run the versioned transparent candidate corpus and return a committed report."""

    fixtures = {fixture.fixture_id: fixture for fixture in FIXTURES}
    candidate_ids = [case.candidate_id for case in _candidate_cases()]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate_ids must be unique")
    results = [evaluate_candidate(case, fixtures[case.fixture_id]) for case in _candidate_cases()]
    body: dict[str, Any] = {
        "conformance_version": CONFORMANCE_VERSION,
        "reference_oracle_version": REFERENCE_ORACLE_VERSION,
        "reference_oracle_report_commitment": (
            _type_c_reference().run_type_c_simulation()["report_commitment"]
        ),
        "claim_state": CLAIM_STATE,
        "boundaries": {
            "hidden_truth": False,
            "normative_scoring": False,
            "ranking": False,
            "weight_planning": False,
            "network": False,
            "wallet": False,
            "chain_submission": False,
            "testnet": False,
            "production_evidence": False,
        },
        "candidate_contract": candidate_contract(),
        "cases": results,
        "summary": {
            "case_count": len(results),
            "expected_pass_count": sum(case.expected_pass for case in _candidate_cases()),
            "expected_fail_count": sum(not case.expected_pass for case in _candidate_cases()),
            "observed_pass_count": sum(result["passed"] for result in results),
            "observed_fail_count": sum(not result["passed"] for result in results),
        },
        "all_expectations_met": all(
            result["passed"] is result["expected_pass"] for result in results
        ),
    }
    return body | {"report_commitment": canonical_sha256(body, domain=REPORT_COMMITMENT_DOMAIN)}
