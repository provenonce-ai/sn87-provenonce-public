"""The only module that imports the transport extra (starlette, valkey, the chain SDK)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from sn87_provenonce.pilot.sender_policy import (
    AllowAnySender,
    PermitSnapshot,
    SenderPolicy,
    SnapshotError,
)
from sn87_provenonce.pilot.server import create_app
from sn87_provenonce.pilot.transport import BoundaryError, SharedReplayStore, TransportConfig

from .announcement import WELL_KNOWN_PATH


def make_store(url: str, receiver: str) -> SharedReplayStore:
    return SharedReplayStore.from_url(url, receiver=receiver, domain="request")


def probe(store: SharedReplayStore) -> str:
    """Read-only checks: the server answers PING and its eviction policy is ``noeviction``."""
    try:
        if not store.client.ping():
            return "REPLAY_STORE_UNAVAILABLE"
        store._require_noeviction()
    except BoundaryError as error:
        return str(error)
    except Exception:
        return "REPLAY_STORE_UNAVAILABLE"
    return "ok"


# The public testnet 582 endpoint and genesis hash, as in scripts/chain_read.py.
DEFAULT_CHAIN_ENDPOINT = "wss://test.chain.opentensor.ai:443"
DEFAULT_CHAIN_GENESIS = "0x8f9cf856bf558a14440e75569c9e58594757048d7b3a84b5d25f6bd978263105"


class ChainPermitProvider:
    """READ-ONLY metagraph read: the hotkeys holding validator_permit on one netuid.

    Storage queries only (``SubnetworkN``, ``ValidatorPermit``, ``Keys``) through the public
    SDK, pinned to one endpoint whose genesis hash must match before any answer is used. It
    holds no wallet and builds no extrinsic. The SDK is imported on first use."""

    def __init__(self, endpoint: str = DEFAULT_CHAIN_ENDPOINT,
                 genesis: str = DEFAULT_CHAIN_GENESIS, *,
                 subtensor_factory: Callable[[str], Any] | None = None,
                 deadline_seconds: float = 45.0,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._endpoint, self._genesis = endpoint, genesis
        self._deadline_seconds, self._monotonic = deadline_seconds, monotonic
        self._factory = subtensor_factory or self._default_factory
        self._sub: Any = None
        self._verified = False

    @staticmethod
    def _default_factory(endpoint: str) -> Any:
        import bittensor as bt

        return bt.Subtensor(endpoint, fallback_endpoints=[], archive_endpoints=[])

    @staticmethod
    def _storage() -> Any:
        import bittensor as bt

        return bt.storage.SubtensorModule

    def _connect(self) -> Any:
        if self._sub is None:
            self._sub = self._factory(self._endpoint)
        if not self._verified:
            sub = self._sub
            if sub._call(sub._client._substrate.block_hash(0)) != self._genesis:
                self._sub = None
                raise SnapshotError("CHAIN_GENESIS_MISMATCH")
            self._verified = True
        return self._sub

    def describe(self) -> str:
        return f"{self._endpoint} (genesis {self._genesis})"

    def _query(self, name: str, params: list[int], block: int) -> Any:
        """One storage query pinned to ``block``, refused once the read's deadline passed.
        (The SDK's own socket timeouts are not reachable here; the policy also abandons a read
        that hangs inside one call.)"""
        if self._monotonic() > self._deadline:
            raise SnapshotError("SENDER_SNAPSHOT_TIMEOUT")
        return self._connect().query(getattr(self._storage(), name), params, block=block)

    def fetch(self, netuid: int) -> PermitSnapshot:
        try:
            self._deadline = self._monotonic() + self._deadline_seconds
            sub = self._connect()
            block = sub.block                 # read once; every query below is pinned to it
            if type(block) is not int:
                raise SnapshotError("SENDER_SNAPSHOT_UNUSABLE")
            size = self._query("SubnetworkN", [netuid], block)
            permits = self._query("ValidatorPermit", [netuid], block)
            if type(size) is not int or not isinstance(permits, list):
                raise SnapshotError("SENDER_SNAPSHOT_UNUSABLE")
            hotkeys = set()
            for uid in range(min(size, len(permits))):
                if permits[uid]:
                    key = self._query("Keys", [netuid, uid], block)
                    if isinstance(key, str) and key:
                        hotkeys.add(key)
        except SnapshotError:
            raise
        except Exception:
            self._sub, self._verified = None, False  # reconnect next time
            raise SnapshotError("SENDER_SNAPSHOT_READ_FAILED") from None
        return PermitSnapshot(netuid=netuid, permitted=frozenset(hotkeys), block=block)


def make_permit_provider(endpoint: str, genesis: str) -> ChainPermitProvider:
    return ChainPermitProvider(endpoint, genesis)


def make_app(
    handle: Callable[[dict], dict], keypair: Any, store: SharedReplayStore, *,
    max_inflight: int, announcement_record: bytes | None,
    sender_policy: SenderPolicy | AllowAnySender,
) -> Any:
    app = create_app(
        signer=keypair, store=store, handle=handle,
        config=TransportConfig(receiver_ss58=keypair.ss58_address, max_inflight=max_inflight),
        sender_policy=sender_policy,
    )
    if announcement_record is not None:
        async def announcement(_: Request) -> Response:
            return Response(announcement_record, media_type="application/json",
                            headers={"Cache-Control": "no-store"})
        app.add_route(WELL_KNOWN_PATH, announcement, methods=["GET"])
    return app


def probe_exchange(
    endpoint: str, miner_hotkey: str, valkey_url: str, *, wait_seconds: float = 30.0,
    timeout_ms: int = 10_000, caller: Any = None,
) -> dict:
    """Send one signed request for a fixture capsule from a fresh random caller key and return
    the verified differential. With no ``caller`` the key is a fresh random one that exists only
    in this process; a server with the sender allowlist on refuses it (``SENDER_NOT_PERMITTED``),
    so against such a server pass the operator's probe key as ``caller``. The caller's own
    replay store (domain ``response``) quarantines itself for one freshness window the first time
    it is used, so this waits for it."""
    import asyncio
    import time

    from bittensor import sp_core

    from sn87_provenonce.institutional_v02.fixtures import build_case
    from sn87_provenonce.pilot.client import exchange

    caller = caller or sp_core.Keypair.create_from_mnemonic(sp_core.Keypair.generate_mnemonic())
    store = SharedReplayStore.from_url(valkey_url, receiver=caller.ss58_address,
                                       domain="response")
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            if store.ready():
                break
        except BoundaryError as error:
            if str(error) != "REPLAY_STORE_WARMING" or time.monotonic() > deadline:
                raise
        time.sleep(0.25)
    return asyncio.run(exchange(
        endpoint=endpoint, capsule=build_case("stale_authority"), signer=caller,
        receiver=miner_hotkey, store=store, timeout_ms=timeout_ms))
