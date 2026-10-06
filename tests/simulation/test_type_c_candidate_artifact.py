from __future__ import annotations

import json
import os
from copy import deepcopy

import _requires_executors  # noqa: F401
import pytest

import sn87_provenonce.simulation.type_c_candidate_artifact_evidence as artifact_evidence
from sn87_provenonce.cli import main
from sn87_provenonce.protocol.v0alpha1 import PROTOCOL_VERSION, canonical_json_bytes
from sn87_provenonce.simulation import (
    ARTIFACT_TYPE,
    ARTIFACT_VERSION,
    CANDIDATE_CASES,
    FIXTURES,
    CandidateArtifactError,
    CandidateArtifactEvidenceError,
    parse_candidate_artifact,
    run_type_c_candidate_artifact_bytes,
    verify_type_c_candidate_artifact_evidence_bundle,
    write_type_c_candidate_artifact_evidence_bundle,
)
from sn87_provenonce.simulation.type_c import SIMULATION_VERSION
from sn87_provenonce.simulation.type_c_candidate_artifact import (
    CONFORMANCE_VERSION,
    MAX_ARTIFACT_BYTES,
    MAX_JSON_DEPTH,
    REFERENCE_ORACLE_REPORT_COMMITMENT,
    read_bounded_regular_file,
)


def artifact_value() -> dict:
    responses = {
        case.fixture_id: case.response.model_dump(mode="json", exclude_none=True)
        for case in CANDIDATE_CASES
        if case.candidate_id.startswith("reference-conformant:")
    }
    return {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "conformance_version": CONFORMANCE_VERSION,
        "reference_oracle_version": SIMULATION_VERSION,
        "reference_oracle_report_commitment": REFERENCE_ORACLE_REPORT_COMMITMENT,
        "candidate_id": "offline-reference-candidate",
        "cases": [
            {"fixture_id": fixture.fixture_id, "response": responses[fixture.fixture_id]}
            for fixture in FIXTURES
        ],
    }


def artifact_bytes(value: dict | None = None) -> bytes:
    return canonical_json_bytes(value or artifact_value()) + b"\n"


def test_valid_artifact_runs_in_fixture_order_without_harness_expectations() -> None:
    report = run_type_c_candidate_artifact_bytes(artifact_bytes())

    assert report["summary"] == {
        "case_count": 8,
        "passed_count": 8,
        "failed_count": 0,
        "all_cases_conformant": True,
    }
    assert report["fixture_order"] == [fixture.fixture_id for fixture in FIXTURES]
    assert all("expected_pass" not in case for case in report["cases"])
    assert all(case["candidate_commitment"].startswith("sha256:") for case in report["cases"])
    assert all(value is False for value in report["boundaries"].values())


def test_wire_order_is_nonsemantic_but_raw_hash_preserves_it() -> None:
    original = artifact_value()
    reversed_value = deepcopy(original)
    reversed_value["cases"].reverse()
    original_report = run_type_c_candidate_artifact_bytes(artifact_bytes(original))
    reversed_payload = json.dumps(reversed_value, indent=2, ensure_ascii=False).encode()
    reversed_report = run_type_c_candidate_artifact_bytes(reversed_payload)

    assert original_report["source_artifact_sha256"] != reversed_report["source_artifact_sha256"]
    assert (
        original_report["normalized_artifact_commitment"]
        == (reversed_report["normalized_artifact_commitment"])
    )
    assert original_report["cases"] == reversed_report["cases"]


def test_numeric_spelling_is_normalized_after_validation() -> None:
    integer = artifact_value()
    decimal = deepcopy(integer)
    finding_case = next(case for case in integer["cases"] if case["response"].get("findings"))
    decimal_case = next(case for case in decimal["cases"] if case["response"].get("findings"))
    finding_case["response"]["findings"][0]["severity"] = 1
    decimal_case["response"]["findings"][0]["severity"] = 1.0
    integer_payload = json.dumps(integer, separators=(",", ":")).encode()
    decimal_payload = json.dumps(decimal, separators=(",", ":")).encode()

    integer_report = run_type_c_candidate_artifact_bytes(integer_payload)
    decimal_report = run_type_c_candidate_artifact_bytes(decimal_payload)
    assert integer_report["source_artifact_sha256"] != decimal_report["source_artifact_sha256"]
    assert (
        integer_report["normalized_artifact_commitment"]
        == (decimal_report["normalized_artifact_commitment"])
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_type", "foreign"),
        ("artifact_version", "foreign/0"),
        ("protocol_version", "sn87/foreign"),
        ("conformance_version", "foreign/0"),
        ("reference_oracle_version", "foreign/0"),
        ("reference_oracle_report_commitment", "sha256:" + "0" * 64),
    ],
)
def test_envelope_identity_must_match_local_contract(field, value) -> None:
    candidate = artifact_value()
    candidate[field] = value
    with pytest.raises(CandidateArtifactError, match=field):
        run_type_c_candidate_artifact_bytes(artifact_bytes(candidate))


def test_envelope_rejects_missing_and_extra_fields() -> None:
    missing = artifact_value()
    del missing["protocol_version"]
    extra = artifact_value() | {"producer": "not-semantic"}

    with pytest.raises(CandidateArtifactError):
        run_type_c_candidate_artifact_bytes(artifact_bytes(missing))
    with pytest.raises(CandidateArtifactError):
        run_type_c_candidate_artifact_bytes(artifact_bytes(extra))


def test_external_cases_reject_harness_expectations_and_reference_truth() -> None:
    expected_pass = artifact_value()
    expected_pass["cases"][0]["expected_pass"] = True
    reference_truth = artifact_value()
    reference_truth["cases"][0]["reference_outcome"] = {"response_state": "FINDINGS"}

    for invalid in (expected_pass, reference_truth):
        with pytest.raises(CandidateArtifactError):
            run_type_c_candidate_artifact_bytes(artifact_bytes(invalid))


def test_fixture_set_rejects_missing_extra_and_duplicate_ids() -> None:
    missing = artifact_value()
    missing["cases"] = missing["cases"][:-1]
    extra = artifact_value()
    extra["cases"].append(deepcopy(extra["cases"][0]))
    duplicate = artifact_value()
    duplicate["cases"][-1]["fixture_id"] = duplicate["cases"][0]["fixture_id"]
    duplicate["cases"][-1]["response"]["challenge_id"] = duplicate["cases"][0]["fixture_id"]

    for invalid in (missing, extra, duplicate):
        with pytest.raises(CandidateArtifactError):
            run_type_c_candidate_artifact_bytes(artifact_bytes(invalid))


def test_fixture_and_response_challenge_must_match() -> None:
    candidate = artifact_value()
    candidate["cases"][0]["response"]["challenge_id"] = "different"
    with pytest.raises(CandidateArtifactError, match="fixture_id must equal"):
        run_type_c_candidate_artifact_bytes(artifact_bytes(candidate))


def test_nested_finding_challenge_must_match_response() -> None:
    candidate = artifact_value()
    finding_case = next(case for case in candidate["cases"] if case["response"].get("findings"))
    finding_case["response"]["findings"][0]["challenge_id"] = "different"

    with pytest.raises(CandidateArtifactError, match="every finding must bind"):
        run_type_c_candidate_artifact_bytes(artifact_bytes(candidate))


def test_response_amplification_limits_are_enforced() -> None:
    too_many_findings = artifact_value()
    finding_case = next(
        case for case in too_many_findings["cases"] if case["response"].get("findings")
    )
    seed = finding_case["response"]["findings"][0]
    finding_case["response"]["findings"] = [
        deepcopy(seed) | {"finding_id": f"bounded-finding-{index}"} for index in range(33)
    ]

    too_many_evidence = artifact_value()
    evidence_case = next(
        case for case in too_many_evidence["cases"] if case["response"].get("findings")
    )
    evidence_seed = evidence_case["response"]["findings"][0]["evidence"][0]
    evidence_case["response"]["findings"][0]["evidence"] = [
        deepcopy(evidence_seed) for _ in range(17)
    ]

    oversized_string = artifact_value()
    oversized_string["candidate_id"] = "x" * 129

    for invalid in (too_many_findings, too_many_evidence, oversized_string):
        with pytest.raises(CandidateArtifactError):
            run_type_c_candidate_artifact_bytes(artifact_bytes(invalid))


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b" \n\t",
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'{"x":"\\ud800"}',
        b"{} trailing",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1,"x":2}',
        '{"e\u0301":1,"é":2}'.encode(),
    ],
)
def test_parser_rejects_ambiguous_or_invalid_json(payload) -> None:
    with pytest.raises(CandidateArtifactError):
        run_type_c_candidate_artifact_bytes(payload)


def test_parser_rejects_excessive_depth() -> None:
    value: object = "leaf"
    for _ in range(MAX_JSON_DEPTH + 2):
        value = [value]
    with pytest.raises(CandidateArtifactError, match="depth"):
        run_type_c_candidate_artifact_bytes(json.dumps(value).encode())


def test_bounded_reader_accepts_max_and_rejects_max_plus_one(tmp_path) -> None:
    maximum = tmp_path / "maximum.json"
    oversized = tmp_path / "oversized.json"
    maximum.write_bytes(b"x" * 16)
    oversized.write_bytes(b"x" * 17)

    assert read_bounded_regular_file(maximum, max_bytes=16) == b"x" * 16
    with pytest.raises(CandidateArtifactError, match="exceeds"):
        read_bounded_regular_file(oversized, max_bytes=16)
    with pytest.raises(ValueError, match="positive integer"):
        read_bounded_regular_file(maximum, max_bytes=True)


def test_every_bytes_entry_point_enforces_the_default_size_ceiling() -> None:
    base = artifact_bytes()
    at_limit = base + b" " * (MAX_ARTIFACT_BYTES - len(base))
    over_limit = at_limit + b" "

    assert len(at_limit) == MAX_ARTIFACT_BYTES
    assert parse_candidate_artifact(at_limit).candidate_id == "offline-reference-candidate"
    assert run_type_c_candidate_artifact_bytes(at_limit)["summary"]["all_cases_conformant"]
    for entry_point in (parse_candidate_artifact, run_type_c_candidate_artifact_bytes):
        with pytest.raises(CandidateArtifactError, match="exceeds"):
            entry_point(over_limit)
        with pytest.raises(CandidateArtifactError, match="must be bytes"):
            entry_point(bytearray(base))


def test_reader_rejects_symlink_directory_and_fifo(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(artifact_bytes())
    symlink = tmp_path / "link.json"
    symlink.symlink_to(source)
    fifo = tmp_path / "candidate.fifo"
    os.mkfifo(fifo)

    for invalid in (symlink, tmp_path, fifo):
        with pytest.raises(CandidateArtifactError, match="regular file"):
            read_bounded_regular_file(invalid)


def test_invalid_source_creates_no_bundle(tmp_path) -> None:
    source = tmp_path / "invalid.json"
    source.write_bytes(b"{}")
    destination = tmp_path / "evidence"

    with pytest.raises(CandidateArtifactError):
        write_type_c_candidate_artifact_evidence_bundle(source, destination)
    assert not destination.exists()


def test_bundle_preserves_source_and_reconstructs_everything(tmp_path) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    created = write_type_c_candidate_artifact_evidence_bundle(source, destination)

    assert destination.joinpath("candidate-artifact.json").read_bytes() == source.read_bytes()
    assert created["status"] == "VERIFIED"
    assert created["all_cases_conformant"] is True
    assert verify_type_c_candidate_artifact_evidence_bundle(destination) == created
    with pytest.raises(FileExistsError):
        write_type_c_candidate_artifact_evidence_bundle(source, destination)


def test_reference_candidate_bundle_bytes_remain_contract_compatible(tmp_path) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)

    assert {
        name: artifact_evidence.raw_sha256(destination.joinpath(name).read_bytes())
        for name in sorted(artifact_evidence.EXPECTED_FILES)
    } == {
        "candidate-artifact.json": (
            "sha256:1bc7f9aaa15b41d0b8bf08738dea60b0c21a359f50540459e7bc65a615c62617"
        ),
        "manifest.json": "sha256:1195d0ae2be096fb8a511c32ae2bd28b8aad4e6ce16547f3273d2c3f09c6d544",
        "report.json": "sha256:2f9d37154ff93c7139756eb76332eb41960141f51e1be9d94a1db90a5c68be14",
    }


@pytest.mark.parametrize("name", ["candidate-artifact.json", "report.json", "manifest.json"])
def test_bundle_rejects_tampering_of_every_file(tmp_path, name) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)
    destination.joinpath(name).write_bytes(destination.joinpath(name).read_bytes() + b" ")

    with pytest.raises(ValueError):
        verify_type_c_candidate_artifact_evidence_bundle(destination)


def test_bundle_normalizes_malformed_preserved_candidate_failure(tmp_path) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)

    malformed = b"{}\n"
    destination.joinpath("candidate-artifact.json").write_bytes(malformed)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["candidate-artifact.json"] = artifact_evidence.raw_sha256(malformed)
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    with pytest.raises(
        CandidateArtifactEvidenceError, match="invalid preserved candidate artifact"
    ):
        verify_type_c_candidate_artifact_evidence_bundle(destination)


def test_bundle_rejects_unexpected_and_symlink_entries(tmp_path) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)
    destination.joinpath("unexpected").write_text("x")
    with pytest.raises(CandidateArtifactEvidenceError, match="file set mismatch"):
        verify_type_c_candidate_artifact_evidence_bundle(destination)

    destination.joinpath("unexpected").unlink()
    report = destination.joinpath("report.json")
    saved = report.read_bytes()
    report.unlink()
    report.symlink_to(source)
    with pytest.raises(CandidateArtifactEvidenceError, match="opened safely"):
        verify_type_c_candidate_artifact_evidence_bundle(destination)
    report.unlink()
    report.write_bytes(saved)


def test_bundle_writer_cannot_follow_raced_entry_symlink(tmp_path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"preserve-me")
    open_directory = artifact_evidence._open_new_bundle_directory

    def raced_directory(path):
        descriptor = open_directory(path)
        path.joinpath("report.json").symlink_to(victim)
        return descriptor

    monkeypatch.setattr(artifact_evidence, "_open_new_bundle_directory", raced_directory)
    with pytest.raises(CandidateArtifactEvidenceError, match="created exclusively"):
        write_type_c_candidate_artifact_evidence_bundle(source, destination)
    assert victim.read_bytes() == b"preserve-me"


def test_bundle_writer_cannot_follow_raced_parent_symlink(tmp_path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    parent = tmp_path / "parent"
    destination = parent / "evidence"
    displaced = tmp_path / "displaced"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    mkdir = artifact_evidence.os.mkdir
    swapped = False

    def swap_parent(path, *args, **kwargs):
        nonlocal swapped
        result = mkdir(path, *args, **kwargs)
        if path == parent.name and not swapped:
            parent.rename(displaced)
            parent.symlink_to(attacker, target_is_directory=True)
            swapped = True
        return result

    monkeypatch.setattr(artifact_evidence.os, "mkdir", swap_parent)
    with pytest.raises(CandidateArtifactEvidenceError, match="anchored safely"):
        write_type_c_candidate_artifact_evidence_bundle(source, destination)
    assert not displaced.joinpath("evidence").exists()
    assert not attacker.joinpath("evidence").exists()


def test_verifier_rejects_intermediate_parent_symlink(tmp_path) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    real_parent = tmp_path / "real-parent"
    destination = real_parent / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(CandidateArtifactEvidenceError, match="anchored safely"):
        verify_type_c_candidate_artifact_evidence_bundle(alias / "evidence")


def test_bundle_verifier_rejects_hard_link_entries(tmp_path) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)
    report = destination / "report.json"
    linked_source = tmp_path / "linked-report.json"
    linked_source.write_bytes(report.read_bytes())
    report.unlink()
    os.link(linked_source, report)

    with pytest.raises(CandidateArtifactEvidenceError, match="exactly one link"):
        verify_type_c_candidate_artifact_evidence_bundle(destination)


def test_output_limits_fail_before_bundle_creation(tmp_path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    monkeypatch.setattr(artifact_evidence, "MAX_REPORT_BYTES", 1)

    with pytest.raises(CandidateArtifactEvidenceError, match="report exceeds"):
        write_type_c_candidate_artifact_evidence_bundle(source, destination)
    assert not destination.exists()


def test_bundle_writer_detects_post_write_directory_substitution(tmp_path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    alternate_source = tmp_path / "alternate.json"
    alternate_payload = artifact_value()
    alternate_payload["candidate_id"] = "alternate-candidate"
    alternate_source.write_bytes(artifact_bytes(alternate_payload))
    alternate = tmp_path / "alternate-bundle"
    write_type_c_candidate_artifact_evidence_bundle(alternate_source, alternate)

    destination = tmp_path / "evidence"
    displaced = tmp_path / "displaced"
    verify_descriptor = artifact_evidence._verify_type_c_candidate_artifact_evidence_descriptor

    def swapped_directory(descriptor):
        result = verify_descriptor(descriptor)
        destination.rename(displaced)
        alternate.rename(destination)
        return result

    monkeypatch.setattr(
        artifact_evidence,
        "_verify_type_c_candidate_artifact_evidence_descriptor",
        swapped_directory,
    )
    with pytest.raises(CandidateArtifactEvidenceError, match="changed during creation"):
        write_type_c_candidate_artifact_evidence_bundle(source, destination)

    assert displaced.joinpath("candidate-artifact.json").read_bytes() == source.read_bytes()
    assert (
        destination.joinpath("candidate-artifact.json").read_bytes()
        == alternate_source.read_bytes()
    )


def test_writer_rejects_membership_injection_during_descriptor_verification(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    read_open_file = artifact_evidence._read_open_file
    injected = False

    def inject_entry(descriptor, name, max_bytes):
        nonlocal injected
        payload = read_open_file(descriptor, name, max_bytes)
        if not injected:
            destination.joinpath("unexpected").write_bytes(b"x")
            injected = True
        return payload

    monkeypatch.setattr(artifact_evidence, "_read_open_file", inject_entry)
    with pytest.raises(CandidateArtifactEvidenceError, match="membership changed"):
        write_type_c_candidate_artifact_evidence_bundle(source, destination)


def test_verifier_rejects_entry_overwrite_during_descriptor_verification(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)
    read_open_file = artifact_evidence._read_open_file
    overwritten = False

    def overwrite_report(descriptor, name, max_bytes):
        nonlocal overwritten
        payload = read_open_file(descriptor, name, max_bytes)
        if name == "report.json" and not overwritten:
            destination.joinpath("report.json").write_bytes(b"{}\n")
            overwritten = True
        return payload

    monkeypatch.setattr(artifact_evidence, "_read_open_file", overwrite_report)
    with pytest.raises(CandidateArtifactEvidenceError, match="changed during verification"):
        verify_type_c_candidate_artifact_evidence_bundle(destination)


@pytest.mark.parametrize("entrypoint", ["writer", "verifier"])
def test_bundle_rejects_late_mutation_of_earlier_entry(tmp_path, monkeypatch, entrypoint) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    if entrypoint == "verifier":
        write_type_c_candidate_artifact_evidence_bundle(source, destination)

    read_open_file = artifact_evidence._read_open_file
    reads_by_name: dict[str, int] = {}

    def overwrite_after_first_second_read(descriptor, name, max_bytes):
        payload = read_open_file(descriptor, name, max_bytes)
        reads_by_name[name] = reads_by_name.get(name, 0) + 1
        if name == "candidate-artifact.json" and reads_by_name[name] == 2:
            destination.joinpath("report.json").write_bytes(b"{}\n")
        return payload

    monkeypatch.setattr(
        artifact_evidence,
        "_read_open_file",
        overwrite_after_first_second_read,
    )
    with pytest.raises(CandidateArtifactEvidenceError, match="changed during verification"):
        if entrypoint == "writer":
            write_type_c_candidate_artifact_evidence_bundle(source, destination)
        else:
            verify_type_c_candidate_artifact_evidence_bundle(destination)


def test_source_reader_normalizes_descriptor_metadata_failure(tmp_path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())

    def fail_fstat(_descriptor):
        raise OSError("synthetic metadata failure")

    monkeypatch.setattr(artifact_evidence.os, "fstat", fail_fstat)
    with pytest.raises(CandidateArtifactError, match="metadata"):
        read_bounded_regular_file(source)


def test_verifier_normalizes_descriptor_metadata_failure(tmp_path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)

    def fail_fstat(_descriptor):
        raise OSError("synthetic metadata failure")

    monkeypatch.setattr(artifact_evidence.os, "fstat", fail_fstat)
    with pytest.raises(CandidateArtifactEvidenceError, match="metadata"):
        verify_type_c_candidate_artifact_evidence_bundle(destination)


@pytest.mark.parametrize("bad_name", ["bad-\ud800", "bad-\x00"])
@pytest.mark.parametrize("entrypoint", ["writer", "verifier"])
def test_public_bundle_entrypoints_normalize_invalid_paths(tmp_path, entrypoint, bad_name) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / bad_name

    with pytest.raises(CandidateArtifactEvidenceError):
        if entrypoint == "writer":
            write_type_c_candidate_artifact_evidence_bundle(source, destination)
        else:
            verify_type_c_candidate_artifact_evidence_bundle(destination)


@pytest.mark.parametrize("flag", ["O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"])
@pytest.mark.parametrize("unavailable", [None, 0])
def test_verifier_fails_closed_without_required_platform_flags(
    tmp_path, monkeypatch, flag, unavailable
) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)
    monkeypatch.setattr(artifact_evidence.os, flag, unavailable)

    with pytest.raises(CandidateArtifactEvidenceError, match="unsupported on this platform"):
        verify_type_c_candidate_artifact_evidence_bundle(destination)


def test_verifier_detects_post_verification_directory_substitution(tmp_path, monkeypatch) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"
    write_type_c_candidate_artifact_evidence_bundle(source, destination)
    displaced = tmp_path / "displaced"
    verify_descriptor = artifact_evidence._verify_type_c_candidate_artifact_evidence_descriptor

    def swapped_directory(descriptor):
        result = verify_descriptor(descriptor)
        destination.rename(displaced)
        destination.mkdir()
        return result

    monkeypatch.setattr(
        artifact_evidence,
        "_verify_type_c_candidate_artifact_evidence_descriptor",
        swapped_directory,
    )
    with pytest.raises(CandidateArtifactEvidenceError, match="changed during verification"):
        verify_type_c_candidate_artifact_evidence_bundle(destination)


def test_cli_runs_and_verifies_offline_artifact(tmp_path, capsys) -> None:
    source = tmp_path / "candidate.json"
    source.write_bytes(artifact_bytes())
    destination = tmp_path / "evidence"

    assert main(["conform-type-c-artifact", str(source), "--output-dir", str(destination)]) == 0
    assert '"status": "VERIFIED"' in capsys.readouterr().out
    assert main(["verify-type-c-artifact-bundle", str(destination)]) == 0
    assert '"status": "VERIFIED"' in capsys.readouterr().out


def test_default_artifact_size_ceiling_is_deliberately_bounded() -> None:
    assert MAX_ARTIFACT_BYTES == 262_144
