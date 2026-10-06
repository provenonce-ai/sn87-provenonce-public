from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sn87_provenonce.protocol.v0alpha1 import (
    AssuranceRequest,
    AssuranceResponse,
    evaluate_integrity_gate,
)

VECTORS = Path(__file__).resolve().parents[2] / "protocol" / "v0alpha1" / "test-vectors"


def load_model(model: type, name: str):
    payload = json.loads((VECTORS / name).read_text(encoding="utf-8"))
    return model.model_validate(payload)


def test_all_integrity_factors_must_pass() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")
    result = evaluate_integrity_gate(
        request,
        response,
        received_at=datetime(2026, 9, 4, 0, 59, tzinfo=UTC),
        signature_valid=True,
        nonce_valid=True,
        policy_valid=True,
        evidence_valid=True,
    )
    assert result.passed
    assert result.failures == ()


def test_integrity_failures_do_not_compensate() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")
    result = evaluate_integrity_gate(
        request,
        response,
        received_at=datetime(2026, 9, 4, 1, 1, tzinfo=UTC),
        signature_valid=False,
        nonce_valid=True,
        policy_valid=True,
        evidence_valid=False,
    )
    assert not result.passed
    assert result.signature_valid is False
    assert result.evidence_valid is False
    assert result.deadline_valid is False
    assert result.failures == ("DEADLINE_EXPIRED", "SIGNATURE_INVALID", "EVIDENCE_INVALID")


def test_negative_response_does_not_invent_evidence_requirement() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.no-material-deviation.json")
    result = evaluate_integrity_gate(
        request,
        response,
        received_at=datetime(2026, 9, 4, 0, 59, tzinfo=UTC),
        signature_valid=True,
        nonce_valid=True,
        policy_valid=True,
        evidence_valid=False,
    )
    assert result.passed
    assert result.evidence_valid is True


@pytest.mark.parametrize(
    ("overrides", "expected_failure"),
    [
        ({"signature_valid": False}, "SIGNATURE_INVALID"),
        ({"nonce_valid": False}, "NONCE_INVALID"),
        ({"policy_valid": False}, "POLICY_INVALID"),
        ({"evidence_valid": False}, "EVIDENCE_INVALID"),
    ],
)
def test_each_external_integrity_factor_fails_independently(
    overrides: dict[str, bool], expected_failure: str
) -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")
    factors = {
        "signature_valid": True,
        "nonce_valid": True,
        "policy_valid": True,
        "evidence_valid": True,
    }
    factors.update(overrides)
    result = evaluate_integrity_gate(
        request,
        response,
        received_at=datetime(2026, 9, 4, 0, 59, tzinfo=UTC),
        **factors,
    )
    assert not result.passed
    assert result.failures == (expected_failure,)


def test_schema_factor_fails_independently() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json").model_copy(
        update={"protocol_version": "sn87/incompatible"}
    )
    result = evaluate_integrity_gate(
        request,
        response,
        received_at=datetime(2026, 9, 4, 0, 59, tzinfo=UTC),
        signature_valid=True,
        nonce_valid=True,
        policy_valid=True,
        evidence_valid=True,
    )
    assert not result.passed
    assert result.schema_valid is False
    assert result.failures == ("PROTOCOL_VERSION_MISMATCH",)


def test_deadline_factor_fails_independently() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")
    result = evaluate_integrity_gate(
        request,
        response,
        received_at=datetime(2026, 9, 4, 1, 1, tzinfo=UTC),
        signature_valid=True,
        nonce_valid=True,
        policy_valid=True,
        evidence_valid=True,
    )
    assert not result.passed
    assert result.deadline_valid is False
    assert result.failures == ("DEADLINE_EXPIRED",)
