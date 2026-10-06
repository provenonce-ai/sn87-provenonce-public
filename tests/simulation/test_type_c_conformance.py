from __future__ import annotations

from copy import deepcopy

import _requires_executors  # noqa: F401
import pytest
from pydantic import ValidationError

from sn87_provenonce.cli import main
from sn87_provenonce.protocol.v0alpha1 import canonical_sha256
from sn87_provenonce.simulation import (
    CANDIDATE_CASES,
    CandidateCase,
    run_type_c_candidate_conformance,
    verify_type_c_conformance_evidence_bundle,
    write_type_c_conformance_evidence_bundle,
)
from sn87_provenonce.simulation.type_c_conformance import REPORT_COMMITMENT_DOMAIN


def result(report, candidate_id: str):
    return next(case for case in report["cases"] if case["candidate_id"] == candidate_id)


def test_candidate_corpus_exercises_pass_and_fail_paths() -> None:
    report = run_type_c_candidate_conformance()

    assert report["claim_state"] == (
        "IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_CANDIDATE_CONFORMANCE_ONLY"
    )
    assert report["all_expectations_met"] is True
    assert report["summary"] == {
        "case_count": 17,
        "expected_pass_count": 8,
        "expected_fail_count": 9,
        "observed_pass_count": 8,
        "observed_fail_count": 9,
    }
    assert len(CANDIDATE_CASES) == 17
    assert all(value is False for value in report["boundaries"].values())
    assert report["candidate_contract"]["candidate_text_semantics_evaluated"] is False
    assert report["candidate_contract"]["normative_score_emitted"] is False
    assert report["reference_oracle_report_commitment"] == (
        "sha256:354472f0ab5ba0d1e863b24f509c395a913e06a5616e0e3f3faab0916432d9ec"
    )
    assert all(case["fixture_input_commitment"].startswith("sha256:") for case in report["cases"])


@pytest.mark.parametrize(
    ("candidate_id", "failures"),
    [
        (
            "adversarial-false-negative",
            ["exact_finding_types_match", "response_state_match"],
        ),
        (
            "adversarial-false-positive",
            ["exact_finding_types_match", "response_state_match"],
        ),
        (
            "adversarial-indiscriminate-abstention",
            ["exact_finding_types_match", "response_state_match"],
        ),
        ("adversarial-wrong-defect-code", ["exact_finding_types_match"]),
        ("adversarial-wrong-evidence", ["evidence_binding"]),
        ("adversarial-wrong-challenge", ["challenge_binding"]),
        (
            "adversarial-duplicate-finding",
            ["exact_finding_types_match", "finding_id_uniqueness"],
        ),
        ("adversarial-wrong-protocol-version", ["protocol_version_match"]),
        ("adversarial-wrong-oracle-class", ["oracle_class_binding"]),
    ],
)
def test_adversarial_candidates_fail_for_disclosed_reasons(candidate_id, failures) -> None:
    case = result(run_type_c_candidate_conformance(), candidate_id)

    assert case["passed"] is False
    assert case["expected_pass"] is False
    assert case["failures"] == failures


def test_every_reference_conformant_candidate_passes() -> None:
    report = run_type_c_candidate_conformance()
    conformant = [
        case for case in report["cases"] if case["candidate_id"].startswith("reference-conformant:")
    ]

    assert len(conformant) == 8
    assert all(case["passed"] is True and not case["failures"] for case in conformant)


def test_candidate_case_revalidates_copied_nested_models() -> None:
    good = next(
        case
        for case in CANDIDATE_CASES
        if case.candidate_id == "reference-conformant:type-c-missing-review"
    )
    bad_finding = good.response.findings[0].model_copy(
        update={"challenge_id": "different-challenge"}
    )
    bad_response = good.response.model_copy(update={"findings": (bad_finding,)})

    with pytest.raises(ValidationError, match="every finding must bind"):
        CandidateCase("copied-invalid-response", good.fixture_id, bad_response, False)


def test_report_is_deterministic_and_committed() -> None:
    first = run_type_c_candidate_conformance()
    second = run_type_c_candidate_conformance()

    assert first == second
    assert first["report_commitment"].startswith("sha256:")
    assert all(case["candidate_commitment"].startswith("sha256:") for case in first["cases"])


def test_bundle_rejects_self_committed_candidate_result_change(tmp_path) -> None:
    report = run_type_c_candidate_conformance()
    body = deepcopy({key: value for key, value in report.items() if key != "report_commitment"})
    body["cases"][0]["passed"] = False
    body["cases"][0]["failures"] = ["fabricated"]
    tampered = body | {"report_commitment": canonical_sha256(body, domain=REPORT_COMMITMENT_DOMAIN)}

    with pytest.raises(ValueError, match="does not match the versioned corpus"):
        write_type_c_conformance_evidence_bundle(tampered, tmp_path / "evidence")


def test_bundle_is_create_only_and_reconstructs_report(tmp_path) -> None:
    destination = tmp_path / "evidence"
    report = run_type_c_candidate_conformance()
    created = write_type_c_conformance_evidence_bundle(report, destination)

    assert verify_type_c_conformance_evidence_bundle(destination) == created
    with pytest.raises(FileExistsError, match="already exists"):
        write_type_c_conformance_evidence_bundle(report, destination)


def test_cli_creates_and_verifies_candidate_conformance_bundle(tmp_path, capsys) -> None:
    destination = tmp_path / "evidence"
    assert main(["conform-type-c-candidates", "--output-dir", str(destination)]) == 0
    capsys.readouterr()

    assert main(["verify-type-c-conformance-bundle", str(destination)]) == 0
    assert '"status": "VERIFIED"' in capsys.readouterr().out
