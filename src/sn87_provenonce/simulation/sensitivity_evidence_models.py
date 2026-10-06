"""Strict machine-readable contracts for sensitivity evidence."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from sn87_provenonce.protocol.v0alpha1 import canonical_sha256, parse_json_strict
from sn87_provenonce.simulation.sensitivity_analysis import SensitivityAnalysisResult

REPORT_VERSION = "sn87/transparent-sensitivity-report/0alpha1"
CLAIM_STATE = "IMPLEMENTED_TESTED_TRANSPARENT_SENSITIVITY_EVIDENCE_ONLY"
REPORT_COMMITMENT_DOMAIN = "SN87:TRANSPARENT_SENSITIVITY_REPORT:v0alpha1"
BUNDLE_VERSION = "sn87/transparent-sensitivity-evidence-bundle/0alpha1"
MAX_REPORT_BYTES = 16_777_216
MAX_MANIFEST_BYTES = 16_384
Commitment = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class SensitivityEvidenceLimits(StrictEvidenceModel):
    max_source_bytes_inclusive: Literal[1_000_000]
    max_report_bytes_inclusive: Literal[16_777_216]
    max_manifest_bytes_inclusive: Literal[16_384]

    @field_validator("*", mode="before")
    @classmethod
    def require_exact_integers(cls, value: Any) -> int:
        if type(value) is not int:
            raise ValueError("evidence limits must be exact integers")
        return value


class SensitivityEvidenceBoundaries(StrictEvidenceModel):
    source_origin_proven: Literal[False]
    production_policy_selected: Literal[False]
    estimator_preference_defined: Literal[False]
    normative_scoring: Literal[False]
    winner_selected: Literal[False]
    ranking_defined: Literal[False]
    weight_policy_defined: Literal[False]
    g1_acceptance: Literal[False]
    hidden_truth: Literal[False]
    network: Literal[False]
    wallet: Literal[False]
    chain_action_defined: Literal[False]
    testnet: Literal[False]
    production_evidence: Literal[False]

    @field_validator("*", mode="before")
    @classmethod
    def require_boolean_false(cls, value: Any) -> bool:
        if value is not False:
            raise ValueError("evidence boundary must be the boolean false")
        return False


class SensitivityEvidenceReport(StrictEvidenceModel):
    report_version: Literal["sn87/transparent-sensitivity-report/0alpha1"]
    claim_state: Literal["IMPLEMENTED_TESTED_TRANSPARENT_SENSITIVITY_EVIDENCE_ONLY"]
    source_spec_sha256: Commitment
    normalized_spec_commitment: Commitment
    limits: SensitivityEvidenceLimits
    boundaries: SensitivityEvidenceBoundaries
    analysis_result: SensitivityAnalysisResult
    report_commitment: Commitment

    @field_validator("limits", "boundaries", "analysis_result", mode="before")
    @classmethod
    def snapshot_nested_models(cls, value: Any) -> Any:
        return value.model_dump(mode="json") if isinstance(value, BaseModel) else value

    @model_validator(mode="after")
    def verify_report_commitment(self) -> Self:
        body = self.model_dump(mode="json", exclude={"report_commitment"})
        if self.report_commitment != canonical_sha256(body, domain=REPORT_COMMITMENT_DOMAIN):
            raise ValueError("sensitivity report commitment mismatch")
        if self.normalized_spec_commitment != self.analysis_result.analysis_commitment:
            raise ValueError("report does not bind its normalized sensitivity specification")
        return self


class SensitivityEvidenceFiles(StrictEvidenceModel):
    sensitivity_spec_json: Commitment = Field(alias="sensitivity-spec.json")
    report_json: Commitment = Field(alias="report.json")


class SensitivityEvidenceManifest(StrictEvidenceModel):
    bundle_version: Literal["sn87/transparent-sensitivity-evidence-bundle/0alpha1"]
    claim_state: Literal["IMPLEMENTED_TESTED_TRANSPARENT_SENSITIVITY_EVIDENCE_ONLY"]
    files: SensitivityEvidenceFiles
    report_commitment: Commitment
    source_spec_sha256: Commitment
    normalized_spec_commitment: Commitment
    result_commitment: Commitment

    @field_validator("files", mode="before")
    @classmethod
    def snapshot_files(cls, value: Any) -> Any:
        return value.to_payload() if isinstance(value, SensitivityEvidenceFiles) else value

    @model_validator(mode="after")
    def verify_source_binding(self) -> Self:
        if self.files.sensitivity_spec_json != self.source_spec_sha256:
            raise ValueError("manifest source hash fields disagree")
        return self


def _bounded_json(value: str | bytes, limit: int, label: str) -> dict[str, Any]:
    if not isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be JSON text or bytes")
    size = len(value.encode("utf-8")) if isinstance(value, str) else len(value)
    if size > limit:
        raise ValueError(f"{label} cannot exceed {limit} bytes")
    payload = parse_json_strict(value)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be an object")
    return payload


def parse_sensitivity_evidence_report(value: str | bytes) -> SensitivityEvidenceReport:
    return SensitivityEvidenceReport.model_validate(
        _bounded_json(value, MAX_REPORT_BYTES, "sensitivity evidence report")
    )


def parse_sensitivity_evidence_manifest(value: str | bytes) -> SensitivityEvidenceManifest:
    return SensitivityEvidenceManifest.model_validate(
        _bounded_json(value, MAX_MANIFEST_BYTES, "sensitivity evidence manifest")
    )
