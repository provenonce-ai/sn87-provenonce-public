"""Transport-neutral reference-miner response boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from sn87_provenonce.protocol.v0alpha1 import AssuranceRequest, AssuranceResponse


class AssuranceAnalyzer(Protocol):
    """A miner-owned analysis engine; strategy and model choice remain implementation-specific."""

    async def analyze(self, request: AssuranceRequest) -> AssuranceResponse: ...


class MinerContractViolation(ValueError):
    """A stable failure at the reference miner's response-emission boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ReferenceMiner:
    """Run an analyzer and refuse to emit a response bound to another request.

    `AssuranceResponse` itself enforces the three response-state shapes. This boundary adds
    the request-relative version and challenge bindings that a standalone model cannot know.
    Analyzer exceptions deliberately propagate: an operational failure is not evidence for
    an `INSUFFICIENT_EVIDENCE_ABSTAIN` response.
    """

    analyzer: AssuranceAnalyzer

    async def answer(self, request: AssuranceRequest) -> AssuranceResponse:
        candidate = await self.analyzer.analyze(request)
        if not isinstance(candidate, AssuranceResponse):
            raise MinerContractViolation("MINER_RESPONSE_TYPE_INVALID")
        try:
            response = AssuranceResponse.model_validate(candidate.model_dump(mode="python"))
        except ValidationError as error:
            raise MinerContractViolation("MINER_RESPONSE_SCHEMA_INVALID") from error
        if response.protocol_version != request.protocol_version:
            raise MinerContractViolation("MINER_PROTOCOL_VERSION_MISMATCH")
        if response.challenge_id != request.challenge_id:
            raise MinerContractViolation("MINER_CHALLENGE_ID_MISMATCH")
        return response
