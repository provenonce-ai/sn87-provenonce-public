from __future__ import annotations

import json
import shutil
from dataclasses import replace
from itertools import product

import _requires_executors  # noqa: F401
import pytest

from sn87_provenonce.cli import main
from sn87_provenonce.protocol.v0alpha1 import ResponseState, canonical_sha256
from sn87_provenonce.simulation import (
    FIXTURES,
    ReferenceOutcome,
    compare_reference_executions,
    execute_relational,
    execute_state_machine,
    run_type_c_simulation,
    verify_type_c_evidence_bundle,
    write_type_c_evidence_bundle,
)
from sn87_provenonce.simulation.type_c import (
    EventKind,
    WorkflowEvent,
    _validate_fixture_set,
    workflow_contract,
)


def fixture(fixture_id: str):
    return next(value for value in FIXTURES if value.fixture_id == fixture_id)


@pytest.mark.parametrize(
    ("fixture_id", "state", "defects"),
    [
        ("type-c-clean-control", ResponseState.NO_MATERIAL_DEVIATION, []),
        ("type-c-missing-review", ResponseState.FINDINGS, ["MISSING_REVIEW_GATE"]),
        (
            "type-c-missing-review-equivalent-observation",
            ResponseState.FINDINGS,
            ["MISSING_REVIEW_GATE"],
        ),
        ("type-c-chain-break", ResponseState.FINDINGS, ["EVIDENCE_CHAIN_BREAK"]),
        (
            "type-c-insufficient-evidence",
            ResponseState.INSUFFICIENT_EVIDENCE_ABSTAIN,
            [],
        ),
        ("type-c-missing-submit", ResponseState.FINDINGS, ["MISSING_SUBMIT_EVENT"]),
        (
            "type-c-validation-before-submit",
            ResponseState.FINDINGS,
            ["INVALID_WORKFLOW_ORDER"],
        ),
        (
            "type-c-duplicate-submit",
            ResponseState.FINDINGS,
            ["DUPLICATE_SUBMIT_EVENT"],
        ),
    ],
)
def test_independent_references_agree_on_expected_outcome(fixture_id, state, defects) -> None:
    result = compare_reference_executions(fixture(fixture_id))

    assert result["reference_agreement"] is True
    assert result["events"]
    assert isinstance(result["evidence_complete"], bool)
    assert result["agreed_outcome"] == {
        "response_state": state.value,
        "defect_codes": defects,
    }


def test_equivalent_mutation_preserves_material_outcome() -> None:
    original = compare_reference_executions(fixture("type-c-missing-review"))
    mutation = compare_reference_executions(fixture("type-c-missing-review-equivalent-observation"))

    assert original["agreed_outcome"] == mutation["agreed_outcome"]
    assert mutation["mutation_provenance"] == {
        "source_fixture_id": "type-c-missing-review",
        "operator": "INSERT_SEMANTIC_NO_OP",
        "expected_invariant": "MISSING_REVIEW_GATE",
    }


def test_reference_disagreement_fails_closed() -> None:
    def incorrect(_fixture):
        return ReferenceOutcome(ResponseState.NO_MATERIAL_DEVIATION, ())

    with pytest.raises(ValueError, match="reference execution disagreement"):
        compare_reference_executions(
            fixture("type-c-missing-review"),
            executors=(("state_machine", execute_state_machine), ("incorrect", incorrect)),
        )


def test_unestablished_mutation_invariant_fails_closed() -> None:
    source = fixture("type-c-missing-review")
    invalid = replace(
        source,
        provenance=replace(source.provenance, expected_invariant="EVIDENCE_CHAIN_BREAK"),
    )

    with pytest.raises(ValueError, match="mutation invariant not established"):
        compare_reference_executions(invalid)


def test_executor_names_must_be_unique() -> None:
    def clean(_fixture):
        return ReferenceOutcome(ResponseState.NO_MATERIAL_DEVIATION, ())

    with pytest.raises(ValueError, match="names must be non-empty and unique"):
        compare_reference_executions(
            fixture("type-c-clean-control"),
            executors=(("duplicate", clean), ("duplicate", clean)),
        )


def test_report_is_deterministic_and_explicitly_bounded() -> None:
    first = run_type_c_simulation()
    second = run_type_c_simulation()

    assert first == second
    assert first["claim_state"] == "IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_REFERENCE_ORACLE_ONLY"
    assert first["workflow_contract"] == workflow_contract()
    assert first["all_references_agree"] is True
    assert all(value is False for value in first["boundaries"].values())
    assert first["report_commitment"].startswith("sha256:")


def test_type_c_bundle_is_create_only_and_detects_tampering(tmp_path) -> None:
    destination = tmp_path / "type-c"
    report = run_type_c_simulation()
    created = write_type_c_evidence_bundle(report, destination)

    assert verify_type_c_evidence_bundle(destination) == created
    with pytest.raises(FileExistsError, match="already exists"):
        write_type_c_evidence_bundle(report, destination)

    report_path = destination / "report.json"
    value = json.loads(report_path.read_text(encoding="utf-8"))
    value["all_references_agree"] = False
    report_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="byte hash mismatch"):
        verify_type_c_evidence_bundle(destination)


@pytest.mark.parametrize("linked_name", ["manifest.json", "report.json"])
def test_type_c_bundle_rejects_symbolic_link_entries(tmp_path, linked_name) -> None:
    source = tmp_path / "source"
    write_type_c_evidence_bundle(run_type_c_simulation(), source)
    destination = tmp_path / "linked"
    destination.mkdir()
    for name in ("manifest.json", "report.json"):
        target = destination / name
        if name == linked_name:
            target.symlink_to(source / name)
        else:
            shutil.copyfile(source / name, target)

    with pytest.raises(ValueError, match="could not be opened safely"):
        verify_type_c_evidence_bundle(destination)


def test_mutation_provenance_is_executable_and_replay_validated() -> None:
    clean = fixture("type-c-clean-control")
    chain_break = fixture("type-c-chain-break")
    mislabeled = replace(chain_break, events=clean.events)

    with pytest.raises(ValueError, match="mutation replay mismatch"):
        _validate_fixture_set((clean, mislabeled))


def test_references_reject_observation_outside_workflow() -> None:
    clean = fixture("type-c-clean-control")
    first = clean.events[0]
    observation = WorkflowEvent(
        event_id="early-observation",
        kind=EventKind.OBSERVE,
        input_commitment=first.input_commitment,
        output_commitment=first.input_commitment,
    )
    malformed = replace(
        clean,
        fixture_id="type-c-observation-before-submit",
        events=(observation,) + clean.events,
        provenance=replace(
            clean.provenance,
            operator="PROBE",
            expected_invariant="OBSERVATION_OUTSIDE_WORKFLOW",
        ),
    )

    result = compare_reference_executions(malformed)
    assert result["agreed_outcome"] == {
        "response_state": "FINDINGS",
        "defect_codes": ["OBSERVATION_OUTSIDE_WORKFLOW"],
    }


def test_reference_algorithms_agree_across_bounded_event_grammar() -> None:
    clean = fixture("type-c-clean-control")
    for length in range(1, 6):
        for sequence in product(EventKind, repeat=length):
            markers = [
                canonical_sha256(f"state-{index}", domain="SN87:TYPE_C_GRAMMAR_TEST:v1")
                for index in range(length + 1)
            ]
            events = tuple(
                WorkflowEvent(
                    event_id=f"event-{index}",
                    kind=kind,
                    input_commitment=markers[index],
                    output_commitment=markers[index + 1],
                    approved=True if kind is EventKind.REVIEW else None,
                )
                for index, kind in enumerate(sequence)
            )
            candidate = replace(
                clean,
                fixture_id="bounded-grammar-probe",
                case_class="TEST_ONLY",
                events=events,
                provenance=replace(clean.provenance, operator="TEST_ONLY"),
            )

            assert execute_state_machine(candidate) == execute_relational(candidate)


def test_type_c_bundle_rejects_self_committed_boundary_expansion(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    body["boundaries"]["miner_scoring"] = True
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="boundaries must all be false"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_self_committed_workflow_contract_change(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    body["workflow_contract"]["release_must_be_terminal"] = False
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="workflow contract mismatch"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_self_committed_unknown_report_field(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    body["unsupported_claim"] = True
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="report field set mismatch"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_self_committed_fixture_subset(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    body["fixtures"] = body["fixtures"][:1]
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="fixture corpus mismatch"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_self_committed_reference_disagreement(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    body["fixtures"][0]["reference_results"]["relational"] = {
        "response_state": "FINDINGS",
        "defect_codes": ["INJECTED"],
    }
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="reference results differ"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_self_committed_fabricated_agreement(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    target = body["fixtures"][0]
    fabricated = {
        "response_state": "NO_MATERIAL_DEVIATION",
        "defect_codes": ["FABRICATED_DEFECT"],
    }
    target["reference_results"] = {
        "state_machine": fabricated,
        "relational": fabricated,
    }
    target["agreed_outcome"] = fabricated
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="does not match recomputed reference execution"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_disclosed_input_commitment_mismatch(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    body["fixtures"][0]["events"][0]["event_id"] = "tampered"
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="does not match disclosed input"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_self_committed_unknown_event_kind(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    target = body["fixtures"][0]
    target["events"][0]["kind"] = "INVENTED"
    target["input_commitment"] = canonical_sha256(
        {
            "fixture_id": target["fixture_id"],
            "case_class": target["case_class"],
            "evidence_complete": target["evidence_complete"],
            "events": target["events"],
            "provenance": target["mutation_provenance"],
        },
        domain="SN87:TYPE_C_TRANSPARENT_FIXTURE:v0alpha2",
    )
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="event kind is invalid"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_bundle_rejects_self_committed_duplicate_event_ids(tmp_path) -> None:
    report = run_type_c_simulation()
    body = {key: value for key, value in report.items() if key != "report_commitment"}
    target = body["fixtures"][0]
    target["events"][1]["event_id"] = target["events"][0]["event_id"]
    target["input_commitment"] = canonical_sha256(
        {
            "fixture_id": target["fixture_id"],
            "case_class": target["case_class"],
            "evidence_complete": target["evidence_complete"],
            "events": target["events"],
            "provenance": target["mutation_provenance"],
        },
        domain="SN87:TYPE_C_TRANSPARENT_FIXTURE:v0alpha2",
    )
    expanded = body | {
        "report_commitment": canonical_sha256(
            body,
            domain="SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2",
        )
    }

    with pytest.raises(ValueError, match="event identities must be unique"):
        write_type_c_evidence_bundle(expanded, tmp_path / "type-c")


def test_type_c_cli_creates_and_verifies_bundle(tmp_path, capsys) -> None:
    destination = tmp_path / "type-c"
    assert main(["simulate-type-c-reference", "--output-dir", str(destination)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "VERIFIED"

    assert main(["verify-type-c-bundle", str(destination)]) == 0
    assert json.loads(capsys.readouterr().out) == created
