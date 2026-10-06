"""Bounded offline candidate artifacts for the transparent Type-C corpus."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from sn87_provenonce import evidence_filesystem
from sn87_provenonce.protocol.v0alpha1 import (
    PROTOCOL_VERSION,
    AssuranceResponse,
    canonical_sha256,
    parse_json_strict,
)
from sn87_provenonce.simulation.type_c import FIXTURES
from sn87_provenonce.simulation.type_c import SIMULATION_VERSION as REFERENCE_ORACLE_VERSION
from sn87_provenonce.simulation.type_c_conformance import (
    CONFORMANCE_VERSION,
    CandidateCase,
    evaluate_candidate,
)

ARTIFACT_TYPE = "sn87-transparent-type-c-candidate-artifact"
ARTIFACT_VERSION = f"{ARTIFACT_TYPE}/0alpha1"
REPORT_VERSION = "type-c-offline-candidate-conformance/0alpha1"
CLAIM_STATE = "IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_OFFLINE_ARTIFACT_CONFORMANCE_ONLY"
NORMALIZED_ARTIFACT_COMMITMENT_DOMAIN = "SN87:TYPE_C_CANDIDATE_ARTIFACT:v0alpha1"
REPORT_COMMITMENT_DOMAIN = "SN87:TYPE_C_CANDIDATE_ARTIFACT_REPORT:v0alpha1"
# Pinned so this module imports without the private reference executor. It is the
# ``report_commitment`` of ``type_c_reference.run_type_c_simulation()``; a test asserts the
# equality wherever the executor is present, so a stale pin fails there.
REFERENCE_ORACLE_REPORT_COMMITMENT = (
    "sha256:354472f0ab5ba0d1e863b24f509c395a913e06a5616e0e3f3faab0916432d9ec"
)

MAX_ARTIFACT_BYTES = 262_144
MAX_JSON_DEPTH = 24
MAX_STRING_CHARACTERS = 8_192
MAX_CANDIDATE_ID_CHARACTERS = 128
MAX_FINDINGS_PER_RESPONSE = 32
MAX_EVIDENCE_REFERENCES_PER_FINDING = 16

BoundedStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_STRING_CHARACTERS),
]
CandidateId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_CANDIDATE_ID_CHARACTERS,
    ),
]


class CandidateArtifactError(ValueError):
    """A bounded, caller-safe candidate artifact failure."""


class _StrictArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateArtifactCase(_StrictArtifactModel):
    fixture_id: BoundedStr
    response: AssuranceResponse

    @model_validator(mode="after")
    def enforce_local_resource_limits(self) -> Self:
        if self.fixture_id != self.response.challenge_id:
            raise ValueError("fixture_id must equal response.challenge_id")
        findings = self.response.findings or ()
        if len(findings) > MAX_FINDINGS_PER_RESPONSE:
            raise ValueError("response exceeds the finding limit")
        if any(len(finding.evidence) > MAX_EVIDENCE_REFERENCES_PER_FINDING for finding in findings):
            raise ValueError("finding exceeds the Evidence-reference limit")
        return self


class TypeCCandidateArtifact(_StrictArtifactModel):
    artifact_type: Literal[ARTIFACT_TYPE]
    artifact_version: Literal[ARTIFACT_VERSION]
    protocol_version: Literal[PROTOCOL_VERSION]
    conformance_version: Literal[CONFORMANCE_VERSION]
    reference_oracle_version: Literal[REFERENCE_ORACLE_VERSION]
    reference_oracle_report_commitment: Literal[REFERENCE_ORACLE_REPORT_COMMITMENT]
    candidate_id: CandidateId
    cases: tuple[CandidateArtifactCase, ...] = Field(
        min_length=len(FIXTURES), max_length=len(FIXTURES)
    )

    @model_validator(mode="after")
    def enforce_exact_envelope_and_corpus(self) -> Self:
        expected = {
            "artifact_type": ARTIFACT_TYPE,
            "artifact_version": ARTIFACT_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "conformance_version": CONFORMANCE_VERSION,
            "reference_oracle_version": REFERENCE_ORACLE_VERSION,
            "reference_oracle_report_commitment": REFERENCE_ORACLE_REPORT_COMMITMENT,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"{field_name} does not match the local contract")

        supplied_ids = [case.fixture_id for case in self.cases]
        if len(supplied_ids) != len(set(supplied_ids)):
            raise ValueError("candidate artifact fixture_ids must be unique")
        expected_ids = [fixture.fixture_id for fixture in FIXTURES]
        if set(supplied_ids) != set(expected_ids):
            raise ValueError("candidate artifact must contain the exact transparent fixture set")
        return self

    def cases_in_fixture_order(self) -> tuple[CandidateArtifactCase, ...]:
        by_fixture = {case.fixture_id: case for case in self.cases}
        return tuple(by_fixture[fixture.fixture_id] for fixture in FIXTURES)

    @property
    def normalized_commitment(self) -> str:
        normalized = self.model_dump(mode="json")
        normalized["cases"] = [
            case.model_dump(mode="json") for case in self.cases_in_fixture_order()
        ]
        return canonical_sha256(normalized, domain=NORMALIZED_ARTIFACT_COMMITMENT_DOMAIN)


def raw_sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def read_bounded_regular_file(path: Path, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> bytes:
    """Read one exact regular-file snapshot without following links or exceeding a byte cap."""

    return evidence_filesystem.read_bounded_regular_file(
        path,
        max_bytes,
        label="candidate artifact",
        error_type=CandidateArtifactError,
    )


def _enforce_json_limits(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise CandidateArtifactError("candidate artifact exceeds the JSON depth limit")
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARACTERS:
            raise CandidateArtifactError("candidate artifact contains an oversized string")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise CandidateArtifactError(
                "candidate artifact contains an invalid Unicode scalar"
            ) from error
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise CandidateArtifactError("candidate artifact contains a non-finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            _enforce_json_limits(key, depth=depth + 1)
            _enforce_json_limits(item, depth=depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _enforce_json_limits(item, depth=depth + 1)


def parse_candidate_artifact(payload: bytes) -> TypeCCandidateArtifact:
    """Parse and validate one exact candidate artifact byte snapshot."""

    if not isinstance(payload, bytes):
        raise CandidateArtifactError("candidate artifact payload must be bytes")
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise CandidateArtifactError(
            f"candidate artifact exceeds the {MAX_ARTIFACT_BYTES}-byte limit"
        )
    if not payload or not payload.strip():
        raise CandidateArtifactError("candidate artifact is empty")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise CandidateArtifactError("candidate artifact must not contain a UTF-8 BOM")
    try:
        text = payload.decode("utf-8", errors="strict")
        parsed = parse_json_strict(text)
        _enforce_json_limits(parsed)
        if not isinstance(parsed, dict):
            raise CandidateArtifactError("candidate artifact root must be an object")
        return TypeCCandidateArtifact.model_validate(parsed)
    except CandidateArtifactError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        ValidationError,
        ValueError,
    ) as error:
        raise CandidateArtifactError(f"invalid candidate artifact: {error}") from error


def run_type_c_candidate_artifact_bytes(payload: bytes) -> dict[str, Any]:
    """Evaluate one validated offline artifact in canonical fixture order."""

    artifact = parse_candidate_artifact(payload)
    by_fixture = {fixture.fixture_id: fixture for fixture in FIXTURES}
    results = []
    for supplied in artifact.cases_in_fixture_order():
        case = CandidateCase(
            candidate_id=f"{artifact.candidate_id}:{supplied.fixture_id}",
            fixture_id=supplied.fixture_id,
            response=supplied.response,
        )
        results.append(evaluate_candidate(case, by_fixture[supplied.fixture_id]))

    body: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "claim_state": CLAIM_STATE,
        "source_artifact_sha256": raw_sha256(payload),
        "normalized_artifact_commitment": artifact.normalized_commitment,
        "candidate_id": artifact.candidate_id,
        "artifact_version": artifact.artifact_version,
        "conformance_version": artifact.conformance_version,
        "reference_oracle_version": artifact.reference_oracle_version,
        "reference_oracle_report_commitment": artifact.reference_oracle_report_commitment,
        "fixture_order": [fixture.fixture_id for fixture in FIXTURES],
        "limits": {
            "max_artifact_bytes_inclusive": MAX_ARTIFACT_BYTES,
            "exact_case_count": len(FIXTURES),
            "max_json_depth_inclusive": MAX_JSON_DEPTH,
            "max_string_characters_inclusive": MAX_STRING_CHARACTERS,
            "max_findings_per_response_inclusive": MAX_FINDINGS_PER_RESPONSE,
            "max_evidence_references_per_finding_inclusive": (MAX_EVIDENCE_REFERENCES_PER_FINDING),
        },
        "boundaries": {
            "miner_identity_or_origin_proven": False,
            "candidate_text_semantics_evaluated": False,
            "confidence_or_severity_calibrated": False,
            "hidden_truth": False,
            "normative_scoring": False,
            "ranking": False,
            "weight_planning": False,
            "network": False,
            "wallet": False,
            "chain_submission": False,
            "testnet": False,
            "g1_acceptance": False,
            "production_evidence": False,
        },
        "cases": results,
        "summary": {
            "case_count": len(results),
            "passed_count": sum(result["passed"] for result in results),
            "failed_count": sum(not result["passed"] for result in results),
            "all_cases_conformant": all(result["passed"] for result in results),
        },
    }
    return body | {"report_commitment": canonical_sha256(body, domain=REPORT_COMMITMENT_DOMAIN)}


def run_type_c_candidate_artifact(path: Path) -> dict[str, Any]:
    return run_type_c_candidate_artifact_bytes(read_bounded_regular_file(path))
