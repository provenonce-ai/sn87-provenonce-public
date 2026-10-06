"""Create-only evidence bundles for transparent local simulations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sn87_provenonce.evidence import (
    EvidenceBundleSpec,
    verify_bundle,
    verify_report,
    write_bundle,
)
from sn87_provenonce.simulation.lane_one import REPORT_COMMITMENT_DOMAIN

BUNDLE_VERSION = "sn87-transparent-simulation-bundle/0alpha1"
SPEC = EvidenceBundleSpec(
    bundle_version=BUNDLE_VERSION,
    commitment_domain=REPORT_COMMITMENT_DOMAIN,
    claim_state="IMPLEMENTED_TESTED_SIMULATION_ONLY",
)


def verify_report_commitment(report: dict[str, Any]) -> None:
    verify_report(report, SPEC)


def write_evidence_bundle(report: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Write a new deterministic bundle without replacing an existing path."""

    return write_bundle(report, destination, SPEC)


def verify_evidence_bundle(destination: Path) -> dict[str, Any]:
    """Verify exact file membership, raw bytes, and the semantic report commitment."""

    return verify_bundle(destination, SPEC)
