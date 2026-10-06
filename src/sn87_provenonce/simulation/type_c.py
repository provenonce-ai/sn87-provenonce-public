"""Transparent Type-C reference-oracle fixtures for local conformance."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

from sn87_provenonce.protocol.v0alpha1 import canonical_sha256

SIMULATION_VERSION = "type-c-transparent-reference-oracle/0alpha2"
REPORT_COMMITMENT_DOMAIN = "SN87:TYPE_C_TRANSPARENT_REFERENCE_ORACLE_REPORT:v0alpha2"
FIXTURE_COMMITMENT_DOMAIN = "SN87:TYPE_C_TRANSPARENT_FIXTURE:v0alpha2"
CLAIM_STATE = "IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_REFERENCE_ORACLE_ONLY"


class EventKind(StrEnum):
    SUBMIT = "SUBMIT"
    REVIEW = "REVIEW"
    OBSERVE = "OBSERVE"
    VALIDATE = "VALIDATE"
    RELEASE = "RELEASE"


class MutationOperator(StrEnum):
    BASELINE = "BASELINE"
    DELETE_REVIEW_EVENT = "DELETE_REVIEW_EVENT"
    INSERT_SEMANTIC_NO_OP = "INSERT_SEMANTIC_NO_OP"
    SUBSTITUTE_REVIEW_INPUT = "SUBSTITUTE_REVIEW_INPUT"
    REDACT_REQUIRED_EVENTS = "REDACT_REQUIRED_EVENTS"
    DELETE_SUBMIT_EVENT = "DELETE_SUBMIT_EVENT"
    SWAP_SUBMIT_AND_VALIDATE_KINDS = "SWAP_SUBMIT_AND_VALIDATE_KINDS"
    INSERT_DUPLICATE_SUBMIT = "INSERT_DUPLICATE_SUBMIT"


REQUIRED_EVENT_ORDER = (
    EventKind.SUBMIT,
    EventKind.REVIEW,
    EventKind.VALIDATE,
    EventKind.RELEASE,
)


def workflow_contract() -> dict[str, object]:
    """Return a fresh disclosed copy of the fixture-local workflow grammar."""

    return {
        "required_event_cardinality": {kind.value: 1 for kind in REQUIRED_EVENT_ORDER},
        "required_event_order": [kind.value for kind in REQUIRED_EVENT_ORDER],
        "optional_events": [EventKind.OBSERVE.value],
        "observation_window": "AFTER_SUBMIT_BEFORE_RELEASE",
        "release_must_be_terminal": True,
        "review_must_be_approved": True,
        "commitment_chain_must_be_contiguous": True,
    }


MISSING_DEFECT = {
    EventKind.SUBMIT: "MISSING_SUBMIT_EVENT",
    EventKind.REVIEW: "MISSING_REVIEW_GATE",
    EventKind.VALIDATE: "MISSING_VALIDATION_GATE",
    EventKind.RELEASE: "MISSING_RELEASE_EVENT",
}
DUPLICATE_DEFECT = {
    EventKind.SUBMIT: "DUPLICATE_SUBMIT_EVENT",
    EventKind.REVIEW: "DUPLICATE_REVIEW_EVENT",
    EventKind.VALIDATE: "DUPLICATE_VALIDATION_EVENT",
    EventKind.RELEASE: "DUPLICATE_RELEASE_EVENT",
}


@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    kind: EventKind
    input_commitment: str
    output_commitment: str
    approved: bool | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must be non-empty")
        for value in (self.input_commitment, self.output_commitment):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
                raise ValueError("event commitments must be lowercase sha256 values")
        if self.kind is not EventKind.REVIEW and self.approved is not None:
            raise ValueError("approved is valid only for REVIEW events")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "input_commitment": self.input_commitment,
            "output_commitment": self.output_commitment,
        }
        if self.approved is not None:
            value["approved"] = self.approved
        return value


@dataclass(frozen=True)
class MutationProvenance:
    source_fixture_id: str | None
    operator: str
    expected_invariant: str

    def __post_init__(self) -> None:
        if self.source_fixture_id is not None and not self.source_fixture_id.strip():
            raise ValueError("source_fixture_id must be non-empty when present")
        if not self.operator.strip() or not self.expected_invariant.strip():
            raise ValueError("mutation operator and expected invariant must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_fixture_id": self.source_fixture_id,
            "operator": self.operator,
            "expected_invariant": self.expected_invariant,
        }


@dataclass(frozen=True)
class TypeCFixture:
    fixture_id: str
    case_class: str
    evidence_complete: bool
    events: tuple[WorkflowEvent, ...]
    provenance: MutationProvenance

    def __post_init__(self) -> None:
        if not self.fixture_id.strip() or not self.case_class.strip():
            raise ValueError("fixture_id and case_class must be non-empty")
        if not self.events:
            raise ValueError("Type C fixtures require at least one event")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Type C fixture event_ids must be unique")

    @property
    def input_commitment(self) -> str:
        return canonical_sha256(
            {
                "fixture_id": self.fixture_id,
                "case_class": self.case_class,
                "evidence_complete": self.evidence_complete,
                "events": [event.to_dict() for event in self.events],
                "provenance": self.provenance.to_dict(),
            },
            domain=FIXTURE_COMMITMENT_DOMAIN,
        )


def _artifact_commitment(marker: str) -> str:
    return canonical_sha256(marker, domain="SN87:TYPE_C_TOY_ARTIFACT:v0alpha1")


def _event(
    event_id: str,
    kind: EventKind,
    input_marker: str,
    output_marker: str,
    *,
    approved: bool | None = None,
) -> WorkflowEvent:
    return WorkflowEvent(
        event_id=event_id,
        kind=kind,
        input_commitment=_artifact_commitment(input_marker),
        output_commitment=_artifact_commitment(output_marker),
        approved=approved,
    )


def _apply_mutation(
    source: TypeCFixture, operator: MutationOperator
) -> tuple[tuple[WorkflowEvent, ...], bool]:
    events = source.events
    if operator is MutationOperator.DELETE_REVIEW_EVENT:
        review_index = next(
            index for index, event in enumerate(events) if event.kind is EventKind.REVIEW
        )
        prior = events[review_index - 1]
        following = replace(events[review_index + 1], input_commitment=prior.output_commitment)
        return events[:review_index] + (following,) + events[review_index + 2 :], True
    if operator is MutationOperator.INSERT_SEMANTIC_NO_OP:
        submit_index = next(
            index for index, event in enumerate(events) if event.kind is EventKind.SUBMIT
        )
        anchor = events[submit_index]
        observation = WorkflowEvent(
            event_id="semantic-no-op",
            kind=EventKind.OBSERVE,
            input_commitment=anchor.output_commitment,
            output_commitment=anchor.output_commitment,
        )
        return events[: submit_index + 1] + (observation,) + events[submit_index + 1 :], True
    if operator is MutationOperator.SUBSTITUTE_REVIEW_INPUT:
        return tuple(
            replace(event, input_commitment=_artifact_commitment("other-input"))
            if event.kind is EventKind.REVIEW
            else event
            for event in events
        ), True
    if operator is MutationOperator.REDACT_REQUIRED_EVENTS:
        return tuple(event for event in events if event.kind is EventKind.RELEASE), False
    if operator is MutationOperator.DELETE_SUBMIT_EVENT:
        return tuple(event for event in events if event.kind is not EventKind.SUBMIT), True
    if operator is MutationOperator.SWAP_SUBMIT_AND_VALIDATE_KINDS:
        return tuple(
            replace(event, kind=EventKind.VALIDATE)
            if event.kind is EventKind.SUBMIT
            else replace(event, kind=EventKind.SUBMIT)
            if event.kind is EventKind.VALIDATE
            else event
            for event in events
        ), True
    if operator is MutationOperator.INSERT_DUPLICATE_SUBMIT:
        submit_index = next(
            index for index, event in enumerate(events) if event.kind is EventKind.SUBMIT
        )
        anchor = events[submit_index]
        duplicate = WorkflowEvent(
            event_id="duplicate-submit",
            kind=EventKind.SUBMIT,
            input_commitment=anchor.output_commitment,
            output_commitment=anchor.output_commitment,
        )
        return events[: submit_index + 1] + (duplicate,) + events[submit_index + 1 :], True
    raise ValueError(f"unsupported mutation operator: {operator}")


def _derive_fixture(
    *,
    fixture_id: str,
    case_class: str,
    source: TypeCFixture,
    operator: MutationOperator,
    expected_invariant: str,
) -> TypeCFixture:
    events, evidence_complete = _apply_mutation(source, operator)
    return TypeCFixture(
        fixture_id=fixture_id,
        case_class=case_class,
        evidence_complete=evidence_complete,
        events=events,
        provenance=MutationProvenance(source.fixture_id, operator.value, expected_invariant),
    )


_CLEAN_CONTROL = TypeCFixture(
    fixture_id="type-c-clean-control",
    case_class="TYPE_C_CLEAN_CONTROL",
    evidence_complete=True,
    events=(
        _event("e1", EventKind.SUBMIT, "draft", "submitted"),
        _event("e2", EventKind.REVIEW, "submitted", "reviewed", approved=True),
        _event("e3", EventKind.VALIDATE, "reviewed", "validated"),
        _event("e4", EventKind.RELEASE, "validated", "released"),
    ),
    provenance=MutationProvenance(None, MutationOperator.BASELINE.value, "NO_MATERIAL_DEVIATION"),
)
_MISSING_REVIEW = _derive_fixture(
    fixture_id="type-c-missing-review",
    case_class="TYPE_C_PLANTED_DEFECT",
    source=_CLEAN_CONTROL,
    operator=MutationOperator.DELETE_REVIEW_EVENT,
    expected_invariant="MISSING_REVIEW_GATE",
)
FIXTURES = (
    _CLEAN_CONTROL,
    _MISSING_REVIEW,
    _derive_fixture(
        fixture_id="type-c-missing-review-equivalent-observation",
        case_class="TYPE_C_EQUIVALENT_MUTATION",
        source=_MISSING_REVIEW,
        operator=MutationOperator.INSERT_SEMANTIC_NO_OP,
        expected_invariant="MISSING_REVIEW_GATE",
    ),
    _derive_fixture(
        fixture_id="type-c-chain-break",
        case_class="TYPE_C_PLANTED_DEFECT",
        source=_CLEAN_CONTROL,
        operator=MutationOperator.SUBSTITUTE_REVIEW_INPUT,
        expected_invariant="EVIDENCE_CHAIN_BREAK",
    ),
    _derive_fixture(
        fixture_id="type-c-insufficient-evidence",
        case_class="TYPE_C_INSUFFICIENT_EVIDENCE",
        source=_CLEAN_CONTROL,
        operator=MutationOperator.REDACT_REQUIRED_EVENTS,
        expected_invariant="INSUFFICIENT_EVIDENCE_ABSTAIN",
    ),
    _derive_fixture(
        fixture_id="type-c-missing-submit",
        case_class="TYPE_C_PLANTED_DEFECT",
        source=_CLEAN_CONTROL,
        operator=MutationOperator.DELETE_SUBMIT_EVENT,
        expected_invariant="MISSING_SUBMIT_EVENT",
    ),
    _derive_fixture(
        fixture_id="type-c-validation-before-submit",
        case_class="TYPE_C_PLANTED_DEFECT",
        source=_CLEAN_CONTROL,
        operator=MutationOperator.SWAP_SUBMIT_AND_VALIDATE_KINDS,
        expected_invariant="INVALID_WORKFLOW_ORDER",
    ),
    _derive_fixture(
        fixture_id="type-c-duplicate-submit",
        case_class="TYPE_C_PLANTED_DEFECT",
        source=_CLEAN_CONTROL,
        operator=MutationOperator.INSERT_DUPLICATE_SUBMIT,
        expected_invariant="DUPLICATE_SUBMIT_EVENT",
    ),
)


def _validate_fixture_set(fixtures: tuple[TypeCFixture, ...]) -> None:
    fixture_by_id = {fixture.fixture_id: fixture for fixture in fixtures}
    fixture_ids = set(fixture_by_id)
    if len(fixture_ids) != len(fixtures):
        raise ValueError("Type C fixture_ids must be unique")
    for fixture in fixtures:
        source_id = fixture.provenance.source_fixture_id
        if source_id is not None and (
            source_id not in fixture_ids or source_id == fixture.fixture_id
        ):
            raise ValueError(f"invalid mutation source for fixture: {fixture.fixture_id}")
        try:
            operator = MutationOperator(fixture.provenance.operator)
        except ValueError as error:
            raise ValueError(
                f"invalid mutation operator for fixture: {fixture.fixture_id}"
            ) from error
        if source_id is None:
            if operator is not MutationOperator.BASELINE:
                raise ValueError(f"unbased mutation fixture: {fixture.fixture_id}")
            continue
        if operator is MutationOperator.BASELINE:
            raise ValueError(f"derived fixture uses baseline operator: {fixture.fixture_id}")
        expected_events, expected_evidence_complete = _apply_mutation(
            fixture_by_id[source_id], operator
        )
        if (
            fixture.events != expected_events
            or fixture.evidence_complete is not expected_evidence_complete
        ):
            raise ValueError(f"mutation replay mismatch for fixture: {fixture.fixture_id}")
