"""Create-only evidence bundles for the transparent Type-C reference oracle."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sn87_provenonce.evidence import EvidenceBundleSpec, verify_bundle_with_report, write_bundle
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable
from sn87_provenonce.protocol.v0alpha1 import ResponseState, canonical_sha256
from sn87_provenonce.simulation.type_c import (
    CLAIM_STATE,
    FIXTURE_COMMITMENT_DOMAIN,
    FIXTURES,
    REPORT_COMMITMENT_DOMAIN,
    SIMULATION_VERSION,
    EventKind,
    MutationProvenance,
    TypeCFixture,
    WorkflowEvent,
    workflow_contract,
)


def _type_c_reference():
    """The private Type C executor, imported at the call that needs it."""
    try:
        from sn87_provenonce.simulation import type_c_reference
    except ImportError as exc:
        raise PrivateReferenceExecutorUnavailable from exc
    return type_c_reference


BUNDLE_VERSION = "sn87-transparent-type-c-reference-oracle-bundle/0alpha2"
SPEC = EvidenceBundleSpec(BUNDLE_VERSION, REPORT_COMMITMENT_DOMAIN, CLAIM_STATE)


def write_type_c_evidence_bundle(report: dict[str, Any], destination: Path) -> dict[str, Any]:
    _verify_type_c_boundary(report)
    return write_bundle(report, destination, SPEC)


def verify_type_c_evidence_bundle(destination: Path) -> dict[str, Any]:
    result, report = verify_bundle_with_report(destination, SPEC)
    _verify_type_c_boundary(report)
    return result


def _verify_type_c_boundary(report: dict[str, Any]) -> None:
    if set(report) != {
        "simulation_version",
        "claim_state",
        "boundaries",
        "workflow_contract",
        "reference_executors",
        "fixtures",
        "all_references_agree",
        "report_commitment",
    }:
        raise ValueError("Type C report field set mismatch")
    if report.get("claim_state") != CLAIM_STATE:
        raise ValueError("Type C report claim state mismatch")
    if report.get("simulation_version") != SIMULATION_VERSION:
        raise ValueError("Type C simulation version mismatch")
    boundaries = report.get("boundaries")
    required_boundaries = {
        "benchmark_truth",
        "external_network",
        "hidden_fixture",
        "miner_scoring",
        "chain_submission",
        "production_evidence",
    }
    if not isinstance(boundaries, dict) or set(boundaries) != required_boundaries:
        raise ValueError("Type C report boundary set mismatch")
    if any(value is not False for value in boundaries.values()):
        raise ValueError("transparent Type C report boundaries must all be false")
    if report.get("workflow_contract") != workflow_contract():
        raise ValueError("Type C report workflow contract mismatch")
    executors = report.get("reference_executors")
    if executors != ["state_machine", "relational"]:
        raise ValueError("Type C report reference executor set mismatch")
    fixtures = report.get("fixtures")
    if (
        not isinstance(fixtures, list)
        or not fixtures
        or not all(isinstance(fixture, dict) for fixture in fixtures)
    ):
        raise ValueError("Type C report requires fixture results")
    fixture_ids = [fixture.get("fixture_id") for fixture in fixtures]
    if not all(isinstance(fixture_id, str) and fixture_id.strip() for fixture_id in fixture_ids):
        raise ValueError("Type C report fixture identities must be non-empty and unique")
    if len(fixture_ids) != len(set(fixture_ids)):
        raise ValueError("Type C report fixture identities must be non-empty and unique")
    canonical_fixture_ids = [fixture.fixture_id for fixture in FIXTURES]
    if fixture_ids != canonical_fixture_ids:
        raise ValueError("Type C report fixture corpus mismatch")
    canonical_fixtures = {fixture.fixture_id: fixture for fixture in FIXTURES}
    for fixture in fixtures:
        if set(fixture) != {
            "fixture_id",
            "case_class",
            "evidence_complete",
            "events",
            "input_commitment",
            "mutation_provenance",
            "reference_results",
            "agreed_outcome",
            "reference_agreement",
        }:
            raise ValueError("Type C fixture field set mismatch")
        if fixture.get("reference_agreement") is not True:
            raise ValueError("Type C fixture reference agreement is not proven")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", str(fixture.get("input_commitment"))) is None:
            raise ValueError("Type C fixture input commitment is invalid")
        if not isinstance(fixture.get("case_class"), str) or not fixture["case_class"].strip():
            raise ValueError("Type C fixture case class is invalid")
        if not isinstance(fixture.get("evidence_complete"), bool):
            raise ValueError("Type C fixture evidence completeness is invalid")
        events = fixture.get("events")
        if (
            not isinstance(events, list)
            or not events
            or not all(isinstance(event, dict) for event in events)
        ):
            raise ValueError("Type C fixture events are invalid")
        event_ids: list[str] = []
        valid_event_kinds = {kind.value for kind in EventKind}
        for event in events:
            required_event_keys = {
                "event_id",
                "kind",
                "input_commitment",
                "output_commitment",
            }
            permitted_event_keys = required_event_keys | {"approved"}
            if not required_event_keys.issubset(event) or not set(event).issubset(
                permitted_event_keys
            ):
                raise ValueError("Type C fixture event field set is invalid")
            event_id = event["event_id"]
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError("Type C fixture event identity is invalid")
            event_ids.append(event_id)
            kind = event["kind"]
            if not isinstance(kind, str) or kind not in valid_event_kinds:
                raise ValueError("Type C fixture event kind is invalid")
            for key in ("input_commitment", "output_commitment"):
                value = event[key]
                if (
                    not isinstance(value, str)
                    or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                ):
                    raise ValueError("Type C fixture event commitment is invalid")
            if "approved" in event and (
                kind != EventKind.REVIEW.value or not isinstance(event["approved"], bool)
            ):
                raise ValueError("Type C fixture event approval is invalid")
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Type C fixture event identities must be unique")
        results = fixture.get("reference_results")
        if not isinstance(results, dict) or set(results) != set(executors):
            raise ValueError("Type C fixture reference result set mismatch")
        if any(value != fixture.get("agreed_outcome") for value in results.values()):
            raise ValueError("Type C fixture reference results differ")
        provenance = fixture.get("mutation_provenance")
        if not isinstance(provenance, dict) or set(provenance) != {
            "source_fixture_id",
            "operator",
            "expected_invariant",
        }:
            raise ValueError("Type C fixture mutation provenance is missing")
        if not isinstance(provenance.get("operator"), str) or not provenance["operator"].strip():
            raise ValueError("Type C fixture mutation operator is invalid")
        source_id = provenance.get("source_fixture_id")
        if source_id is not None and (
            not isinstance(source_id, str)
            or not source_id.strip()
            or source_id not in fixture_ids
            or source_id == fixture["fixture_id"]
        ):
            raise ValueError("Type C fixture mutation source is invalid")
        invariant = provenance.get("expected_invariant")
        outcome = fixture.get("agreed_outcome")
        if (
            not isinstance(outcome, dict)
            or set(outcome) != {"response_state", "defect_codes"}
            or not isinstance(outcome.get("response_state"), str)
            or outcome.get("response_state") not in {state.value for state in ResponseState}
            or not isinstance(outcome.get("defect_codes"), list)
            or not all(isinstance(code, str) and code.strip() for code in outcome["defect_codes"])
            or outcome["defect_codes"] != sorted(set(outcome["defect_codes"]))
        ):
            raise ValueError("Type C fixture agreed outcome is invalid")
        if not isinstance(invariant, str) or (
            invariant != outcome.get("response_state") and invariant not in outcome["defect_codes"]
        ):
            raise ValueError("Type C fixture mutation invariant is not established")
        commitment_body = {
            "fixture_id": fixture["fixture_id"],
            "case_class": fixture["case_class"],
            "evidence_complete": fixture["evidence_complete"],
            "events": events,
            "provenance": provenance,
        }
        expected_commitment = canonical_sha256(
            commitment_body,
            domain=FIXTURE_COMMITMENT_DOMAIN,
        )
        if fixture["input_commitment"] != expected_commitment:
            raise ValueError("Type C fixture input commitment does not match disclosed input")
        reconstructed = TypeCFixture(
            fixture_id=fixture["fixture_id"],
            case_class=fixture["case_class"],
            evidence_complete=fixture["evidence_complete"],
            events=tuple(
                WorkflowEvent(
                    event_id=event["event_id"],
                    kind=EventKind(event["kind"]),
                    input_commitment=event["input_commitment"],
                    output_commitment=event["output_commitment"],
                    approved=event.get("approved"),
                )
                for event in events
            ),
            provenance=MutationProvenance(
                source_fixture_id=provenance["source_fixture_id"],
                operator=provenance["operator"],
                expected_invariant=provenance["expected_invariant"],
            ),
        )
        if reconstructed != canonical_fixtures[fixture["fixture_id"]]:
            raise ValueError("Type C fixture does not match versioned corpus")
        if fixture != _type_c_reference().compare_reference_executions(reconstructed):
            raise ValueError("Type C fixture does not match recomputed reference execution")
    if report.get("all_references_agree") is not True:
        raise ValueError("Type C report reference agreement is not proven")
