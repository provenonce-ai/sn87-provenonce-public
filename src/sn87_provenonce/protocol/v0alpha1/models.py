"""Strict transport-neutral models for the SN87 v0alpha1 conformance slice."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

PROTOCOL_VERSION = "sn87/0alpha1"
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Commitment = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResponseState(StrEnum):
    FINDINGS = "FINDINGS"
    NO_MATERIAL_DEVIATION = "NO_MATERIAL_DEVIATION"
    INSUFFICIENT_EVIDENCE_ABSTAIN = "INSUFFICIENT_EVIDENCE_ABSTAIN"


class DisclosureMode(StrEnum):
    METADATA = "METADATA"
    SELECTIVE_EVIDENCE = "SELECTIVE_EVIDENCE"
    CONFIDENTIAL_CHALLENGE = "CONFIDENTIAL_CHALLENGE"


class OracleClass(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class SourceBinding(StrictModel):
    source_id: NonEmptyStr
    commitment: Commitment


class EvidenceReference(StrictModel):
    commitment: Commitment
    predicate: NonEmptyStr


class DisclosurePolicy(StrictModel):
    policy_id: NonEmptyStr
    mode: DisclosureMode
    allowed_evidence_predicates: tuple[NonEmptyStr, ...] = ()
    privacy_budget: UnitInterval


class AssuranceCapsule(StrictModel):
    capsule_id: NonEmptyStr
    protocol_version: NonEmptyStr = PROTOCOL_VERSION
    signal: dict[str, Any]
    orchestration: dict[str, Any]
    constraints: tuple[dict[str, Any], ...]
    observed_paths: tuple[dict[str, Any], ...]
    pipeline: dict[str, Any]
    evidence: tuple[EvidenceReference, ...]
    context: dict[str, Any]
    source_bindings: tuple[SourceBinding, ...] = Field(min_length=1)
    disclosure_policy: DisclosurePolicy
    mapping_confidence: UnitInterval
    limitations: tuple[NonEmptyStr, ...] = ()


class OracleBinding(StrictModel):
    oracle_class: OracleClass
    identifier: NonEmptyStr
    commitment: Commitment | None = None
    reliability: Annotated[float, Field(gt=0.0, le=1.0)] | None = None
    reliability_method: NonEmptyStr | None = None

    @model_validator(mode="after")
    def require_type_d_reliability(self) -> Self:
        missing_type_d_fields = (
            self.commitment is None
            or self.reliability is None
            or self.reliability_method is None
        )
        if self.oracle_class is OracleClass.D and missing_type_d_fields:
            raise ValueError(
                "Type D oracle bindings require commitment, reliability, and reliability_method"
            )
        return self


class CostBudget(StrictModel):
    seconds: Annotated[float, Field(gt=0.0)]
    credits: Annotated[float, Field(ge=0.0)]
    privacy_budget: UnitInterval


class AdmissibilityDeclaration(StrictModel):
    challenge_class: NonEmptyStr
    challenge_class_version: NonEmptyStr
    claim_types: tuple[NonEmptyStr, ...] = Field(min_length=1)
    oracle_bindings: tuple[OracleBinding, ...] = Field(min_length=1)
    residual_fields: tuple[NonEmptyStr, ...] = ()
    disclosure_modes: tuple[DisclosureMode, ...] = Field(min_length=1)
    max_cost: CostBudget


class AssuranceRequest(StrictModel):
    protocol_version: NonEmptyStr = PROTOCOL_VERSION
    challenge_id: NonEmptyStr
    challenge_class: NonEmptyStr
    capsule: AssuranceCapsule
    visible_policy: AdmissibilityDeclaration
    hidden_commitment: Commitment
    nonce: NonEmptyStr
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value

    @model_validator(mode="after")
    def require_consistent_contract(self) -> Self:
        if self.capsule.protocol_version != self.protocol_version:
            raise ValueError("capsule and request protocol versions must match")
        if self.visible_policy.challenge_class != self.challenge_class:
            raise ValueError("visible policy and request challenge classes must match")
        if self.capsule.disclosure_policy.mode not in self.visible_policy.disclosure_modes:
            raise ValueError("capsule disclosure mode is not admissible for this challenge")
        return self


class AssuranceFinding(StrictModel):
    finding_id: NonEmptyStr
    challenge_id: NonEmptyStr
    finding_type: NonEmptyStr
    claim: NonEmptyStr
    severity: UnitInterval
    confidence: UnitInterval | None = None
    oracle_class: OracleClass
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    counterfactual_path: NonEmptyStr | None = None
    limitations: tuple[NonEmptyStr, ...] = ()
    recommended_action: NonEmptyStr


class CalibrationReport(StrictModel):
    method: NonEmptyStr
    claim_confidences: dict[NonEmptyStr, UnitInterval] = Field(min_length=1)


class AssuranceResponse(StrictModel):
    protocol_version: NonEmptyStr = PROTOCOL_VERSION
    challenge_id: NonEmptyStr
    response_state: ResponseState
    rationale: NonEmptyStr
    findings: tuple[AssuranceFinding, ...] | None = None
    counterfactual_paths: tuple[NonEmptyStr, ...] | None = None
    confidence_report: CalibrationReport | None = None
    evidence_requests: tuple[NonEmptyStr, ...] | None = None
    miner_commitment: Commitment | None = None

    @model_validator(mode="after")
    def enforce_response_state(self) -> Self:
        findings = self.findings or ()
        if self.response_state is ResponseState.FINDINGS and not findings:
            raise ValueError("FINDINGS responses require at least one finding")
        if self.response_state is not ResponseState.FINDINGS and findings:
            raise ValueError("findings are allowed only for FINDINGS responses")
        finding_ids = tuple(finding.finding_id for finding in findings)
        if findings:
            for finding in findings:
                if finding.challenge_id != self.challenge_id:
                    raise ValueError("every finding must bind to the response challenge_id")
            missing_finding_confidence = any(
                finding.confidence is None for finding in findings
            )
            if missing_finding_confidence and self.confidence_report is None:
                raise ValueError(
                    "FINDINGS responses require confidence on every finding or a confidence_report"
                )
        if self.confidence_report is not None:
            if len(set(finding_ids)) != len(finding_ids):
                raise ValueError(
                    "confidence_report cannot bind response findings with duplicate IDs"
                )
            report_ids = set(self.confidence_report.claim_confidences)
            if report_ids != set(finding_ids):
                raise ValueError(
                    "confidence_report claim IDs must exactly match response finding IDs"
                )
        return self


class IntegrityGateResult(StrictModel):
    schema_valid: bool
    policy_valid: bool
    signature_valid: bool
    nonce_valid: bool
    evidence_valid: bool
    deadline_valid: bool
    failures: tuple[NonEmptyStr, ...] = ()

    @property
    def passed(self) -> bool:
        return all(
            (
                self.schema_valid,
                self.policy_valid,
                self.signature_valid,
                self.nonce_valid,
                self.evidence_valid,
                self.deadline_valid,
            )
        )
