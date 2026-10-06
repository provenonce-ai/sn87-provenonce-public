from __future__ import annotations

import json

import pytest

from sn87_provenonce.cli import main, run_local_validator_demo
from sn87_provenonce.runtime import (
    verify_validator_evidence_bundle,
    write_validator_evidence_bundle,
)


def test_validator_bundle_is_deterministic_and_verifiable(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    report = run_local_validator_demo()

    first_result = write_validator_evidence_bundle(report, first)
    second_result = write_validator_evidence_bundle(report, second)

    assert first_result == second_result
    assert first_result["status"] == "VERIFIED"
    assert first_result["claim_state"] == "IMPLEMENTED_TESTED_LOCAL_RUNTIME_ONLY"
    assert first.joinpath("report.json").read_bytes() == second.joinpath("report.json").read_bytes()
    assert (
        first.joinpath("manifest.json").read_bytes()
        == second.joinpath("manifest.json").read_bytes()
    )


def test_validator_bundle_refuses_overwrite(tmp_path) -> None:
    destination = tmp_path / "evidence"
    report = run_local_validator_demo()
    write_validator_evidence_bundle(report, destination)

    with pytest.raises(FileExistsError, match="already exists"):
        write_validator_evidence_bundle(report, destination)


def test_validator_bundle_rejects_tampering(tmp_path) -> None:
    destination = tmp_path / "evidence"
    write_validator_evidence_bundle(run_local_validator_demo(), destination)
    report_path = destination / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["broadcast_capable"] = True
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="byte hash mismatch"):
        verify_validator_evidence_bundle(destination)


def test_validator_bundle_rejects_unexpected_files(tmp_path) -> None:
    destination = tmp_path / "evidence"
    write_validator_evidence_bundle(run_local_validator_demo(), destination)
    destination.joinpath("workpaper.txt").write_text("excluded", encoding="utf-8")

    with pytest.raises(ValueError, match="file set mismatch"):
        verify_validator_evidence_bundle(destination)


def test_validator_evidence_cli_creates_and_verifies_bundle(tmp_path, capsys) -> None:
    destination = tmp_path / "evidence"
    assert main(["run-local-validator", "--output-dir", str(destination)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "VERIFIED"

    assert main(["verify-validator-bundle", str(destination)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified == created


def test_validator_bundle_requires_bounded_runtime_flags(tmp_path) -> None:
    report = run_local_validator_demo()
    report["broadcast_capable"] = True

    with pytest.raises(ValueError, match="broadcast_capable=false"):
        write_validator_evidence_bundle(report, tmp_path / "evidence")
