"""Bounded Starlette endpoint. No chain mutation or implicit wallet loading."""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable
from typing import Any

import anyio
from bittensor import http_auth, resolve_signer
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from sn87_provenonce.canonical import canonical_bytes, parse_canonical

from .transport import (
    PATH,
    VERSION,
    BoundaryError,
    SharedReplayStore,
    TransportConfig,
    verify_bytes,
)


def _error(code: str, status: int) -> Response:
    return Response(canonical_bytes({"error": code}), status_code=status,
                    media_type="application/json", headers={"Cache-Control": "no-store"})


def create_app(
    *, signer: Any, store: SharedReplayStore, handle: Callable[[dict], dict],
    config: TransportConfig | None = None,
) -> Starlette:
    resolved = resolve_signer(signer, role="hotkey")
    config = config or TransportConfig(receiver_ss58=resolved.ss58_address)
    if config.receiver_ss58 != resolved.ss58_address or store.receiver != config.receiver_ss58:
        raise ValueError("server identity does not match replay domain")
    if store.domain != "request" or store.retention < config.max_age + config.allowed_skew:
        raise ValueError("server replay configuration mismatch")
    limiter = anyio.CapacityLimiter(config.max_inflight)
    slots = asyncio.Semaphore(config.max_inflight)

    async def threaded(fn: Callable, *args: Any) -> Any:
        return await anyio.to_thread.run_sync(fn, *args, limiter=limiter)

    async def ready(_: Request) -> Response:
        try:
            if not await threaded(store.ready):
                return _error("REPLAY_STORE_UNAVAILABLE", 503)
        except BoundaryError as exc:
            return _error(str(exc), 503)
        return Response(canonical_bytes({"ready": True}), media_type="application/json")

    async def assurance(request: Request) -> Response:
        raw_headers = request.scope["headers"]
        names = [k.lower() for k, _ in raw_headers]
        if len(names) != len(set(names)):
            return _error("DUPLICATE_HEADER", 400)
        if request.scope.get("raw_path", b"") != PATH.encode() or request.url.query:
            return _error("UNSUPPORTED_PATH", 404)
        if request.headers.get("content-type") != "application/json":
            return _error("UNSUPPORTED_MEDIA_TYPE", 415)
        if request.headers.get("content-encoding", "identity") != "identity":
            return _error("UNSUPPORTED_CONTENT_ENCODING", 415)
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isdecimal():
                return _error("INVALID_CONTENT_LENGTH", 400)
            if int(length) > config.max_body_bytes:
                return _error("BODY_TOO_LARGE", 413)
        try:
            await asyncio.wait_for(slots.acquire(), timeout=0.05)
        except TimeoutError:
            return _error("CAPACITY_LIMIT", 429)
        pending_work: set[asyncio.Task] = set()

        async def bounded_work(fn: Callable, *args: Any) -> Any:
            task = asyncio.create_task(threaded(fn, *args))
            pending_work.add(task)
            try:
                return await asyncio.shield(task)
            finally:
                if task.done():
                    pending_work.discard(task)

        try:
            async def read_body() -> bytes:
                parts, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > config.max_body_bytes:
                        raise BoundaryError("BODY_TOO_LARGE")
                    parts.append(chunk)
                return b"".join(parts)

            body = await asyncio.wait_for(read_body(), config.body_timeout_seconds)
            if length is not None and len(body) != int(length):
                return _error("TRUNCATED_BODY", 400)
            caller = await bounded_work(lambda: verify_bytes(
                request.headers, body, method="POST", path=PATH, config=config, store=store,
            ))
            envelope = parse_canonical(body)
            if not isinstance(envelope, dict) or set(envelope) != {
                "schema_version", "challenge_id", "deadline_ms", "capsule",
            }:
                return _error("INVALID_ENVELOPE", 422)
            capsule, deadline = envelope["capsule"], envelope["deadline_ms"]
            if envelope["schema_version"] != VERSION or type(deadline) is not int:
                return _error("INVALID_ENVELOPE", 422)
            if not isinstance(capsule, dict) or envelope["challenge_id"] != capsule.get("qid"):
                return _error("CHALLENGE_BINDING_FAILED", 422)
            remaining_ms = deadline - time.time_ns() // 1_000_000
            if remaining_ms <= 0 or remaining_ms > config.max_deadline_ms:
                return _error("DEADLINE_REJECTED", 408)
            result = await asyncio.wait_for(bounded_work(handle, capsule), remaining_ms / 1000)
            if time.time_ns() // 1_000_000 >= deadline:
                return _error("DEADLINE_EXCEEDED", 504)
            if not isinstance(result, dict) or result.get("qid") != envelope["challenge_id"]:
                return _error("HANDLER_BINDING_FAILED", 500)
            receipt = {
                "schema_version": VERSION, "http_status": 200,
                "challenge_id": envelope["challenge_id"],
                "request_sha256": hashlib.sha256(body).hexdigest(),
                "request_nonce_ns": str(caller.nonce_ns),
                "responder": config.receiver_ss58, "receiver": caller.hotkey_ss58,
                "differential": result,
            }
            response_bytes = canonical_bytes(receipt)
            headers = http_auth.sign(signer, method="RESPONSE", path=PATH,
                                     body=response_bytes, receiver_ss58=caller.hotkey_ss58)
            headers["Cache-Control"] = "no-store"
            return Response(response_bytes, headers=headers, media_type="application/json")
        except BoundaryError as exc:
            code = str(exc)
            status = 503 if code.startswith("REPLAY_STORE") else 401
            if code == "RATE_LIMITED":
                status = 429
            if code == "BODY_TOO_LARGE":
                status = 413
            return _error(code, status)
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            return _error("INVALID_PAYLOAD", 422)
        except ClientDisconnect:
            return _error("TRUNCATED_BODY", 400)
        except TimeoutError:
            return _error("DEADLINE_EXCEEDED", 504)
        except Exception:
            return _error("INTERNAL_FAILURE", 500)
        finally:
            # A timed-out synchronous handler continues running. Keep both its
            # shielded AnyIO limiter token and the request admission slot until
            # actual completion; replying 504 must not create extra capacity.
            outstanding = {task for task in pending_work if not task.done()}
            if not outstanding:
                slots.release()
            else:
                released = False

                def completed(task: asyncio.Task) -> None:
                    nonlocal released
                    if not task.cancelled():
                        task.exception()  # retrieve errors without exposing handler content
                    outstanding.discard(task)
                    if not outstanding and not released:
                        released = True
                        slots.release()

                for task in outstanding.copy():
                    task.add_done_callback(completed)

    return Starlette(debug=False, routes=[
        Route(PATH, assurance, methods=["POST"]), Route("/ready", ready, methods=["GET"]),
    ])
