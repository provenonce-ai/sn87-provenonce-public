"""The only module that imports the transport extra (starlette, valkey, the chain SDK)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

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


def make_app(
    handle: Callable[[dict], dict], keypair: Any, store: SharedReplayStore, *,
    max_inflight: int, announcement_record: bytes | None,
) -> Any:
    app = create_app(
        signer=keypair, store=store, handle=handle,
        config=TransportConfig(receiver_ss58=keypair.ss58_address, max_inflight=max_inflight),
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
    the verified differential. The caller key exists only in this process. The caller's own
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
