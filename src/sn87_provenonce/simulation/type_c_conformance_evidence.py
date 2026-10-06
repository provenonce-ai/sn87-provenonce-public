"""Create-only evidence for transparent candidate-Differential conformance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sn87_provenonce.evidence import EvidenceBundleSpec, verify_bundle_with_report, write_bundle
from sn87_provenonce.simulation.type_c_conformance import (
    CLAIM_STATE,
    CONFORMANCE_VERSION,
    REPORT_COMMITMENT_DOMAIN,
    run_type_c_candidate_conformance,
)

BUNDLE_VERSION = "sn87-transparent-type-c-candidate-conformance-bundle/0alpha1"
SPEC = EvidenceBundleSpec(BUNDLE_VERSION, REPORT_COMMITMENT_DOMAIN, CLAIM_STATE)


def write_type_c_conformance_evidence_bundle(
    report: dict[str, Any], destination: Path
) -> dict[str, Any]:
    _verify_conformance_boundary(report)
    return write_bundle(report, destination, SPEC)


def verify_type_c_conformance_evidence_bundle(destination: Path) -> dict[str, Any]:
    result, report = verify_bundle_with_report(destination, SPEC)
    _verify_conformance_boundary(report)
    return result


def _verify_conformance_boundary(report: dict[str, Any]) -> None:
    if report.get("conformance_version") != CONFORMANCE_VERSION:
        raise ValueError("Type-C conformance version mismatch")
    boundaries = report.get("boundaries")
    if not isinstance(boundaries, dict) or not boundaries:
        raise ValueError("Type-C conformance boundaries are missing")
    if any(value is not False for value in boundaries.values()):
        raise ValueError("Type-C conformance boundaries must all be false")
    expected = run_type_c_candidate_conformance()
    if report != expected:
        raise ValueError("Type-C conformance report does not match the versioned corpus")
