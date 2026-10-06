from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

import sn87_provenonce.evidence as evidence_module
import sn87_provenonce.simulation.evidence as simulation_evidence
from sn87_provenonce.cli import main
from sn87_provenonce.simulation import (
    run_lane_one_simulation,
    verify_evidence_bundle,
    write_evidence_bundle,
)


def test_bundle_is_deterministic_and_verifiable(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    report = run_lane_one_simulation()
    first_result = write_evidence_bundle(report, first)
    second_result = write_evidence_bundle(report, second)

    assert first_result == second_result
    assert first_result["status"] == "VERIFIED"
    assert first.joinpath("report.json").read_bytes() == second.joinpath("report.json").read_bytes()
    assert (
        first.joinpath("manifest.json").read_bytes()
        == second.joinpath("manifest.json").read_bytes()
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("e\u0301", "é"), ((1, 2), [1, 2])],
)
def test_writer_binds_to_canonical_report_snapshot(tmp_path, value, expected) -> None:
    body = {
        "claim_state": simulation_evidence.SPEC.claim_state,
        "value": value,
    }
    report = evidence_module.seal_report(body, simulation_evidence.SPEC)
    destination = tmp_path / "evidence"

    created = evidence_module.write_bundle(report, destination, simulation_evidence.SPEC)

    assert created["status"] == "VERIFIED"
    assert evidence_module.verify_bundle(destination, simulation_evidence.SPEC) == created
    assert json.loads(destination.joinpath("report.json").read_bytes())["value"] == expected


def test_bundle_creation_refuses_to_overwrite(tmp_path) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)
    with pytest.raises(FileExistsError, match="already exists"):
        write_evidence_bundle(run_lane_one_simulation(), destination)


def test_verifier_detects_report_tampering(tmp_path) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)
    report_path = destination / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["ranking"].reverse()
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="byte hash mismatch"):
        verify_evidence_bundle(destination)


def test_verifier_rejects_unmanifested_files(tmp_path) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)
    destination.joinpath("draft-notes.txt").write_text("not part of the bundle", encoding="utf-8")
    with pytest.raises(ValueError, match="file set mismatch"):
        verify_evidence_bundle(destination)


def test_verifier_retains_and_rereads_one_report_descriptor(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)
    original_read_open_file = evidence_module._read_open_file
    report_descriptors: list[int] = []

    def counted_read_open_file(descriptor, name, max_bytes) -> bytes:
        if name == "report.json":
            report_descriptors.append(descriptor)
        return original_read_open_file(descriptor, name, max_bytes)

    monkeypatch.setattr(evidence_module, "_read_open_file", counted_read_open_file)

    assert verify_evidence_bundle(destination)["status"] == "VERIFIED"
    assert len(report_descriptors) == 2
    assert len(set(report_descriptors)) == 1


def test_writer_cannot_follow_raced_entry_symlink(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "evidence"
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"preserve-me")
    open_directory = evidence_module._open_new_bundle_directory

    def raced_directory(path):
        descriptor = open_directory(path)
        path.joinpath("report.json").symlink_to(victim)
        return descriptor

    monkeypatch.setattr(evidence_module, "_open_new_bundle_directory", raced_directory)
    with pytest.raises(evidence_module.EvidenceBundleError, match="created exclusively"):
        write_evidence_bundle(run_lane_one_simulation(), destination)
    assert victim.read_bytes() == b"preserve-me"


def test_writer_cannot_follow_raced_parent_symlink(tmp_path, monkeypatch) -> None:
    parent = tmp_path / "parent"
    destination = parent / "evidence"
    displaced = tmp_path / "displaced"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    mkdir = evidence_module.os.mkdir
    swapped = False

    def swap_parent(path, *args, **kwargs):
        nonlocal swapped
        result = mkdir(path, *args, **kwargs)
        if path == parent.name and not swapped:
            parent.rename(displaced)
            parent.symlink_to(attacker, target_is_directory=True)
            swapped = True
        return result

    monkeypatch.setattr(evidence_module.os, "mkdir", swap_parent)
    with pytest.raises(evidence_module.EvidenceBundleError, match="anchored safely"):
        write_evidence_bundle(run_lane_one_simulation(), destination)
    assert not displaced.joinpath("evidence").exists()
    assert not attacker.joinpath("evidence").exists()


def test_writer_detects_post_write_directory_substitution(tmp_path, monkeypatch) -> None:
    report = run_lane_one_simulation()
    alternate = tmp_path / "alternate"
    write_evidence_bundle(report, alternate)
    destination = tmp_path / "evidence"
    displaced = tmp_path / "displaced"
    verify_descriptor = evidence_module._verify_bundle_descriptor

    def swapped_directory(descriptor, spec):
        result = verify_descriptor(descriptor, spec)
        destination.rename(displaced)
        alternate.rename(destination)
        return result

    monkeypatch.setattr(evidence_module, "_verify_bundle_descriptor", swapped_directory)
    with pytest.raises(evidence_module.EvidenceBundleError, match="changed during creation"):
        write_evidence_bundle(report, destination)


def test_writer_rejects_membership_injection(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "evidence"
    read_open_file = evidence_module._read_open_file
    injected = False

    def inject_entry(descriptor, name, max_bytes):
        nonlocal injected
        payload = read_open_file(descriptor, name, max_bytes)
        if not injected:
            destination.joinpath("unexpected").write_bytes(b"x")
            injected = True
        return payload

    monkeypatch.setattr(evidence_module, "_read_open_file", inject_entry)
    with pytest.raises(evidence_module.EvidenceBundleError, match="membership changed"):
        write_evidence_bundle(run_lane_one_simulation(), destination)


def test_verifier_rejects_entry_overwrite(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)
    read_open_file = evidence_module._read_open_file
    overwritten = False

    def overwrite_report(descriptor, name, max_bytes):
        nonlocal overwritten
        payload = read_open_file(descriptor, name, max_bytes)
        if name == "report.json" and not overwritten:
            destination.joinpath("report.json").write_bytes(b"{}\n")
            overwritten = True
        return payload

    monkeypatch.setattr(evidence_module, "_read_open_file", overwrite_report)
    with pytest.raises(evidence_module.EvidenceBundleError, match="changed during verification"):
        verify_evidence_bundle(destination)


@pytest.mark.parametrize("entrypoint", ["writer", "verifier"])
def test_bundle_rejects_late_mutation_of_earlier_entry(tmp_path, monkeypatch, entrypoint) -> None:
    destination = tmp_path / "evidence"
    if entrypoint == "verifier":
        write_evidence_bundle(run_lane_one_simulation(), destination)
    read_open_file = evidence_module._read_open_file
    reads_by_name: dict[str, int] = {}

    def overwrite_after_manifest_second_read(descriptor, name, max_bytes):
        payload = read_open_file(descriptor, name, max_bytes)
        reads_by_name[name] = reads_by_name.get(name, 0) + 1
        if name == "manifest.json" and reads_by_name[name] == 2:
            destination.joinpath("report.json").write_bytes(b"{}\n")
        return payload

    monkeypatch.setattr(
        evidence_module,
        "_read_open_file",
        overwrite_after_manifest_second_read,
    )
    with pytest.raises(evidence_module.EvidenceBundleError, match="changed during verification"):
        if entrypoint == "writer":
            write_evidence_bundle(run_lane_one_simulation(), destination)
        else:
            verify_evidence_bundle(destination)


def test_verifier_detects_post_verification_directory_substitution(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)
    displaced = tmp_path / "displaced"
    verify_descriptor = evidence_module._verify_bundle_descriptor

    def swapped_directory(descriptor, spec):
        result = verify_descriptor(descriptor, spec)
        destination.rename(displaced)
        destination.mkdir()
        return result

    monkeypatch.setattr(evidence_module, "_verify_bundle_descriptor", swapped_directory)
    with pytest.raises(evidence_module.EvidenceBundleError, match="changed during verification"):
        verify_evidence_bundle(destination)


def test_verifier_rejects_hard_link_entries(tmp_path) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)
    report = destination / "report.json"
    linked_source = tmp_path / "linked-report.json"
    linked_source.write_bytes(report.read_bytes())
    report.unlink()
    os.link(linked_source, report)

    with pytest.raises(evidence_module.EvidenceBundleError, match="exactly one link"):
        verify_evidence_bundle(destination)


@pytest.mark.parametrize(
    ("limit_name", "match"),
    [
        ("max_report_bytes", "report exceeds"),
        ("max_manifest_bytes", "manifest exceeds"),
    ],
)
def test_output_limits_fail_before_bundle_creation(tmp_path, limit_name, match) -> None:
    destination = tmp_path / "evidence"
    constrained = replace(simulation_evidence.SPEC, **{limit_name: 1})

    with pytest.raises(evidence_module.EvidenceBundleError, match=match):
        evidence_module.write_bundle(run_lane_one_simulation(), destination, constrained)
    assert not destination.exists()


@pytest.mark.parametrize("value", [0, True, 1.0])
def test_bundle_spec_requires_positive_exact_byte_limits(value) -> None:
    with pytest.raises(ValueError, match="positive exact integer"):
        replace(simulation_evidence.SPEC, max_report_bytes=value)


def test_verifier_normalizes_descriptor_metadata_failure(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "evidence"
    write_evidence_bundle(run_lane_one_simulation(), destination)

    def fail_fstat(_descriptor):
        raise OSError("synthetic metadata failure")

    monkeypatch.setattr(evidence_module.os, "fstat", fail_fstat)
    with pytest.raises(evidence_module.EvidenceBundleError, match="metadata"):
        verify_evidence_bundle(destination)


@pytest.mark.parametrize("bad_name", ["bad-\ud800", "bad-\x00"])
@pytest.mark.parametrize("entrypoint", ["writer", "verifier"])
def test_public_entrypoints_normalize_invalid_paths(tmp_path, entrypoint, bad_name) -> None:
    destination = tmp_path / bad_name

    with pytest.raises(evidence_module.EvidenceBundleError):
        if entrypoint == "writer":
            write_evidence_bundle(run_lane_one_simulation(), destination)
        else:
            verify_evidence_bundle(destination)


def test_report_sealing_normalizes_canonicalization_depth_failure() -> None:
    nested: dict = {}
    cursor = nested
    for _ in range(2_000):
        child: dict = {}
        cursor["child"] = child
        cursor = child
    report = {
        "claim_state": simulation_evidence.SPEC.claim_state,
        "nested": nested,
    }

    with pytest.raises(evidence_module.EvidenceBundleError, match="cannot be committed"):
        evidence_module.seal_report(report, simulation_evidence.SPEC)


@pytest.mark.parametrize("operation", ["seal", "verify"])
def test_report_operations_normalize_mapping_runtime_failure(operation) -> None:
    class ExplodingDict(dict):
        def items(self):
            raise RuntimeError("synthetic canonicalization failure")

    report = {
        "claim_state": simulation_evidence.SPEC.claim_state,
        "nested": ExplodingDict(),
    }
    if operation == "verify":
        report["report_commitment"] = "sha256:" + "0" * 64

    with pytest.raises(evidence_module.EvidenceBundleError, match="report cannot be"):
        if operation == "seal":
            evidence_module.seal_report(report, simulation_evidence.SPEC)
        else:
            evidence_module.verify_report(report, simulation_evidence.SPEC)


def test_cli_creates_and_verifies_bundle(tmp_path, capsys) -> None:
    destination = tmp_path / "evidence"
    assert main(["simulate-lane-one", "--output-dir", str(destination)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "VERIFIED"

    assert main(["verify-simulation-bundle", str(destination)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified == created
