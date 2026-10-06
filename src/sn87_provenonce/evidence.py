"""Reusable create-only evidence-bundle primitives."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sn87_provenonce import evidence_filesystem
from sn87_provenonce.protocol.v0alpha1 import (
    canonical_json_bytes,
    canonical_sha256,
    parse_json_strict,
)

EXPECTED_FILES = frozenset({"manifest.json", "report.json"})
DEFAULT_MAX_REPORT_BYTES = 16_777_216
DEFAULT_MAX_MANIFEST_BYTES = 16_384


class EvidenceBundleError(ValueError):
    """A caller-safe reusable evidence-bundle failure."""


@dataclass(frozen=True)
class EvidenceBundleSpec:
    bundle_version: str
    commitment_domain: str
    claim_state: str
    max_report_bytes: int = DEFAULT_MAX_REPORT_BYTES
    max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES

    def __post_init__(self) -> None:
        for name in ("bundle_version", "commitment_domain", "claim_state"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise EvidenceBundleError(f"{name} must be a nonempty string")
        for name in ("max_report_bytes", "max_manifest_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise EvidenceBundleError(f"{name} must be a positive exact integer")


def _raw_sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _stable_stat(metadata: os.stat_result) -> tuple[int, ...]:
    return evidence_filesystem.stable_stat(metadata)


def _fstat_descriptor(descriptor: int, label: str) -> os.stat_result:
    return evidence_filesystem.fstat_descriptor(descriptor, label, error_type=EvidenceBundleError)


def _close_descriptor(descriptor: int) -> None:
    evidence_filesystem.close_descriptor(descriptor)


def _open_directory_path(path: Path, *, create_missing: bool) -> tuple[int, Path]:
    return evidence_filesystem.open_directory_path(
        path,
        create_missing=create_missing,
        error_type=EvidenceBundleError,
    )


def _open_regular_file_at(directory_descriptor: int, name: str, max_bytes: int) -> int:
    return evidence_filesystem.open_regular_file_at(
        directory_descriptor,
        name,
        max_bytes,
        error_type=EvidenceBundleError,
        label_prefix="evidence bundle entry",
    )


def _read_open_file(descriptor: int, name: str, max_bytes: int) -> bytes:
    return evidence_filesystem.read_open_file(
        descriptor,
        name,
        max_bytes,
        error_type=EvidenceBundleError,
        label_prefix="evidence bundle entry",
    )


def _open_new_bundle_directory(destination: Path) -> int:
    descriptor, _absolute_destination = evidence_filesystem.open_new_bundle_directory(
        destination, error_type=EvidenceBundleError
    )
    return descriptor


def _write_new_bundle_file(directory_descriptor: int, name: str, payload: bytes) -> None:
    evidence_filesystem.write_new_bundle_file(
        directory_descriptor,
        name,
        payload,
        error_type=EvidenceBundleError,
        label_prefix="evidence bundle entry",
    )


def _directory_descriptor_matches_path(directory_descriptor: int, path: Path) -> bool:
    return evidence_filesystem.directory_descriptor_matches_path(directory_descriptor, path)


def seal_report(report: dict[str, Any], spec: EvidenceBundleSpec) -> dict[str, Any]:
    """Return a committed copy of an unsealed report with its claim boundary enforced."""

    try:
        if "report_commitment" in report:
            raise EvidenceBundleError("report is already sealed")
        if report.get("claim_state") != spec.claim_state:
            raise EvidenceBundleError("report claim state does not match bundle specification")
        sealed = dict(report)
        sealed["report_commitment"] = canonical_sha256(report, domain=spec.commitment_domain)
    except EvidenceBundleError:
        raise
    except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        raise EvidenceBundleError(f"report cannot be committed: {error}") from error
    return sealed


def verify_report(report: dict[str, Any], spec: EvidenceBundleSpec) -> None:
    try:
        commitment = report.get("report_commitment")
        if not isinstance(commitment, str):
            raise EvidenceBundleError("report_commitment is missing")
        if report.get("claim_state") != spec.claim_state:
            raise EvidenceBundleError("report claim state does not match bundle specification")
        body = {key: value for key, value in report.items() if key != "report_commitment"}
        expected = canonical_sha256(body, domain=spec.commitment_domain)
    except EvidenceBundleError:
        raise
    except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        raise EvidenceBundleError(f"report cannot be verified: {error}") from error
    if commitment != expected:
        raise EvidenceBundleError("report commitment mismatch")


def _manifest(
    report_bytes: bytes, report: dict[str, Any], spec: EvidenceBundleSpec
) -> dict[str, Any]:
    return {
        "bundle_version": spec.bundle_version,
        "claim_state": report["claim_state"],
        "files": {"report.json": _raw_sha256(report_bytes)},
        "report_commitment": report["report_commitment"],
    }


def _canonical_bytes(value: Any, max_bytes: int, label: str) -> bytes:
    try:
        payload = canonical_json_bytes(value) + b"\n"
    except (RecursionError, RuntimeError, TypeError, UnicodeError, ValueError) as error:
        raise EvidenceBundleError(f"{label} is not canonical JSON: {error}") from error
    if len(payload) > max_bytes:
        raise EvidenceBundleError(f"{label} exceeds its {max_bytes}-byte limit")
    return payload


def write_bundle(
    report: dict[str, Any], destination: Path, spec: EvidenceBundleSpec
) -> dict[str, Any]:
    """Write and verify one deterministic bundle without replacing an existing path."""

    report_bytes = _canonical_bytes(report, spec.max_report_bytes, "evidence report")
    try:
        report_snapshot = parse_json_strict(report_bytes)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise EvidenceBundleError(
            f"canonical evidence report could not be parsed: {error}"
        ) from error
    if not isinstance(report_snapshot, dict):
        raise EvidenceBundleError("canonical evidence report root must be an object")
    verify_report(report_snapshot, spec)
    manifest = _manifest(report_bytes, report_snapshot, spec)
    manifest_bytes = _canonical_bytes(manifest, spec.max_manifest_bytes, "evidence manifest")

    try:
        absolute_destination = destination.absolute()
    except (OSError, UnicodeError, ValueError) as error:
        raise EvidenceBundleError("evidence destination path is invalid") from error
    directory_descriptor = _open_new_bundle_directory(absolute_destination)
    try:
        _write_new_bundle_file(directory_descriptor, "report.json", report_bytes)
        _write_new_bundle_file(directory_descriptor, "manifest.json", manifest_bytes)
        try:
            os.fsync(directory_descriptor)
        except OSError as error:
            raise EvidenceBundleError(
                "evidence bundle directory could not be synchronized"
            ) from error
        result, verified_report = _verify_bundle_descriptor(directory_descriptor, spec)
        if verified_report != report_snapshot or result["report_sha256"] != _raw_sha256(
            report_bytes
        ):
            raise EvidenceBundleError("verified evidence report differs from the written snapshot")
        if not _directory_descriptor_matches_path(directory_descriptor, absolute_destination):
            raise EvidenceBundleError("evidence bundle destination changed during creation")
        return result
    finally:
        _close_descriptor(directory_descriptor)


def _verify_bundle_descriptor(
    directory_descriptor: int, spec: EvidenceBundleSpec
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify one two-file bundle through an anchored directory descriptor."""

    try:
        actual_files = set(os.listdir(directory_descriptor))
    except OSError as error:
        raise EvidenceBundleError("evidence bundle could not be listed safely") from error
    if actual_files != EXPECTED_FILES:
        raise EvidenceBundleError(
            f"bundle file set mismatch: expected {sorted(EXPECTED_FILES)}, "
            f"found {sorted(actual_files)}"
        )
    initial_directory_stat = _stable_stat(
        _fstat_descriptor(directory_descriptor, "evidence bundle directory")
    )
    limits = {
        "manifest.json": spec.max_manifest_bytes,
        "report.json": spec.max_report_bytes,
    }
    descriptors: dict[str, int] = {}
    try:
        for name in sorted(EXPECTED_FILES):
            descriptors[name] = _open_regular_file_at(directory_descriptor, name, limits[name])
        initial_stats = {
            name: _stable_stat(_fstat_descriptor(descriptor, f"evidence bundle entry {name}"))
            for name, descriptor in descriptors.items()
        }
        snapshots = {
            name: _read_open_file(descriptor, name, limits[name])
            for name, descriptor in descriptors.items()
        }
        manifest_bytes = snapshots["manifest.json"]
        report_bytes = snapshots["report.json"]
        try:
            manifest_value = parse_json_strict(manifest_bytes)
            report_value = parse_json_strict(report_bytes)
        except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
            raise EvidenceBundleError(f"invalid evidence bundle JSON: {error}") from error
        if not isinstance(manifest_value, dict) or not isinstance(report_value, dict):
            raise EvidenceBundleError("bundle JSON roots must be objects")
        if manifest_value.get("bundle_version") != spec.bundle_version:
            raise EvidenceBundleError("unsupported evidence bundle version")
        manifest_files = manifest_value.get("files")
        if not isinstance(manifest_files, dict) or set(manifest_files) != {"report.json"}:
            raise EvidenceBundleError("manifest files must contain exactly report.json")
        actual_hash = _raw_sha256(report_bytes)
        if manifest_files["report.json"] != actual_hash:
            raise EvidenceBundleError("report.json byte hash mismatch")
        canonical_manifest = _canonical_bytes(
            manifest_value, spec.max_manifest_bytes, "evidence manifest"
        )
        canonical_report = _canonical_bytes(report_value, spec.max_report_bytes, "evidence report")
        if manifest_bytes != canonical_manifest:
            raise EvidenceBundleError("manifest.json is not the exact canonical snapshot")
        if report_bytes != canonical_report:
            raise EvidenceBundleError("report.json is not the exact canonical snapshot")
        verify_report(report_value, spec)
        expected_manifest = _manifest(report_bytes, report_value, spec)
        if manifest_value != expected_manifest:
            raise EvidenceBundleError("manifest does not match the verified report snapshot")

        closing_snapshots = {
            name: _read_open_file(descriptor, name, limits[name])
            for name, descriptor in descriptors.items()
        }
        try:
            final_descriptor_stats = {
                name: _stable_stat(_fstat_descriptor(descriptor, f"evidence bundle entry {name}"))
                for name, descriptor in descriptors.items()
            }
            final_named_stats = {
                name: _stable_stat(
                    os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                )
                for name in descriptors
            }
        except (OSError, UnicodeError) as error:
            raise EvidenceBundleError(
                "evidence bundle entry changed during verification"
            ) from error
        for name in descriptors:
            if (
                closing_snapshots[name] != snapshots[name]
                or final_descriptor_stats[name] != initial_stats[name]
                or final_named_stats[name] != initial_stats[name]
            ):
                raise EvidenceBundleError(
                    f"evidence bundle entry changed during verification: {name}"
                )

        try:
            closing_files = set(os.listdir(directory_descriptor))
            closing_directory_stat = _stable_stat(
                _fstat_descriptor(directory_descriptor, "evidence bundle directory")
            )
        except (OSError, UnicodeError) as error:
            raise EvidenceBundleError("evidence bundle could not be finalized safely") from error
        if closing_files != EXPECTED_FILES:
            raise EvidenceBundleError("evidence bundle membership changed during verification")
        if closing_directory_stat != initial_directory_stat:
            raise EvidenceBundleError("evidence bundle directory changed during verification")

        result = {
            "status": "VERIFIED",
            "bundle_version": spec.bundle_version,
            "claim_state": report_value["claim_state"],
            "report_sha256": actual_hash,
            "report_commitment": report_value["report_commitment"],
            "files": sorted(actual_files),
        }
        return result, report_value
    finally:
        for descriptor in descriptors.values():
            _close_descriptor(descriptor)


def verify_bundle(destination: Path, spec: EvidenceBundleSpec) -> dict[str, Any]:
    """Verify exact membership, bytes, claim state, and semantic commitment."""

    result, _report = verify_bundle_with_report(destination, spec)
    return result


def verify_bundle_with_report(
    destination: Path, spec: EvidenceBundleSpec
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify one path-anchored bundle and return its exact parsed report snapshot."""

    directory_descriptor, absolute_destination = _open_directory_path(
        destination, create_missing=False
    )
    try:
        result = _verify_bundle_descriptor(directory_descriptor, spec)
        if not _directory_descriptor_matches_path(directory_descriptor, absolute_destination):
            raise EvidenceBundleError("evidence bundle destination changed during verification")
        return result
    finally:
        _close_descriptor(directory_descriptor)
