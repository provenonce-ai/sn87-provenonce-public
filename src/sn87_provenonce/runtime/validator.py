"""Deterministic validator orchestration without networking, scoring, or chain access."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sn87_provenonce.protocol.v0alpha1 import (
    AssuranceRequest,
    AssuranceResponse,
    IntegrityGateResult,
    evaluate_integrity_gate,
)


class ExchangeStatus(StrEnum):
    INTEGRITY_PASSED = "INTEGRITY_PASSED"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
    TIMEOUT = "TIMEOUT"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


@dataclass(frozen=True)
class TransportReceipt:
    """A typed response plus facts established by the future transport adapter."""

    response: AssuranceResponse
    received_at: datetime
    signature_valid: bool
    nonce_valid: bool


@dataclass(frozen=True)
class ContentVerification:
    """Facts established outside transport by policy and Evidence verification."""

    policy_valid: bool
    evidence_valid: bool


class MinerGateway(Protocol):
    async def request(self, miner_id: str, request: AssuranceRequest) -> TransportReceipt: ...


class ResponseVerifier(Protocol):
    async def verify(
        self,
        miner_id: str,
        request: AssuranceRequest,
        response: AssuranceResponse,
    ) -> ContentVerification: ...


@dataclass(frozen=True)
class MinerExchangeOutcome:
    miner_id: str
    status: ExchangeStatus
    response: AssuranceResponse | None = None
    integrity_gate: IntegrityGateResult | None = None
    failure_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "miner_id": self.miner_id,
            "status": self.status.value,
        }
        if self.response is not None:
            payload["response"] = self.response.model_dump(mode="json", exclude_none=True)
        if self.integrity_gate is not None:
            payload["integrity_gate"] = self.integrity_gate.model_dump(mode="json") | {
                "passed": self.integrity_gate.passed
            }
        if self.failure_code is not None:
            payload["failure_code"] = self.failure_code
        return payload


@dataclass(frozen=True)
class ValidatorRound:
    protocol_version: str
    challenge_id: str
    outcomes: tuple[MinerExchangeOutcome, ...]

    def to_dict(self) -> dict[str, object]:
        counts = Counter(outcome.status.value for outcome in self.outcomes)
        return {
            "claim_state": "IMPLEMENTED_TESTED_LOCAL_RUNTIME_ONLY",
            "mode": "LOCAL_TRANSPORT_NEUTRAL_VALIDATOR",
            "protocol_version": self.protocol_version,
            "challenge_id": self.challenge_id,
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "status_counts": dict(sorted(counts.items())),
            "scoring_performed": False,
            "weight_plan_created": False,
            "broadcast_capable": False,
        }


async def execute_validator_round(
    request: AssuranceRequest,
    miner_ids: tuple[str, ...],
    gateway: MinerGateway,
    verifier: ResponseVerifier,
    *,
    timeout_seconds: float,
) -> ValidatorRound:
    """Collect and gate miner responses while preserving requested miner order.

    Each exchange is isolated. A timeout or transport exception cannot cancel sibling
    exchanges, and no exception text is exposed in the result. This boundary performs no
    scoring, ranking, weight planning, wallet access, or chain mutation.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if any(not miner_id.strip() for miner_id in miner_ids):
        raise ValueError("miner_ids must be non-empty")
    if len(set(miner_ids)) != len(miner_ids):
        raise ValueError("miner_ids must be unique")

    async def exchange(miner_id: str) -> MinerExchangeOutcome:
        phase = "transport"
        try:
            async with asyncio.timeout(timeout_seconds):
                receipt = await gateway.request(miner_id, request)
                phase = "verification"
                verification = await verifier.verify(miner_id, request, receipt.response)
                gate = evaluate_integrity_gate(
                    request,
                    receipt.response,
                    received_at=receipt.received_at,
                    signature_valid=receipt.signature_valid,
                    nonce_valid=receipt.nonce_valid,
                    policy_valid=verification.policy_valid,
                    evidence_valid=verification.evidence_valid,
                )
        except TimeoutError:
            return MinerExchangeOutcome(
                miner_id=miner_id,
                status=ExchangeStatus.TIMEOUT,
                failure_code="MINER_EXCHANGE_TIMEOUT",
            )
        except Exception:
            if phase == "verification":
                return MinerExchangeOutcome(
                    miner_id=miner_id,
                    status=ExchangeStatus.VERIFICATION_ERROR,
                    failure_code="MINER_VERIFICATION_ERROR",
                )
            return MinerExchangeOutcome(
                miner_id=miner_id,
                status=ExchangeStatus.TRANSPORT_ERROR,
                failure_code="MINER_TRANSPORT_ERROR",
            )
        return MinerExchangeOutcome(
            miner_id=miner_id,
            status=(
                ExchangeStatus.INTEGRITY_PASSED if gate.passed else ExchangeStatus.INTEGRITY_FAILED
            ),
            response=receipt.response,
            integrity_gate=gate,
        )

    outcomes = await asyncio.gather(*(exchange(miner_id) for miner_id in miner_ids))
    return ValidatorRound(
        protocol_version=request.protocol_version,
        challenge_id=request.challenge_id,
        outcomes=tuple(outcomes),
    )
