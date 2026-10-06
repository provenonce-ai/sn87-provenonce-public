"""Create-only evidence for bounded offline sensitivity analysis."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sn87_provenonce import evidence_filesystem
from sn87_provenonce.protocol.v0alpha1 import (
    canonical_json_bytes,
    canonical_sha256,
    parse_json_strict,
)
from sn87_provenonce.simulation.sensitivity_analysis import (
    MAX_ANALYSIS_JSON_BYTES,
    analyze_sensitivity,
    parse_sensitivity_analysis_spec,
)
from sn87_provenonce.simulation.sensitivity_evidence_models import (
    BUNDLE_VERSION,
    CLAIM_STATE,
    MAX_MANIFEST_BYTES,
    MAX_REPORT_BYTES,
    REPORT_COMMITMENT_DOMAIN,
    REPORT_VERSION,
    SensitivityEvidenceManifest,
    SensitivityEvidenceReport,
    parse_sensitivity_evidence_manifest,
    parse_sensitivity_evidence_report,
)

EXPECTED_FILES = frozenset({"manifest.json", "report.json", "sensitivity-spec.json"})


class SensitivityEvidenceError(ValueError):
    """A bounded, caller-safe sensitivity evidence failure."""


def raw_sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _read_regular_file(path: Path, max_bytes: int, *, label: str) -> bytes:
    return evidence_filesystem.read_bounded_regular_file(
        path,
        max_bytes,
        label=label,
        error_type=SensitivityEvidenceError,
    )


def _open_regular_file_at(directory_descriptor: int, name: str, max_bytes: int) -> int:
    return evidence_filesystem.open_regular_file_at(
        directory_descriptor,
        name,
        max_bytes,
        error_type=SensitivityEvidenceError,
        label_prefix="bundle entry",
    )


def _read_open_file(descriptor: int, name: str, max_bytes: int) -> bytes:
    return evidence_filesystem.read_open_file(
        descriptor,
        name,
        max_bytes,
        error_type=SensitivityEvidenceError,
        label_prefix="bundle entry",
    )


def _stable_stat(metadata: os.stat_result) -> tuple[int, ...]:
    return evidence_filesystem.stable_stat(metadata)


def _fstat_descriptor(descriptor: int, label: str) -> os.stat_result:
    return evidence_filesystem.fstat_descriptor(
        descriptor, label, error_type=SensitivityEvidenceError
    )


def _close_descriptor(descriptor: int) -> None:
    evidence_filesystem.close_descriptor(descriptor)


def read_sensitivity_spec(path: Path) -> bytes:
    """Read one exact regular-file snapshot without following links."""

    return _read_regular_file(path, MAX_ANALYSIS_JSON_BYTES, label="sensitivity spec")


def run_sensitivity_analysis_bytes(payload: bytes) -> dict[str, Any]:
    """Validate and analyze one exact sensitivity-spec byte snapshot."""

    if not isinstance(payload, bytes):
        raise SensitivityEvidenceError("sensitivity spec payload must be bytes")
    if len(payload) > MAX_ANALYSIS_JSON_BYTES:
        raise SensitivityEvidenceError(
            f"sensitivity spec exceeds the {MAX_ANALYSIS_JSON_BYTES}-byte limit"
        )
    if not payload or not payload.strip():
        raise SensitivityEvidenceError("sensitivity spec is empty")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise SensitivityEvidenceError("sensitivity spec must not contain a UTF-8 BOM")
    try:
        spec = parse_sensitivity_analysis_spec(payload)
        result = analyze_sensitivity(spec=spec)
    except SensitivityEvidenceError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        ValidationError,
        ValueError,
    ) as error:
        raise SensitivityEvidenceError(f"invalid sensitivity spec: {error}") from error

    body: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "claim_state": CLAIM_STATE,
        "source_spec_sha256": raw_sha256(payload),
        "normalized_spec_commitment": spec.commitment,
        "limits": {
            "max_source_bytes_inclusive": MAX_ANALYSIS_JSON_BYTES,
            "max_report_bytes_inclusive": MAX_REPORT_BYTES,
            "max_manifest_bytes_inclusive": MAX_MANIFEST_BYTES,
        },
        "boundaries": {
            "source_origin_proven": False,
            "production_policy_selected": False,
            "estimator_preference_defined": False,
            "normative_scoring": False,
            "winner_selected": False,
            "ranking_defined": False,
            "weight_policy_defined": False,
            "g1_acceptance": False,
            "hidden_truth": False,
            "network": False,
            "wallet": False,
            "chain_action_defined": False,
            "testnet": False,
            "production_evidence": False,
        },
        "analysis_result": result,
    }
    candidate_report = body | {
        "report_commitment": canonical_sha256(body, domain=REPORT_COMMITMENT_DOMAIN)
    }
    try:
        report_size = len(canonical_json_bytes(candidate_report)) + 1
    except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        raise SensitivityEvidenceError(f"sensitivity report is not canonical: {error}") from error
    if report_size > MAX_REPORT_BYTES:
        raise SensitivityEvidenceError(
            f"sensitivity report exceeds the {MAX_REPORT_BYTES}-byte limit"
        )
    try:
        return SensitivityEvidenceReport.model_validate(candidate_report).to_payload()
    except ValidationError as error:  # pragma: no cover - internal contract assertion
        raise SensitivityEvidenceError(f"sensitivity report contract failed: {error}") from error


def run_sensitivity_analysis(path: Path) -> dict[str, Any]:
    return run_sensitivity_analysis_bytes(read_sensitivity_spec(path))


def _manifest(source_bytes: bytes, report_bytes: bytes, report: dict[str, Any]) -> dict[str, Any]:
    return SensitivityEvidenceManifest.model_validate(
        {
            "bundle_version": BUNDLE_VERSION,
            "claim_state": CLAIM_STATE,
            "files": {
                "sensitivity-spec.json": raw_sha256(source_bytes),
                "report.json": raw_sha256(report_bytes),
            },
            "report_commitment": report["report_commitment"],
            "source_spec_sha256": report["source_spec_sha256"],
            "normalized_spec_commitment": report["normalized_spec_commitment"],
            "result_commitment": report["analysis_result"]["result_commitment"],
        }
    ).to_payload()


def _open_new_bundle_directory(destination: Path) -> int:
    descriptor, _absolute_destination = evidence_filesystem.open_new_bundle_directory(
        destination, error_type=SensitivityEvidenceError
    )
    return descriptor


def _write_new_bundle_file(directory_descriptor: int, name: str, payload: bytes) -> None:
    evidence_filesystem.write_new_bundle_file(
        directory_descriptor,
        name,
        payload,
        error_type=SensitivityEvidenceError,
        label_prefix="bundle entry",
    )


def write_sensitivity_evidence_bundle(source: Path, destination: Path) -> dict[str, Any]:
    """Validate once, then preserve and analyze the same exact source byte snapshot."""

    source_bytes = read_sensitivity_spec(source)
    report = run_sensitivity_analysis_bytes(source_bytes)
    try:
        report_bytes = canonical_json_bytes(report) + b"\n"
        manifest_bytes = canonical_json_bytes(_manifest(source_bytes, report_bytes, report)) + b"\n"
    except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        raise SensitivityEvidenceError(f"sensitivity evidence is not canonical: {error}") from error
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise SensitivityEvidenceError("sensitivity report exceeds its byte limit")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise SensitivityEvidenceError("sensitivity manifest exceeds its byte limit")
    absolute_destination = evidence_filesystem.absolute_path(
        destination,
        error_type=SensitivityEvidenceError,
        label="evidence destination",
    )
    directory_descriptor = _open_new_bundle_directory(absolute_destination)
    try:
        _write_new_bundle_file(directory_descriptor, "sensitivity-spec.json", source_bytes)
        _write_new_bundle_file(directory_descriptor, "report.json", report_bytes)
        _write_new_bundle_file(directory_descriptor, "manifest.json", manifest_bytes)
        try:
            os.fsync(directory_descriptor)
        except OSError as error:
            raise SensitivityEvidenceError("bundle directory could not be synchronized") from error
        result = _verify_sensitivity_evidence_descriptor(directory_descriptor)
        if result["source_spec_sha256"] != raw_sha256(source_bytes):
            raise SensitivityEvidenceError("verified bundle source differs from the input snapshot")
        if result["report_sha256"] != raw_sha256(report_bytes):
            raise SensitivityEvidenceError("verified bundle report differs from the written report")
        if not _directory_descriptor_matches_path(directory_descriptor, absolute_destination):
            raise SensitivityEvidenceError("bundle destination changed during creation")
        return result
    finally:
        _close_descriptor(directory_descriptor)


def _directory_descriptor_matches_path(directory_descriptor: int, path: Path) -> bool:
    return evidence_filesystem.directory_descriptor_matches_path(directory_descriptor, path)


def _verify_sensitivity_evidence_descriptor(
    directory_descriptor: int,
) -> dict[str, Any]:
    """Verify and reconstruct one bundle through an anchored directory descriptor."""

    try:
        actual_files = set(os.listdir(directory_descriptor))
    except OSError as error:
        raise SensitivityEvidenceError("bundle directory could not be listed safely") from error
    if actual_files != EXPECTED_FILES:
        raise SensitivityEvidenceError(
            f"bundle file set mismatch: expected {sorted(EXPECTED_FILES)}, "
            f"found {sorted(actual_files)}"
        )
    initial_directory_stat = _stable_stat(
        _fstat_descriptor(directory_descriptor, "bundle directory")
    )

    limits = {
        "sensitivity-spec.json": MAX_ANALYSIS_JSON_BYTES,
        "report.json": MAX_REPORT_BYTES,
        "manifest.json": MAX_MANIFEST_BYTES,
    }
    descriptors: dict[str, int] = {}
    try:
        for name in sorted(EXPECTED_FILES):
            descriptors[name] = _open_regular_file_at(directory_descriptor, name, limits[name])
        initial_stats = {
            name: _stable_stat(_fstat_descriptor(descriptor, f"bundle entry {name}"))
            for name, descriptor in descriptors.items()
        }
        snapshots = {
            name: _read_open_file(descriptor, name, limits[name])
            for name, descriptor in descriptors.items()
        }
        source_bytes = snapshots["sensitivity-spec.json"]
        report_bytes = snapshots["report.json"]
        manifest_bytes = snapshots["manifest.json"]
        try:
            raw_manifest = parse_json_strict(manifest_bytes)
            raw_report = parse_json_strict(report_bytes)
        except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
            raise SensitivityEvidenceError(f"invalid bundle JSON: {error}") from error
        try:
            canonical_manifest = canonical_json_bytes(raw_manifest) + b"\n"
            canonical_report = canonical_json_bytes(raw_report) + b"\n"
        except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
            raise SensitivityEvidenceError(f"bundle JSON is not canonical: {error}") from error
        if manifest_bytes != canonical_manifest:
            raise SensitivityEvidenceError("manifest.json is not the exact canonical snapshot")
        if report_bytes != canonical_report:
            raise SensitivityEvidenceError("report.json is not the exact canonical snapshot")
        try:
            manifest = parse_sensitivity_evidence_manifest(manifest_bytes).to_payload()
            report = parse_sensitivity_evidence_report(report_bytes).to_payload()
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise SensitivityEvidenceError(f"invalid bundle JSON: {error}") from error
        if canonical_json_bytes(manifest) + b"\n" != manifest_bytes:
            raise SensitivityEvidenceError("manifest.json is not the exact validated form")
        if canonical_json_bytes(report) + b"\n" != report_bytes:
            raise SensitivityEvidenceError("report.json is not the exact validated form")
        if manifest.get("bundle_version") != BUNDLE_VERSION:
            raise SensitivityEvidenceError("unsupported sensitivity evidence bundle version")
        if manifest.get("claim_state") != CLAIM_STATE or report.get("claim_state") != CLAIM_STATE:
            raise SensitivityEvidenceError("sensitivity evidence claim state mismatch")
        expected_files = {
            "sensitivity-spec.json": raw_sha256(source_bytes),
            "report.json": raw_sha256(report_bytes),
        }
        if manifest.get("files") != expected_files:
            raise SensitivityEvidenceError("sensitivity evidence file hash mismatch")
        expected_report = run_sensitivity_analysis_bytes(source_bytes)
        if report != expected_report:
            raise SensitivityEvidenceError("report does not match exact source reconstruction")
        if manifest != _manifest(source_bytes, report_bytes, report):
            raise SensitivityEvidenceError("manifest does not match the reconstructed bundle")

        closing_snapshots = {
            name: _read_open_file(descriptor, name, limits[name])
            for name, descriptor in descriptors.items()
        }
        try:
            final_descriptor_stats = {
                name: _stable_stat(_fstat_descriptor(descriptor, f"bundle entry {name}"))
                for name, descriptor in descriptors.items()
            }
            final_named_stats = {
                name: _stable_stat(
                    os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                )
                for name in descriptors
            }
        except (OSError, UnicodeError, ValueError) as error:
            raise SensitivityEvidenceError("bundle entry changed during verification") from error
        for name in descriptors:
            if (
                closing_snapshots[name] != snapshots[name]
                or final_descriptor_stats[name] != initial_stats[name]
                or final_named_stats[name] != initial_stats[name]
            ):
                raise SensitivityEvidenceError(f"bundle entry changed during verification: {name}")

        try:
            closing_files = set(os.listdir(directory_descriptor))
            closing_directory_stat = _stable_stat(
                _fstat_descriptor(directory_descriptor, "bundle directory")
            )
        except (OSError, UnicodeError, ValueError) as error:
            raise SensitivityEvidenceError(
                "bundle directory could not be finalized safely"
            ) from error
        if closing_files != EXPECTED_FILES:
            raise SensitivityEvidenceError("bundle membership changed during verification")
        if closing_directory_stat != initial_directory_stat:
            raise SensitivityEvidenceError("bundle directory changed during verification")
        return {
            "status": "VERIFIED",
            "bundle_version": BUNDLE_VERSION,
            "claim_state": CLAIM_STATE,
            "files": sorted(actual_files),
            "source_spec_sha256": report["source_spec_sha256"],
            "normalized_spec_commitment": report["normalized_spec_commitment"],
            "result_commitment": report["analysis_result"]["result_commitment"],
            "report_sha256": raw_sha256(report_bytes),
            "report_commitment": report["report_commitment"],
        }
    finally:
        for descriptor in descriptors.values():
            _close_descriptor(descriptor)


def verify_sensitivity_evidence_bundle(destination: Path) -> dict[str, Any]:
    """Reconstruct the analysis from a path-anchored directory snapshot."""

    directory_descriptor, absolute_destination = evidence_filesystem.open_directory_path(
        destination,
        create_missing=False,
        error_type=SensitivityEvidenceError,
    )
    try:
        result = _verify_sensitivity_evidence_descriptor(directory_descriptor)
        if not _directory_descriptor_matches_path(directory_descriptor, absolute_destination):
            raise SensitivityEvidenceError("bundle destination changed during verification")
        return result
    finally:
        _close_descriptor(directory_descriptor)
