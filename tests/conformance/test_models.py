from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sn87_provenonce.protocol.v0alpha1 import AssuranceRequest, AssuranceResponse

VECTORS = Path(__file__).resolve().parents[2] / "protocol" / "v0alpha1" / "test-vectors"


def load(name: str) -> dict:
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    ["response.findings.json", "response.no-material-deviation.json", "response.abstain.json"],
)
def test_reference_responses_validate(name: str) -> None:
    AssuranceResponse.model_validate(load(name))


def test_reference_request_validates() -> None:
    AssuranceRequest.model_validate(load("request.metadata-clean.json"))


def test_findings_state_requires_findings() -> None:
    payload = load("response.no-material-deviation.json")
    payload["response_state"] = "FINDINGS"
    with pytest.raises(ValidationError, match="require at least one finding"):
        AssuranceResponse.model_validate(payload)


def test_negative_state_rejects_findings() -> None:
    payload = load("response.findings.json")
    payload["response_state"] = "NO_MATERIAL_DEVIATION"
    with pytest.raises(ValidationError, match="allowed only for FINDINGS"):
        AssuranceResponse.model_validate(payload)


def test_findings_require_evidence() -> None:
    payload = load("response.findings.json")
    payload["findings"][0]["evidence"] = []
    with pytest.raises(ValidationError):
        AssuranceResponse.model_validate(payload)


def test_findings_require_confidence_or_report() -> None:
    payload = load("response.findings.json")
    payload["findings"][0]["confidence"] = None
    with pytest.raises(ValidationError, match="confidence on every finding"):
        AssuranceResponse.model_validate(payload)


def test_confidence_report_must_cover_exact_finding_set() -> None:
    payload = load("response.findings.json")
    finding_id = payload["findings"][0]["finding_id"]
    payload["findings"][0]["confidence"] = None
    payload["confidence_report"] = {
        "method": "declared-per-finding",
        "claim_confidences": {finding_id: 0.81},
    }
    AssuranceResponse.model_validate(payload)

    payload["confidence_report"]["claim_confidences"] = {"unrelated-finding": 0.81}
    with pytest.raises(ValidationError, match="exactly match"):
        AssuranceResponse.model_validate(payload)


@pytest.mark.parametrize(
    "response_state",
    ["NO_MATERIAL_DEVIATION", "INSUFFICIENT_EVIDENCE_ABSTAIN"],
)
def test_response_without_findings_rejects_confidence_report(response_state: str) -> None:
    payload = load("response.no-material-deviation.json")
    payload["response_state"] = response_state
    payload["confidence_report"] = {
        "method": "declared-per-finding",
        "claim_confidences": {"ghost-finding": 0.81},
    }
    with pytest.raises(ValidationError, match="exactly match"):
        AssuranceResponse.model_validate(payload)


def test_models_reject_unknown_fields() -> None:
    payload = load("response.abstain.json")
    payload["uncommitted_extension"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AssuranceResponse.model_validate(payload)
