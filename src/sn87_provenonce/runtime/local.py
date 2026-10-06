"""Explicit in-memory adapters for local conformance and failure-path testing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sn87_provenonce.protocol.v0alpha1 import AssuranceRequest, AssuranceResponse
from sn87_provenonce.runtime.validator import TransportReceipt

MinerHandler = Callable[[AssuranceRequest], Awaitable[AssuranceResponse]]


@dataclass(frozen=True)
class LocalMinerEndpoint:
    handler: MinerHandler
    received_at: datetime
    signature_valid: bool
    nonce_valid: bool


class InMemoryMinerGateway:
    """Routes requests to explicit local handlers; it never opens a network connection."""

    def __init__(self, endpoints: Mapping[str, LocalMinerEndpoint]) -> None:
        self._endpoints = dict(endpoints)

    async def request(self, miner_id: str, request: AssuranceRequest) -> TransportReceipt:
        endpoint = self._endpoints[miner_id]
        response = await endpoint.handler(request)
        return TransportReceipt(
            response=response,
            received_at=endpoint.received_at,
            signature_valid=endpoint.signature_valid,
            nonce_valid=endpoint.nonce_valid,
        )
