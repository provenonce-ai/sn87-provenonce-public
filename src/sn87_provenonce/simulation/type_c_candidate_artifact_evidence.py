"""Create-only evidence for bounded offline Type-C candidate artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sn87_provenonce import evidence_filesystem
from sn87_provenonce.protocol.v0alpha1 import canonical_json_bytes, parse_json_strict
from sn87_provenonce.simulation.type_c_candidate_artifact import (
    CLAIM_STATE,
    MAX_ARTIFACT_BYTES,
    REPORT_VERSION,
    raw_sha256,
    read_bounded_regular_file,
    run_type_c_candidate_artifact_bytes,
)

BUNDLE_VERSION = "sn87-transparent-type-c-candidate-artifact-bundle/0alpha1"
EXPECTED_FILES = frozenset({"manifest.json", "report.json", "candidate-artifact.json"})
MAX_REPORT_BYTES = 1_048_576
MAX_MANIFEST_BYTES = 16_384


class CandidateArtifactEvidenceError(ValueError):
    """A caller-safe offline candidate evidence failure."""


def _open_regular_file_at(directory_descriptor: int, name: str, max_bytes: int) -> int:
    return evidence_filesystem.open_regular_file_at(
        directory_descriptor,
        name,
        max_bytes,
        error_type=CandidateArtifactEvidenceError,
        label_prefix="bundle entry",
    )


def _read_open_file(descriptor: int, name: str, max_bytes: int) -> bytes:
    return evidence_filesystem.read_open_file(
        descriptor,
        name,
        max_bytes,
        error_type=CandidateArtifactEvidenceError,
        label_prefix="bundle entry",
    )


def _stable_stat(metadata: os.stat_result) -> tuple[int, ...]:
    return evidence_filesystem.stable_stat(metadata)


def _fstat_descriptor(descriptor: int, label: str) -> os.stat_result:
    return evidence_filesystem.fstat_descriptor(
        descriptor, label, error_type=CandidateArtifactEvidenceError
    )


def _close_descriptor(descriptor: int) -> None:
    evidence_filesystem.close_descriptor(descriptor)


def _manifest(
    candidate_bytes: bytes, report_bytes: bytes, report: dict[str, Any]
) -> dict[str, Any]:
    return {
        "bundle_version": BUNDLE_VERSION,
        "claim_state": CLAIM_STATE,
        "files": {
            "candidate-artifact.json": raw_sha256(candidate_bytes),
            "report.json": raw_sha256(report_bytes),
        },
        "report_commitment": report["report_commitment"],
        "source_artifact_sha256": report["source_artifact_sha256"],
    }


def _open_new_bundle_directory(destination: Path) -> int:
    descriptor, _absolute_destination = evidence_filesystem.open_new_bundle_directory(
        destination, error_type=CandidateArtifactEvidenceError
    )
    return descriptor


def _write_new_bundle_file(directory_descriptor: int, name: str, payload: bytes) -> None:
    evidence_filesystem.write_new_bundle_file(
        directory_descriptor,
        name,
        payload,
        error_type=CandidateArtifactEvidenceError,
        label_prefix="bundle entry",
    )


def _directory_descriptor_matches_path(directory_descriptor: int, path: Path) -> bool:
    return evidence_filesystem.directory_descriptor_matches_path(directory_descriptor, path)


def write_type_c_candidate_artifact_evidence_bundle(
    source: Path, destination: Path
) -> dict[str, Any]:
    """Validate once, then preserve and evaluate the same exact source byte snapshot."""

    candidate_bytes = read_bounded_regular_file(source)
    report = run_type_c_candidate_artifact_bytes(candidate_bytes)
    try:
        report_bytes = canonical_json_bytes(report) + b"\n"
        manifest_bytes = (
            canonical_json_bytes(_manifest(candidate_bytes, report_bytes, report)) + b"\n"
        )
    except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        raise CandidateArtifactEvidenceError(
            f"candidate-artifact evidence is not canonical: {error}"
        ) from error
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise CandidateArtifactEvidenceError("candidate-artifact report exceeds its byte limit")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise CandidateArtifactEvidenceError("candidate-artifact manifest exceeds its byte limit")
    absolute_destination = evidence_filesystem.absolute_path(
        destination,
        error_type=CandidateArtifactEvidenceError,
        label="evidence destination",
    )
    directory_descriptor = _open_new_bundle_directory(absolute_destination)
    try:
        _write_new_bundle_file(directory_descriptor, "candidate-artifact.json", candidate_bytes)
        _write_new_bundle_file(directory_descriptor, "report.json", report_bytes)
        _write_new_bundle_file(directory_descriptor, "manifest.json", manifest_bytes)
        try:
            os.fsync(directory_descriptor)
        except OSError as error:
            raise CandidateArtifactEvidenceError(
                "bundle directory could not be synchronized"
            ) from error
        result = _verify_type_c_candidate_artifact_evidence_descriptor(directory_descriptor)
        if result["source_artifact_sha256"] != raw_sha256(candidate_bytes):
            raise CandidateArtifactEvidenceError(
                "verified bundle source differs from the input snapshot"
            )
        if result["report_sha256"] != raw_sha256(report_bytes):
            raise CandidateArtifactEvidenceError(
                "verified bundle report differs from the written report"
            )
        if not _directory_descriptor_matches_path(directory_descriptor, absolute_destination):
            raise CandidateArtifactEvidenceError("bundle destination changed during creation")
        return result
    finally:
        _close_descriptor(directory_descriptor)


def _verify_type_c_candidate_artifact_evidence_descriptor(
    directory_descriptor: int,
) -> dict[str, Any]:
    """Verify and reconstruct one bundle through an anchored directory descriptor."""

    try:
        actual_files = set(os.listdir(directory_descriptor))
    except OSError as error:
        raise CandidateArtifactEvidenceError(
            "bundle directory could not be listed safely"
        ) from error
    if actual_files != EXPECTED_FILES:
        raise CandidateArtifactEvidenceError(
            f"bundle file set mismatch: expected {sorted(EXPECTED_FILES)}, "
            f"found {sorted(actual_files)}"
        )
    initial_directory_stat = _stable_stat(
        _fstat_descriptor(directory_descriptor, "bundle directory")
    )
    limits = {
        "candidate-artifact.json": MAX_ARTIFACT_BYTES,
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
        candidate_bytes = snapshots["candidate-artifact.json"]
        report_bytes = snapshots["report.json"]
        manifest_bytes = snapshots["manifest.json"]
        try:
            manifest = parse_json_strict(manifest_bytes)
            report = parse_json_strict(report_bytes)
        except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
            raise CandidateArtifactEvidenceError(f"invalid bundle JSON: {error}") from error
        if not isinstance(manifest, dict) or not isinstance(report, dict):
            raise CandidateArtifactEvidenceError("bundle JSON roots must be objects")
        try:
            canonical_manifest = canonical_json_bytes(manifest) + b"\n"
            canonical_report = canonical_json_bytes(report) + b"\n"
        except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
            raise CandidateArtifactEvidenceError(
                f"bundle JSON is not canonical: {error}"
            ) from error
        if manifest_bytes != canonical_manifest:
            raise CandidateArtifactEvidenceError(
                "manifest.json is not the exact canonical snapshot"
            )
        if report_bytes != canonical_report:
            raise CandidateArtifactEvidenceError("report.json is not the exact canonical snapshot")
        if manifest.get("bundle_version") != BUNDLE_VERSION:
            raise CandidateArtifactEvidenceError("unsupported candidate-artifact bundle version")
        if manifest.get("claim_state") != CLAIM_STATE or report.get("claim_state") != CLAIM_STATE:
            raise CandidateArtifactEvidenceError("candidate-artifact claim state mismatch")
        expected_files = {
            "candidate-artifact.json": raw_sha256(candidate_bytes),
            "report.json": raw_sha256(report_bytes),
        }
        if manifest.get("files") != expected_files:
            raise CandidateArtifactEvidenceError("candidate-artifact bundle file hash mismatch")
        try:
            expected_report = run_type_c_candidate_artifact_bytes(candidate_bytes)
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise CandidateArtifactEvidenceError(
                f"invalid preserved candidate artifact: {error}"
            ) from error
        if report != expected_report:
            raise CandidateArtifactEvidenceError(
                "candidate-artifact report does not match exact source reconstruction"
            )
        if manifest != _manifest(candidate_bytes, report_bytes, report):
            raise CandidateArtifactEvidenceError("manifest does not match the reconstructed bundle")
        if report.get("report_version") != REPORT_VERSION:
            raise CandidateArtifactEvidenceError("candidate-artifact report version mismatch")
        if manifest.get("report_commitment") != report.get("report_commitment"):
            raise CandidateArtifactEvidenceError("manifest and report commitments differ")
        if manifest.get("source_artifact_sha256") != report.get("source_artifact_sha256"):
            raise CandidateArtifactEvidenceError("manifest and source artifact hashes differ")

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
            raise CandidateArtifactEvidenceError(
                "bundle entry changed during verification"
            ) from error
        for name in descriptors:
            if (
                closing_snapshots[name] != snapshots[name]
                or final_descriptor_stats[name] != initial_stats[name]
                or final_named_stats[name] != initial_stats[name]
            ):
                raise CandidateArtifactEvidenceError(
                    f"bundle entry changed during verification: {name}"
                )

        try:
            closing_files = set(os.listdir(directory_descriptor))
            closing_directory_stat = _stable_stat(
                _fstat_descriptor(directory_descriptor, "bundle directory")
            )
        except (OSError, UnicodeError, ValueError) as error:
            raise CandidateArtifactEvidenceError(
                "bundle directory could not be finalized safely"
            ) from error
        if closing_files != EXPECTED_FILES:
            raise CandidateArtifactEvidenceError("bundle membership changed during verification")
        if closing_directory_stat != initial_directory_stat:
            raise CandidateArtifactEvidenceError("bundle directory changed during verification")
        return {
            "status": "VERIFIED",
            "bundle_version": BUNDLE_VERSION,
            "claim_state": CLAIM_STATE,
            "files": sorted(actual_files),
            "source_artifact_sha256": report["source_artifact_sha256"],
            "normalized_artifact_commitment": report["normalized_artifact_commitment"],
            "report_sha256": raw_sha256(report_bytes),
            "report_commitment": report["report_commitment"],
            "all_cases_conformant": report["summary"]["all_cases_conformant"],
        }
    finally:
        for descriptor in descriptors.values():
            _close_descriptor(descriptor)


def verify_type_c_candidate_artifact_evidence_bundle(destination: Path) -> dict[str, Any]:
    """Reconstruct one candidate run from a path-anchored directory snapshot."""

    directory_descriptor, absolute_destination = evidence_filesystem.open_directory_path(
        destination,
        create_missing=False,
        error_type=CandidateArtifactEvidenceError,
    )
    try:
        result = _verify_type_c_candidate_artifact_evidence_descriptor(directory_descriptor)
        if not _directory_descriptor_matches_path(directory_descriptor, absolute_destination):
            raise CandidateArtifactEvidenceError("bundle destination changed during verification")
        return result
    finally:
        _close_descriptor(directory_descriptor)
