from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sn87_provenonce.protocol.v0alpha1 import AssuranceRequest, AssuranceResponse
from sn87_provenonce.runtime import (
    ContentVerification,
    ExchangeStatus,
    InMemoryMinerGateway,
    LocalMinerEndpoint,
    execute_validator_round,
)

VECTORS = Path(__file__).resolve().parents[2] / "protocol" / "v0alpha1" / "test-vectors"
RECEIVED_AT = datetime(2026, 9, 4, 0, 59, tzinfo=UTC)


def load_model(model: type, name: str):
    return model.model_validate(json.loads((VECTORS / name).read_text(encoding="utf-8")))


class FixedVerifier:
    def __init__(self, *, policy_valid: bool = True, evidence_valid: bool = True) -> None:
        self.policy_valid = policy_valid
        self.evidence_valid = evidence_valid

    async def verify(self, miner_id, request, response):
        return ContentVerification(
            policy_valid=self.policy_valid,
            evidence_valid=self.evidence_valid,
        )


def endpoint(response, *, signature_valid=True, nonce_valid=True):
    async def handler(_request):
        return response

    return LocalMinerEndpoint(
        handler=handler,
        received_at=RECEIVED_AT,
        signature_valid=signature_valid,
        nonce_valid=nonce_valid,
    )


def run_round(request, miner_ids, gateway, verifier=None, timeout_seconds=0.1):
    if verifier is None:
        verifier = FixedVerifier()
    return asyncio.run(
        execute_validator_round(
            request,
            miner_ids,
            gateway,
            verifier,
            timeout_seconds=timeout_seconds,
        )
    )


def test_round_passes_all_three_canonical_response_states_in_input_order() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    responses = {
        "findings": load_model(AssuranceResponse, "response.findings.json"),
        "clean": load_model(AssuranceResponse, "response.no-material-deviation.json"),
        "abstain": load_model(AssuranceResponse, "response.abstain.json"),
    }
    miner_ids = ("findings", "clean", "abstain")
    result = run_round(
        request,
        miner_ids,
        InMemoryMinerGateway({key: endpoint(value) for key, value in responses.items()}),
    )

    assert tuple(outcome.miner_id for outcome in result.outcomes) == miner_ids
    assert all(outcome.status is ExchangeStatus.INTEGRITY_PASSED for outcome in result.outcomes)
    assert result.to_dict()["scoring_performed"] is False
    assert result.to_dict()["broadcast_capable"] is False


def test_failed_signature_is_rejected_without_compensation() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")
    result = run_round(
        request,
        ("unsigned",),
        InMemoryMinerGateway({"unsigned": endpoint(response, signature_valid=False)}),
    )

    outcome = result.outcomes[0]
    assert outcome.status is ExchangeStatus.INTEGRITY_FAILED
    assert outcome.integrity_gate is not None
    assert outcome.integrity_gate.failures == ("SIGNATURE_INVALID",)


def test_timeout_is_isolated_from_sibling_exchange() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")

    async def slow(_request):
        await asyncio.sleep(0.05)
        return response

    gateway = InMemoryMinerGateway(
        {
            "slow": LocalMinerEndpoint(slow, RECEIVED_AT, True, True),
            "fast": endpoint(response),
        }
    )
    result = run_round(request, ("slow", "fast"), gateway, timeout_seconds=0.01)

    assert result.outcomes[0].status is ExchangeStatus.TIMEOUT
    assert result.outcomes[0].failure_code == "MINER_EXCHANGE_TIMEOUT"
    assert result.outcomes[1].status is ExchangeStatus.INTEGRITY_PASSED


def test_transport_exception_is_sanitized_and_isolated() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")

    async def broken(_request):
        raise RuntimeError("secret-bearing adapter detail")

    gateway = InMemoryMinerGateway(
        {
            "broken": LocalMinerEndpoint(broken, RECEIVED_AT, True, True),
            "healthy": endpoint(response),
        }
    )
    result = run_round(request, ("broken", "healthy"), gateway)
    payload = result.to_dict()

    assert result.outcomes[0].status is ExchangeStatus.TRANSPORT_ERROR
    assert result.outcomes[1].status is ExchangeStatus.INTEGRITY_PASSED
    assert "secret-bearing" not in json.dumps(payload)


@pytest.mark.parametrize("miner_ids", [("duplicate", "duplicate")])
def test_duplicate_miner_ids_are_rejected(miner_ids) -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    with pytest.raises(ValueError, match="unique"):
        run_round(request, miner_ids, InMemoryMinerGateway({}))


def test_empty_miner_id_is_rejected() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    with pytest.raises(ValueError, match="non-empty"):
        run_round(request, ("",), InMemoryMinerGateway({}))


def test_verifier_exception_is_sanitized_and_isolated() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")

    class BrokenVerifier:
        async def verify(self, miner_id, request, response):
            if miner_id == "broken":
                raise RuntimeError("private verification detail")
            return ContentVerification(policy_valid=True, evidence_valid=True)

    gateway = InMemoryMinerGateway({"broken": endpoint(response), "healthy": endpoint(response)})
    result = run_round(request, ("broken", "healthy"), gateway, BrokenVerifier())
    payload = result.to_dict()

    assert result.outcomes[0].status is ExchangeStatus.VERIFICATION_ERROR
    assert result.outcomes[1].status is ExchangeStatus.INTEGRITY_PASSED
    assert "private verification detail" not in json.dumps(payload)


def test_slow_verifier_cannot_block_sibling_timeout_or_completion() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json")

    class SelectiveVerifier:
        async def verify(self, miner_id, request, response):
            if miner_id == "slow-verification":
                await asyncio.sleep(0.05)
            return ContentVerification(policy_valid=True, evidence_valid=True)

    gateway = InMemoryMinerGateway(
        {
            "slow-verification": endpoint(response),
            "healthy": endpoint(response),
        }
    )
    result = run_round(
        request,
        ("slow-verification", "healthy"),
        gateway,
        SelectiveVerifier(),
        timeout_seconds=0.01,
    )

    assert result.outcomes[0].status is ExchangeStatus.TIMEOUT
    assert result.outcomes[1].status is ExchangeStatus.INTEGRITY_PASSED


def test_non_positive_timeout_is_rejected() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    with pytest.raises(ValueError, match="positive"):
        run_round(request, (), InMemoryMinerGateway({}), timeout_seconds=0)
