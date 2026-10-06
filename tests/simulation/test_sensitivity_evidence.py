from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

import sn87_provenonce.simulation.sensitivity_evidence as sensitivity_evidence
import sn87_provenonce.simulation.sensitivity_evidence_models as evidence_models
from sn87_provenonce.cli import main
from sn87_provenonce.protocol.v0alpha1 import canonical_json_bytes, canonical_sha256
from sn87_provenonce.simulation import (
    ComponentValue,
    ComponentVector,
    EstimatorKind,
    UnitRatio,
    create_estimator_spec,
    create_sensitivity_analysis_spec,
)
from sn87_provenonce.simulation.lane_one_profile import ExactRatio
from sn87_provenonce.simulation.sensitivity_analysis import (
    MAX_ANALYSIS_JSON_BYTES,
    RESULT_COMMITMENT_DOMAIN,
)
from sn87_provenonce.simulation.sensitivity_evidence import (
    CLAIM_STATE,
    SensitivityEvidenceError,
    read_sensitivity_spec,
    run_sensitivity_analysis_bytes,
    verify_sensitivity_evidence_bundle,
    write_sensitivity_evidence_bundle,
)
from sn87_provenonce.simulation.sensitivity_evidence_models import (
    parse_sensitivity_evidence_manifest,
    parse_sensitivity_evidence_report,
)

PROFILE_COMMITMENT = canonical_sha256(
    {"profile": "evidence-test"}, domain="SN87:TEST_TASK_PROFILE:v0alpha1"
)


def ratio(numerator: int, denominator: int = 1) -> ExactRatio:
    return ExactRatio(numerator=numerator, denominator=denominator)


def vector(vector_id: str, detection: tuple[int, int], evidence: tuple[int, int]):
    return ComponentVector(
        vector_id=vector_id,
        components=(
            ComponentValue(
                component="detection",
                value=UnitRatio(numerator=detection[0], denominator=detection[1]),
            ),
            ComponentValue(
                component="evidence",
                value=UnitRatio(numerator=evidence[0], denominator=evidence[1]),
            ),
        ),
    )


def spec_payload() -> dict:
    arithmetic = create_estimator_spec(
        estimator_id="arithmetic",
        task_profile_commitment=PROFILE_COMMITMENT,
        kind=EstimatorKind.WEIGHTED_ARITHMETIC_MEAN,
        component_weights={"detection": ratio(1), "evidence": ratio(1)},
    )
    harmonic = create_estimator_spec(
        estimator_id="harmonic",
        task_profile_commitment=PROFILE_COMMITMENT,
        kind=EstimatorKind.WEIGHTED_HARMONIC_MEAN,
        component_weights={"detection": ratio(1), "evidence": ratio(1)},
    )
    return create_sensitivity_analysis_spec(
        task_profile_commitment=PROFILE_COMMITMENT,
        estimator_specs=(arithmetic, harmonic),
        baseline=vector("baseline", (1, 2), (1, 2)),
        scenarios=(
            vector("detection-up", (1, 1), (1, 2)),
            vector("tradeoff", (1, 4), (1, 1)),
        ),
    ).to_payload()


def spec_bytes() -> bytes:
    return canonical_json_bytes(spec_payload()) + b"\n"


def test_report_preserves_raw_identity_and_non_normative_boundary() -> None:
    canonical = spec_bytes()
    indented = json.dumps(spec_payload(), indent=2, ensure_ascii=False).encode()
    canonical_report = run_sensitivity_analysis_bytes(canonical)
    indented_report = run_sensitivity_analysis_bytes(indented)

    assert canonical_report["claim_state"] == CLAIM_STATE
    assert canonical_report["source_spec_sha256"] != indented_report["source_spec_sha256"]
    assert (
        canonical_report["normalized_spec_commitment"]
        == indented_report["normalized_spec_commitment"]
    )
    assert (
        canonical_report["analysis_result"]["result_commitment"]
        == indented_report["analysis_result"]["result_commitment"]
    )
    assert all(value is False for value in canonical_report["boundaries"].values())


@pytest.mark.parametrize("payload", [b"", b" \n\t", b"\xef\xbb\xbf{}", b"not-json"])
def test_report_rejects_invalid_source_bytes(payload) -> None:
    with pytest.raises(SensitivityEvidenceError):
        run_sensitivity_analysis_bytes(payload)


def test_every_bytes_entrypoint_enforces_source_ceiling() -> None:
    base = spec_bytes()
    at_limit = base + b" " * (MAX_ANALYSIS_JSON_BYTES - len(base))
    over_limit = at_limit + b" "
    assert run_sensitivity_analysis_bytes(at_limit)["claim_state"] == CLAIM_STATE
    with pytest.raises(SensitivityEvidenceError, match="exceeds"):
        run_sensitivity_analysis_bytes(over_limit)
    with pytest.raises(SensitivityEvidenceError, match="must be bytes"):
        run_sensitivity_analysis_bytes(bytearray(base))  # type: ignore[arg-type]


def test_bundle_preserves_source_and_reconstructs_report(tmp_path) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(json.dumps(spec_payload(), indent=2).encode())
    destination = tmp_path / "evidence"
    created = write_sensitivity_evidence_bundle(source, destination)

    assert destination.joinpath("sensitivity-spec.json").read_bytes() == source.read_bytes()
    assert created["status"] == "VERIFIED"
    assert verify_sensitivity_evidence_bundle(destination) == created
    with pytest.raises(FileExistsError):
        write_sensitivity_evidence_bundle(source, destination)


def test_public_vector_bundle_bytes_remain_contract_compatible(tmp_path) -> None:
    source = (
        Path(__file__).parents[2]
        / "examples"
        / "sensitivity"
        / "illustrative-sensitivity-spec.json"
    )
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)

    assert {
        name: sensitivity_evidence.raw_sha256(destination.joinpath(name).read_bytes())
        for name in sorted(sensitivity_evidence.EXPECTED_FILES)
    } == {
        "manifest.json": "sha256:726d1b0ab2239baf9cc1de69afefe03e9980aee564a76c09f3574deaef4c8bac",
        "report.json": "sha256:95ff7ea0168698de6fbdbaac2d7593694f671cf9c806bf55a057f73b3809b3ac",
        "sensitivity-spec.json": (
            "sha256:a79270a6ae0032410e34d585ef6b74b0432f39ecb91339338f2e87c8f8d6d56b"
        ),
    }


@pytest.mark.parametrize("name", ["sensitivity-spec.json", "report.json", "manifest.json"])
def test_bundle_rejects_tampering_of_every_file(tmp_path, name) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)
    target = destination / name
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(SensitivityEvidenceError):
        verify_sensitivity_evidence_bundle(destination)


@pytest.mark.parametrize("name", ["report.json", "manifest.json"])
def test_bundle_normalizes_non_object_json_failures(tmp_path, name) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)
    destination.joinpath(name).write_bytes(b"[]\n")

    with pytest.raises(SensitivityEvidenceError, match="root must be an object"):
        verify_sensitivity_evidence_bundle(destination)


def test_bundle_rejects_unexpected_and_symlink_entries(tmp_path) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)
    destination.joinpath("unexpected").write_text("x")
    with pytest.raises(SensitivityEvidenceError, match="file set mismatch"):
        verify_sensitivity_evidence_bundle(destination)

    destination.joinpath("unexpected").unlink()
    report = destination / "report.json"
    saved = report.read_bytes()
    report.unlink()
    report.symlink_to(source)
    with pytest.raises(SensitivityEvidenceError, match="opened safely"):
        verify_sensitivity_evidence_bundle(destination)
    report.unlink()
    report.write_bytes(saved)


def test_bundle_rejects_semantically_equivalent_noncanonical_model_form(tmp_path) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)

    report_path = destination / "report.json"
    report = json.loads(report_path.read_bytes())
    report["analysis_result"]["analysis_spec"]["baseline"]["components"][0]["value"] = {
        "denominator": 4,
        "numerator": 2,
    }
    report_bytes = canonical_json_bytes(report) + b"\n"
    report_path.write_bytes(report_bytes)

    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["report.json"] = sensitivity_evidence.raw_sha256(report_bytes)
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")

    with pytest.raises(SensitivityEvidenceError, match="exact validated form"):
        verify_sensitivity_evidence_bundle(destination)


def test_bundle_writer_cannot_follow_raced_entry_symlink(tmp_path, monkeypatch) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"preserve-me")
    open_directory = sensitivity_evidence._open_new_bundle_directory

    def raced_directory(path):
        descriptor = open_directory(path)
        path.joinpath("report.json").symlink_to(victim)
        return descriptor

    monkeypatch.setattr(sensitivity_evidence, "_open_new_bundle_directory", raced_directory)
    with pytest.raises(SensitivityEvidenceError, match="created exclusively"):
        write_sensitivity_evidence_bundle(source, destination)
    assert victim.read_bytes() == b"preserve-me"


def test_bundle_writer_cannot_follow_raced_parent_symlink(tmp_path, monkeypatch) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    parent = tmp_path / "parent"
    destination = parent / "evidence"
    displaced = tmp_path / "displaced"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    mkdir = sensitivity_evidence.os.mkdir
    swapped = False

    def swap_parent(path, *args, **kwargs):
        nonlocal swapped
        result = mkdir(path, *args, **kwargs)
        if path == parent.name and not swapped:
            parent.rename(displaced)
            parent.symlink_to(attacker, target_is_directory=True)
            swapped = True
        return result

    monkeypatch.setattr(sensitivity_evidence.os, "mkdir", swap_parent)
    with pytest.raises(SensitivityEvidenceError, match="anchored safely"):
        write_sensitivity_evidence_bundle(source, destination)
    assert not displaced.joinpath("evidence").exists()
    assert not attacker.joinpath("evidence").exists()


def test_verifier_rejects_intermediate_parent_symlink(tmp_path) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    real_parent = tmp_path / "real-parent"
    destination = real_parent / "evidence"
    write_sensitivity_evidence_bundle(source, destination)
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(SensitivityEvidenceError, match="anchored safely"):
        verify_sensitivity_evidence_bundle(alias / "evidence")


def test_bundle_writer_detects_post_write_directory_substitution(tmp_path, monkeypatch) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    alternate_source = tmp_path / "alternate.json"
    alternate_payload = spec_payload()
    alternate_payload["baseline"]["components"][0]["value"] = {
        "numerator": 1,
        "denominator": 4,
    }
    alternate_source.write_bytes(canonical_json_bytes(alternate_payload) + b"\n")
    alternate = tmp_path / "alternate-bundle"
    write_sensitivity_evidence_bundle(alternate_source, alternate)

    destination = tmp_path / "evidence"
    displaced = tmp_path / "displaced"
    verify_descriptor = sensitivity_evidence._verify_sensitivity_evidence_descriptor

    def swapped_directory(descriptor):
        result = verify_descriptor(descriptor)
        destination.rename(displaced)
        alternate.rename(destination)
        return result

    monkeypatch.setattr(
        sensitivity_evidence,
        "_verify_sensitivity_evidence_descriptor",
        swapped_directory,
    )
    with pytest.raises(SensitivityEvidenceError, match="changed during creation"):
        write_sensitivity_evidence_bundle(source, destination)

    assert displaced.joinpath("sensitivity-spec.json").read_bytes() == source.read_bytes()
    assert (
        destination.joinpath("sensitivity-spec.json").read_bytes() == alternate_source.read_bytes()
    )


def test_writer_rejects_membership_injection_during_descriptor_verification(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    read_open_file = sensitivity_evidence._read_open_file
    injected = False

    def inject_entry(descriptor, name, max_bytes):
        nonlocal injected
        payload = read_open_file(descriptor, name, max_bytes)
        if not injected:
            destination.joinpath("unexpected").write_bytes(b"x")
            injected = True
        return payload

    monkeypatch.setattr(sensitivity_evidence, "_read_open_file", inject_entry)
    with pytest.raises(SensitivityEvidenceError, match="membership changed"):
        write_sensitivity_evidence_bundle(source, destination)


def test_verifier_rejects_entry_overwrite_during_descriptor_verification(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)
    read_open_file = sensitivity_evidence._read_open_file
    overwritten = False

    def overwrite_report(descriptor, name, max_bytes):
        nonlocal overwritten
        payload = read_open_file(descriptor, name, max_bytes)
        if name == "report.json" and not overwritten:
            destination.joinpath("report.json").write_bytes(b"{}\n")
            overwritten = True
        return payload

    monkeypatch.setattr(sensitivity_evidence, "_read_open_file", overwrite_report)
    with pytest.raises(SensitivityEvidenceError, match="changed during verification"):
        verify_sensitivity_evidence_bundle(destination)


@pytest.mark.parametrize("entrypoint", ["writer", "verifier"])
def test_bundle_rejects_late_mutation_of_earlier_entry(tmp_path, monkeypatch, entrypoint) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    if entrypoint == "verifier":
        write_sensitivity_evidence_bundle(source, destination)

    read_open_file = sensitivity_evidence._read_open_file
    reads_by_name: dict[str, int] = {}

    def overwrite_after_last_second_read(descriptor, name, max_bytes):
        payload = read_open_file(descriptor, name, max_bytes)
        reads_by_name[name] = reads_by_name.get(name, 0) + 1
        if name == "sensitivity-spec.json" and reads_by_name[name] == 2:
            destination.joinpath("report.json").write_bytes(b"{}\n")
        return payload

    monkeypatch.setattr(
        sensitivity_evidence,
        "_read_open_file",
        overwrite_after_last_second_read,
    )
    with pytest.raises(SensitivityEvidenceError, match="changed during verification"):
        if entrypoint == "writer":
            write_sensitivity_evidence_bundle(source, destination)
        else:
            verify_sensitivity_evidence_bundle(destination)


@pytest.mark.parametrize("name", ["report.json", "manifest.json"])
def test_bundle_normalizes_invalid_unicode_errors(tmp_path, name) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)
    destination.joinpath(name).write_bytes(b'{"x":"\\ud800"}\n')
    with pytest.raises(SensitivityEvidenceError, match="not canonical"):
        verify_sensitivity_evidence_bundle(destination)


def test_source_reader_rejects_symlink_directory_and_fifo(tmp_path) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    symlink = tmp_path / "link.json"
    symlink.symlink_to(source)
    fifo = tmp_path / "sensitivity.fifo"
    os.mkfifo(fifo)
    for invalid in (symlink, tmp_path, fifo):
        with pytest.raises(SensitivityEvidenceError, match="regular file"):
            read_sensitivity_spec(invalid)


def test_source_reader_normalizes_descriptor_metadata_failure(tmp_path, monkeypatch) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())

    def fail_fstat(_descriptor):
        raise OSError("synthetic metadata failure")

    monkeypatch.setattr(sensitivity_evidence.os, "fstat", fail_fstat)
    with pytest.raises(SensitivityEvidenceError, match="metadata"):
        read_sensitivity_spec(source)


def test_verifier_normalizes_descriptor_metadata_failure(tmp_path, monkeypatch) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)

    def fail_fstat(_descriptor):
        raise OSError("synthetic metadata failure")

    monkeypatch.setattr(sensitivity_evidence.os, "fstat", fail_fstat)
    with pytest.raises(SensitivityEvidenceError, match="metadata"):
        verify_sensitivity_evidence_bundle(destination)


@pytest.mark.parametrize("bad_name", ["bad-\ud800", "bad-\x00"])
@pytest.mark.parametrize("entrypoint", ["writer", "verifier"])
def test_public_entrypoints_normalize_invalid_paths(tmp_path, entrypoint, bad_name) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / bad_name

    with pytest.raises(SensitivityEvidenceError):
        if entrypoint == "writer":
            write_sensitivity_evidence_bundle(source, destination)
        else:
            verify_sensitivity_evidence_bundle(destination)


@pytest.mark.parametrize("flag", ["O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"])
@pytest.mark.parametrize("unavailable", [None, 0])
def test_verifier_fails_closed_without_required_platform_flags(
    tmp_path, monkeypatch, flag, unavailable
) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)
    monkeypatch.setattr(sensitivity_evidence.os, flag, unavailable)

    with pytest.raises(SensitivityEvidenceError, match="unsupported on this platform"):
        verify_sensitivity_evidence_bundle(destination)


def test_invalid_source_creates_no_bundle(tmp_path) -> None:
    source = tmp_path / "invalid.json"
    source.write_bytes(b"{}")
    destination = tmp_path / "evidence"
    with pytest.raises(SensitivityEvidenceError):
        write_sensitivity_evidence_bundle(source, destination)
    assert not destination.exists()


def test_report_limit_is_enforced_before_bundle_creation(tmp_path, monkeypatch) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    monkeypatch.setattr(sensitivity_evidence, "MAX_REPORT_BYTES", 1)

    with pytest.raises(SensitivityEvidenceError, match="report exceeds"):
        run_sensitivity_analysis_bytes(source.read_bytes())
    with pytest.raises(SensitivityEvidenceError, match="report exceeds"):
        write_sensitivity_evidence_bundle(source, destination)
    assert not destination.exists()


def test_cli_runs_and_verifies_sensitivity_bundle(tmp_path, capsys) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"

    assert main(["analyze-sensitivity", str(source)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["claim_state"] == CLAIM_STATE

    assert (
        main(
            [
                "analyze-sensitivity",
                str(source),
                "--output-dir",
                str(destination),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED"
    assert main(["verify-sensitivity-bundle", str(destination)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED"


def test_report_and_manifest_contracts_are_strict_and_bounded(tmp_path, monkeypatch) -> None:
    source = tmp_path / "sensitivity.json"
    source.write_bytes(spec_bytes())
    destination = tmp_path / "evidence"
    write_sensitivity_evidence_bundle(source, destination)

    report_bytes = destination.joinpath("report.json").read_bytes()
    manifest_bytes = destination.joinpath("manifest.json").read_bytes()
    report = parse_sensitivity_evidence_report(report_bytes)
    manifest = parse_sensitivity_evidence_manifest(manifest_bytes)
    assert report.source_spec_sha256 == manifest.source_spec_sha256
    assert report.report_commitment == manifest.report_commitment
    assert report.analysis_result.result_commitment == manifest.result_commitment

    bypassed_result = report.analysis_result.model_copy(update={"ranking_defined": True})
    bypassed_report = report.model_copy(update={"analysis_result": bypassed_result})
    with pytest.raises(ValidationError, match="boolean false"):
        evidence_models.SensitivityEvidenceReport.model_validate(bypassed_report)
    bypassed_files = manifest.files.model_copy(
        update={"sensitivity_spec_json": "sha256:" + "0" * 64}
    )
    bypassed_manifest = manifest.model_copy(update={"files": bypassed_files})
    with pytest.raises(ValidationError, match="source hash fields disagree"):
        evidence_models.SensitivityEvidenceManifest.model_validate(bypassed_manifest)

    report_payload = json.loads(report_bytes)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        parse_sensitivity_evidence_report(
            canonical_json_bytes(report_payload | {"unexpected": False})
        )
    float_limit_payload = json.loads(report_bytes)
    float_limit_payload["limits"]["max_source_bytes_inclusive"] = 1_000_000.0
    with pytest.raises(ValidationError, match="exact integers"):
        parse_sensitivity_evidence_report(canonical_json_bytes(float_limit_payload))
    report_payload["boundaries"]["network"] = 0
    with pytest.raises(ValidationError, match="boolean false"):
        parse_sensitivity_evidence_report(canonical_json_bytes(report_payload))

    manifest_payload = json.loads(manifest_bytes)
    manifest_payload["source_spec_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="source hash fields disagree"):
        parse_sensitivity_evidence_manifest(canonical_json_bytes(manifest_payload))
    with pytest.raises(ValueError, match="root must be an object"):
        parse_sensitivity_evidence_manifest(b"[]")
    with pytest.raises(ValueError):
        parse_sensitivity_evidence_manifest(b'{"bundle_version":1,"bundle_version":2}')

    monkeypatch.setattr(evidence_models, "MAX_REPORT_BYTES", 1)
    monkeypatch.setattr(evidence_models, "MAX_MANIFEST_BYTES", 1)
    with pytest.raises(ValueError, match="cannot exceed 1 bytes"):
        parse_sensitivity_evidence_report(report_bytes)
    with pytest.raises(ValueError, match="cannot exceed 1 bytes"):
        parse_sensitivity_evidence_manifest(manifest_bytes)


def test_report_parser_rejects_self_committed_false_scenario_result() -> None:
    report_payload = run_sensitivity_analysis_bytes(spec_bytes())
    scenario = report_payload["analysis_result"]["sensitivity_results"][0]["scenarios"][0]
    scenario.update(
        {
            "changed_components": ["NOT_A_SPEC_COMPONENT"],
            "estimate": {"numerator": 0, "denominator": 1},
            "delta_from_baseline": {"numerator": 0, "denominator": 1},
            "direction": "UNCHANGED",
        }
    )
    result_body = {
        key: value
        for key, value in report_payload["analysis_result"].items()
        if key != "result_commitment"
    }
    report_payload["analysis_result"]["result_commitment"] = canonical_sha256(
        result_body, domain=RESULT_COMMITMENT_DOMAIN
    )
    report_body = {
        key: value for key, value in report_payload.items() if key != "report_commitment"
    }
    report_payload["report_commitment"] = canonical_sha256(
        report_body, domain=sensitivity_evidence.REPORT_COMMITMENT_DOMAIN
    )

    with pytest.raises(ValidationError, match="does not match its embedded specification"):
        parse_sensitivity_evidence_report(canonical_json_bytes(report_payload) + b"\n")


def test_generated_evidence_schemas_close_object_shapes() -> None:
    schema_directory = Path(__file__).parents[2] / "protocol" / "v0alpha1" / "schemas"
    result_schema = json.loads(
        schema_directory.joinpath("sensitivity-analysis-result.schema.json").read_bytes()
    )
    report_schema = json.loads(
        schema_directory.joinpath("sensitivity-evidence-report.schema.json").read_bytes()
    )
    manifest_schema = json.loads(
        schema_directory.joinpath("sensitivity-evidence-manifest.schema.json").read_bytes()
    )
    assert result_schema["additionalProperties"] is False
    assert report_schema["additionalProperties"] is False
    assert manifest_schema["additionalProperties"] is False
    assert report_schema["properties"]["analysis_result"]["$ref"].endswith(
        "/SensitivityAnalysisResult"
    )
    files_reference = manifest_schema["properties"]["files"]["$ref"]
    files_name = files_reference.rsplit("/", 1)[-1]
    assert manifest_schema["$defs"][files_name]["additionalProperties"] is False
