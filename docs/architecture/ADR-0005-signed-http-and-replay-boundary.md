# ADR-0005: Use a minimal ASGI boundary and shared atomic replay store

**Status:** Implemented

**Date:** 2026-09-03 (decision); implemented 2026-09-27

**Deciders:** Will O'Brien, Provenonce Founder & CEO; SN87 protocol maintainer

**Implementation:** commit `757def4e630a5bb07d683e6071767ca8515fa170` (merged 2026-09-27) added
`src/sn87_provenonce/pilot/transport.py` (SDK verification and the Valkey nonce store) and
`src/sn87_provenonce/pilot/server.py` (the ASGI app factory `create_app`). The signed transport
was exercised by the First Light run whose weight row was applied on public testnet netuid 582
at block 8,102,381. A later commit (`af4b7ec`, 2026-10-03) changed only the import of the
canonicalizer in `server.py`; the decision below is unchanged. The tests that prove the transport
(including the atomic race and fail-closed store cases) live in the private suite and are not in
this repository.

**Not done:** nothing in this repository launches `create_app` as a service. Its only callers are private
(a local smoke script and the private transport tests). A public, runnable launcher is separate work and is not claimed here.

## Context

The SN87 protocol specification requires authenticated validator-to-miner HTTP using the official
`bittensor.http_auth` `btauth/1` envelope. ADR-0004 pins the SDK and proves the envelope
offline, but it intentionally leaves the service framework and multi-process nonce store
unselected. Those choices affect exact-byte verification, replay safety, concurrency, and
future operating topology, so they must be settled before transport code is written.

The official Starlette request API exposes `await request.body()` as bytes. Its middleware
documentation also records a context-variable limitation in `BaseHTTPMiddleware` and advises
pure ASGI middleware when that limitation matters. Uvicorn provides worker, concurrency,
request-count, health-check, and graceful-shutdown controls. The official Redis command
contract provides atomic `SET key value NX PX milliseconds`. Valkey is a Linux Foundation
BSD-licensed key/value store, publishes official Python client support, and retains
compatibility with the Redis OSS protocol.

Sources reviewed:

- [Starlette request body API](https://github.com/Kludex/starlette/blob/main/docs/requests.md)
- [Starlette pure ASGI middleware guidance](https://github.com/Kludex/starlette/blob/main/docs/middleware.md)
- [Uvicorn deployment controls](https://github.com/encode/uvicorn/blob/master/docs/settings.md)
- Redis documentation: atomic SET options
- Valkey project and governance (valkey.io)

## Decision

Use Starlette as the minimal ASGI application layer and Uvicorn as its server. Do not add
FastAPI: SN87 already owns strict Pydantic protocol models, and transport must authenticate
the exact received bytes before any framework-driven JSON parsing or dependency injection.

The signed request boundary must:

1. reject unsupported method, path, media type, and oversized bodies before application
   parsing;
2. buffer no more than a configured hard byte limit;
3. pass the exact raw body, receiver hotkey, method, path, headers, and current time to the
   pinned `bittensor.http_auth.verify` implementation;
4. perform that synchronous verification operation, including nonce-store access, in a
   bounded worker thread rather than on the event loop;
5. parse the authenticated bytes once with SN87's strict JSON parser and Pydantic models;
6. expose only stable failure codes, never signatures, authorization headers, payloads,
   wallet material, or adapter exception text; and
7. use pure ASGI middleware or an explicit endpoint boundary, not `BaseHTTPMiddleware`.

Production-capable deployments must provide one shared, fail-closed nonce store across all
workers and hosts. The selected protocol is an atomic Valkey-compatible operation equivalent
to `SET <domain-separated-key> 1 NX PX <retention-ms>`. The key must be a SHA-256 digest over
the authentication domain, receiver, sender, and nonce; it must not include raw bodies or
signatures. Retention must be at least the complete accepted authentication window, including
clock skew. An unavailable or ambiguous store rejects the request. Readiness is false when
the shared store cannot prove atomic writes.

Valkey is the preferred open-source deployment. The adapter contract remains compatible with
the Redis wire protocol so an approved managed equivalent can be qualified later. The exact
Starlette, Uvicorn, client, and Valkey versions must be pinned and locked with the transport
implementation; no compatible-release ranges are permitted at that boundary.

The official SDK's in-memory nonce store remains acceptable only for single-process local
tests. It is prohibited for any multi-worker, multi-host, testnet, or production claim.

## Options considered

### Starlette plus Uvicorn: selected

It provides the smallest mature Python ASGI surface needed for byte-preserving request
handling while retaining explicit server resource controls.

### FastAPI

Rejected for this boundary. Its automatic parsing and API-description features are useful for
ordinary application APIs but add no needed capability before SN87's authentication gate.

### aiohttp or bare ASGI

Not selected. Both can preserve raw bytes, but aiohttp would introduce a second server model,
while bare ASGI would make SN87 own more request lifecycle and error-handling machinery.

### Process-local nonce memory

Rejected outside isolated tests because two workers could each accept the same signed nonce.

### PostgreSQL nonce table

Deferred, not prohibited. A unique key plus expiration can be correct, but it adds durable-row
cleanup and greater latency to a short-lived atomic admission decision. It remains a fallback
if the approved operating environment cannot support Valkey.

## Required implementation evidence

The transport implementation must include tests proving:

- byte-for-byte body binding, receiver binding, method binding, path binding, freshness, and
  replay rejection;
- malformed, duplicate-key, oversized, truncated, and unsupported-media requests fail before
  model handling;
- two application instances racing the same nonce produce exactly one acceptance;
- store timeout, disconnection, ambiguous write, and retention misconfiguration fail closed;
- application parsing sees exactly the bytes authenticated by the SDK;
- no sensitive authentication material or raw payload appears in responses or logs; and
- local in-memory mode cannot be configured as multi-worker or presented as a testnet deployment.

No endpoint, wallet, DNS name, port, TLS identity, testnet target, or chain operation is
authorized by this ADR.

## Consequences

- The irreversible framework and replay semantics are settled before implementation.
- SN87 keeps protocol parsing and authentication order explicit and auditable.
- Horizontal execution requires shared infrastructure and fails closed when it is unhealthy.
- The future transport dependency set stays optional and exact-versioned.
- This document is an architecture decision, not a service, deployment, or testnet result.
