"""Create-only evidence for the bounded local validator runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sn87_provenonce.evidence import (
    EvidenceBundleSpec,
    seal_report,
    verify_bundle_with_report,
    write_bundle,
)

CLAIM_STATE = "IMPLEMENTED_TESTED_LOCAL_RUNTIME_ONLY"
REPORT_COMMITMENT_DOMAIN = "SN87:LOCAL_VALIDATOR_REPORT:v0alpha1"
BUNDLE_VERSION = "sn87-local-validator-bundle/0alpha1"
SPEC = EvidenceBundleSpec(BUNDLE_VERSION, REPORT_COMMITMENT_DOMAIN, CLAIM_STATE)


def seal_validator_report(report: dict[str, Any]) -> dict[str, Any]:
    _verify_runtime_boundary(report)
    return seal_report(report, SPEC)


def write_validator_evidence_bundle(
    report: dict[str, Any], destination: Path
) -> dict[str, Any]:
    _verify_runtime_boundary(report)
    return write_bundle(report, destination, SPEC)


def verify_validator_evidence_bundle(destination: Path) -> dict[str, Any]:
    result, report = verify_bundle_with_report(destination, SPEC)
    # Verify the operational boundary on the exact report snapshot that was hashed.
    _verify_runtime_boundary(report)
    return result


def _verify_runtime_boundary(report: dict[str, Any]) -> None:
    if report.get("claim_state") != CLAIM_STATE:
        raise ValueError("local validator claim state mismatch")
    if report.get("mode") != "LOCAL_TRANSPORT_NEUTRAL_VALIDATOR":
        raise ValueError("local validator mode mismatch")
    for field in ("scoring_performed", "weight_plan_created", "broadcast_capable"):
        if report.get(field) is not False:
            raise ValueError(f"local validator evidence requires {field}=false")
