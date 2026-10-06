"""Authenticated caller with responder, receipt, exact-byte and deadline binding."""
from __future__ import annotations

import asyncio
import hashlib
import time
from functools import partial
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx
from bittensor import http_auth, resolve_signer

from sn87_provenonce.canonical import canonical_bytes, parse_canonical

from .transport import (
    PATH,
    VERSION,
    BoundaryError,
    SharedReplayStore,
    TransportConfig,
    verify_bytes,
)


def prepare_request(capsule: dict, signer: Any, receiver: str, *, timeout_ms: int = 10_000):
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 15_000:
        raise ValueError("invalid challenge timeout")
    envelope = {"schema_version": VERSION, "challenge_id": capsule["qid"],
                "deadline_ms": time.time_ns() // 1_000_000 + timeout_ms, "capsule": capsule}
    body = canonical_bytes(envelope)
    headers = http_auth.sign(signer, method="POST", path=PATH, body=body,
                             receiver_ss58=receiver)
    headers["Content-Type"] = "application/json"
    return body, headers


def verify_response(
    *, body: bytes, headers: Any, status_code: int, request_body: bytes,
    request_headers: Any, receiver: str, expected_responder: str, store: SharedReplayStore,
) -> dict:
    if status_code != 200:
        raise BoundaryError("REMOTE_REJECTED")
    if len(body) > 262_144:
        raise BoundaryError("RESPONSE_TOO_LARGE")
    if store.receiver != receiver or store.domain != "response":
        raise BoundaryError("RESPONSE_STORE_MISMATCH")
    caller = verify_bytes(headers, body, method="RESPONSE", path=PATH,
                          config=TransportConfig(receiver), store=store)
    if caller.hotkey_ss58 != expected_responder:
        raise BoundaryError("RESPONDER_IDENTITY_MISMATCH")
    try:
        receipt, request = parse_canonical(body), parse_canonical(request_body)
        if set(receipt) != {"schema_version", "http_status", "challenge_id", "request_sha256",
                           "request_nonce_ns", "responder", "receiver", "differential"}:
            raise ValueError("invalid receipt")
        expected = {
            "schema_version": VERSION, "http_status": 200,
            "challenge_id": request["challenge_id"],
            "request_sha256": hashlib.sha256(request_body).hexdigest(),
            "request_nonce_ns": str(request_headers[http_auth.HEADER_NONCE]),
            "responder": expected_responder, "receiver": receiver,
        }
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise ValueError("receipt binding")
        if receipt["differential"].get("qid") != request["challenge_id"]:
            raise ValueError("challenge binding")
        if time.time_ns() // 1_000_000 >= request["deadline_ms"]:
            raise BoundaryError("RESPONSE_LATE")
    except BoundaryError:
        raise
    except Exception:
        raise BoundaryError("RESPONSE_BINDING_FAILED") from None
    return receipt["differential"]


async def exchange(
    *, endpoint: str, capsule: dict, signer: Any, receiver: str,
    store: SharedReplayStore, timeout_ms: int = 10_000,
    client: httpx.AsyncClient | None = None,
) -> dict:
    url = urlsplit(endpoint)
    if url.path not in {"", "/"} or url.query or url.fragment or url.username or url.password:
        raise ValueError("endpoint must be an origin without credentials")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {
        "127.0.0.1", "::1", "localhost",
    }):
        raise ValueError("remote exchange requires HTTPS")
    sender = resolve_signer(signer, role="hotkey").ss58_address
    body, headers = prepare_request(capsule, signer, receiver, timeout_ms=timeout_ms)
    owned = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False)
    try:
        async with asyncio.timeout(timeout_ms / 1000), client.stream(
            "POST", endpoint.rstrip("/") + PATH, content=body,
            headers=headers, timeout=timeout_ms / 1000,
        ) as response:
            chunks, size = [], 0
            async for chunk in response.aiter_raw():
                size += len(chunk)
                if size > 262_144:
                    raise BoundaryError("RESPONSE_TOO_LARGE")
                chunks.append(chunk)
            if response.headers.get("content-type") != "application/json":
                raise BoundaryError("RESPONSE_MEDIA_TYPE")
            names = [name.lower() for name, _ in response.headers.raw]
            if len(names) != len(set(names)):
                raise BoundaryError("DUPLICATE_RESPONSE_HEADER")
            return await anyio.to_thread.run_sync(partial(verify_response,
                body=b"".join(chunks), headers=response.headers, status_code=response.status_code,
                request_body=body, request_headers=headers, receiver=sender,
                expected_responder=receiver, store=store,
            ))
    finally:
        if owned:
            await client.aclose()
