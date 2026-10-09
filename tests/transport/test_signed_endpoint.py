from __future__ import annotations

import asyncio
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from bittensor import http_auth
from transport_support import throwaway_key
from valkey.exceptions import ConnectionError as ValkeyConnectionError
from valkey.exceptions import NoPermissionError, ResponseError

from sn87_provenonce.canonical import canonical_bytes
from sn87_provenonce.pilot.client import prepare_request, verify_response
from sn87_provenonce.pilot.server import create_app
from sn87_provenonce.pilot.transport import (
    PATH,
    VERSION,
    BoundaryError,
    SharedReplayStore,
    TransportConfig,
    verify_bytes,
)

pytest_plugins = ["transport_fixtures"]


def store(redis, receiver, domain="request", **kwargs):
    result = SharedReplayStore(redis, receiver=receiver, domain=domain, **kwargs)
    redis.set(result.prefix + ":generation", redis.info("server")["run_id"] + ":0")
    return result


def capsule():
    return {"qid": "q-transport-case", "payload": "exact bytes"}


def handler(value):
    return {"qid": value["qid"], "state": "NO_MATERIAL_DEVIATION", "rationale": "Test boundary"}


def signed(keys, *, body=None, nonce=None, method="POST", path=PATH, receiver=None):
    sender, server = keys
    body = body or canonical_bytes({
        "schema_version": VERSION, "challenge_id": capsule()["qid"],
        "deadline_ms": time.time_ns() // 1_000_000 + 10_000, "capsule": capsule(),
    })
    headers = http_auth.sign(sender, method=method, path=path, body=body,
                             receiver_ss58=receiver or server.ss58_address, nonce_ns=nonce)
    headers["Content-Type"] = "application/json"
    return body, headers


def post(app, body, headers, path=PATH):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://127.0.0.1") as client:
            return await client.post(path, content=body, headers=headers)
    return asyncio.run(run())


def test_exact_request_and_signed_response_identity_binding(redis, keys):
    sender, server = keys
    app = create_app(signer=server, store=store(redis, server.ss58_address), handle=handler)
    body, headers = prepare_request(capsule(), sender, server.ss58_address)
    response = post(app, body, headers)
    assert response.status_code == 200
    diff = verify_response(
        body=response.content, headers=response.headers, status_code=200,
        request_body=body, request_headers=headers, receiver=sender.ss58_address,
        expected_responder=server.ss58_address, store=store(redis, sender.ss58_address, "response"),
    )
    assert diff == handler(capsule())
    assert post(app, body, headers).json() == {"error": "REPLAYED_REQUEST"}


@pytest.mark.parametrize("mutation", ["body", "receiver", "method", "path", "stale", "future"])
def test_exact_byte_receiver_method_route_freshness_binding(redis, keys, mutation):
    sender, server = keys
    app = create_app(signer=server, store=store(redis, server.ss58_address), handle=handler)
    kw = {}
    if mutation == "receiver":
        kw["receiver"] = sender.ss58_address
    elif mutation in {"method", "path"}:
        kw[mutation] = "PUT" if mutation == "method" else "/different"
    elif mutation == "stale":
        kw["nonce"] = time.time_ns() - 11_000_000_000
    elif mutation == "future":
        kw["nonce"] = time.time_ns() + 3_000_000_000
    body, headers = signed(keys, **kw)
    if mutation == "body":
        body += b" "
    result = post(app, body, headers)
    assert result.status_code == 401
    assert result.json() == {"error": "AUTHENTICATION_FAILED"}


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{', b'\xff', b'{"x":NaN}'])
def test_authenticated_bad_payload_rejected_before_handler(redis, keys, body):
    called = []
    app = create_app(signer=keys[1], store=store(redis, keys[1].ss58_address),
                     handle=lambda x: called.append(x))
    raw, headers = signed(keys, body=body)
    assert post(app, raw, headers).status_code == 422
    assert called == []


def test_unsupported_oversize_duplicate_headers_query_truncation(redis, keys):
    app = create_app(signer=keys[1], store=store(redis, keys[1].ss58_address), handle=handler)
    raw, headers = signed(keys)
    assert post(app, raw, {**headers, "Content-Type": "text/plain"}).status_code == 415
    assert post(app, raw, {**headers, "Content-Length": "999999"}).status_code == 413
    assert post(app, raw, {**headers, "Content-Length": "1"}).json()["error"] == "TRUNCATED_BODY"
    assert post(app, raw, headers, PATH + "?unexpected=1").status_code == 404
    duplicates = list(headers.items()) + [("X-Bittensor-Hotkey", keys[0].ss58_address)]
    assert post(app, raw, duplicates).json()["error"] == "DUPLICATE_HEADER"


def test_atomic_race_and_worker_restart_share_replay(redis, keys):
    sender, server = keys
    config = TransportConfig(server.ss58_address)
    body, headers = signed(keys)
    def attempt(_):
        adapter = store(redis, server.ss58_address)
        try:
            verify_bytes(headers, body, method="POST", path=PATH, config=config, store=adapter)
            return "accepted"
        except BoundaryError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert results.count("accepted") == 1
    assert results.count("REPLAYED_REQUEST") == 15
    # A fresh application object represents an independently started worker.
    app = create_app(signer=server, store=store(redis, server.ss58_address), handle=handler)
    assert post(app, body, headers).json()["error"] == "REPLAYED_REQUEST"


def test_store_data_loss_quarantines_for_full_window(redis, keys):
    receiver = keys[1].ss58_address + "-short-window"
    adapter = store(redis, receiver, retention=0.2, max_age=0.1, allowed_skew=0.1)
    assert adapter.check_and_store(keys[0].ss58_address, 42)
    redis.delete(adapter.prefix + ":generation")
    with pytest.raises(BoundaryError, match="REPLAY_STORE_WARMING"):
        adapter.check_and_store(keys[0].ss58_address, 42)
    time.sleep(0.21)
    assert adapter.ready()


def test_store_run_id_change_quarantines_even_with_persistent_generation(redis, keys):
    adapter = store(redis, keys[1].ss58_address + "-new-generation")
    redis.set(adapter.prefix + ":generation", "previous-process:0")
    with pytest.raises(BoundaryError, match="REPLAY_STORE_WARMING"):
        adapter.ready()


@pytest.mark.parametrize("failure", [TimeoutError(), ConnectionError(), RuntimeError()])
def test_store_unavailable_or_ambiguous_fails_closed(failure):
    def bad(*args, **kwargs):
        raise failure
    adapter = SharedReplayStore(SimpleNamespace(info=bad), receiver="test", domain="request")
    with pytest.raises(BoundaryError, match="REPLAY_STORE_UNAVAILABLE"):
        adapter.check_and_store("sender", 1)


def test_ambiguous_set_fails_closed():
    adapter = SharedReplayStore(SimpleNamespace(info=lambda _: {"run_id": "x"},
                                                config_get=lambda _: NOEVICTION,
                                                eval=lambda *args: None),
                                receiver="test", domain="request")
    with pytest.raises(BoundaryError, match="REPLAY_STORE_UNAVAILABLE"):
        adapter.check_and_store("sender", 1)


NOEVICTION = {"maxmemory-policy": "noeviction"}


def fake_store(config_get):
    calls = []

    def evaluate(*args):
        calls.append(args)
        return 1

    client = SimpleNamespace(info=lambda _: {"run_id": "x"}, config_get=config_get,
                             eval=evaluate)
    return SharedReplayStore(client, receiver="test", domain="request"), calls


def test_noeviction_policy_admits():
    adapter, calls = fake_store(lambda _: NOEVICTION)
    assert adapter.check_and_store("sender", 1) is True
    assert adapter.ready() is True
    assert len(calls) == 2


@pytest.mark.parametrize("policy", [
    "allkeys-lru", "volatile-lru", "allkeys-lfu", "volatile-lfu", "allkeys-random",
    "volatile-random", "volatile-ttl", "",
])
def test_evicting_policy_fails_closed_before_admission(policy):
    adapter, calls = fake_store(lambda _: {"maxmemory-policy": policy})
    for probe in (lambda: adapter.check_and_store("sender", 1), adapter.ready):
        with pytest.raises(BoundaryError, match="REPLAY_STORE_EVICTION_POLICY_UNSAFE"):
            probe()
    assert calls == []


@pytest.mark.parametrize("reply", [{}, None, [], {"other": "noeviction"}])
def test_unreadable_policy_fails_closed(reply):
    adapter, calls = fake_store(lambda _: reply)
    with pytest.raises(BoundaryError, match="REPLAY_STORE_EVICTION_POLICY_UNVERIFIABLE"):
        adapter.ready()
    assert calls == []


@pytest.mark.parametrize("error", [
    ResponseError("ERR unknown command 'CONFIG'"),
    NoPermissionError("NOPERM this user has no permissions to run the 'config' command"),
])
def test_config_not_permitted_fails_closed_with_specific_reason(error):
    def denied(_):
        raise error
    adapter, calls = fake_store(denied)
    with pytest.raises(BoundaryError, match="REPLAY_STORE_EVICTION_POLICY_UNVERIFIABLE"):
        adapter.check_and_store("sender", 1)
    assert calls == []


def test_config_connection_failure_is_unavailable():
    def dropped(_):
        raise ValkeyConnectionError("lost")
    adapter, calls = fake_store(dropped)
    with pytest.raises(BoundaryError, match="REPLAY_STORE_UNAVAILABLE"):
        adapter.ready()
    assert calls == []


def test_real_store_policy_change_fails_closed(redis, keys):
    adapter = store(redis, keys[1].ss58_address + "-eviction-policy")
    assert adapter.ready() is True
    redis.config_set("maxmemory-policy", "volatile-ttl")
    try:
        with pytest.raises(BoundaryError, match="REPLAY_STORE_EVICTION_POLICY_UNSAFE"):
            adapter.ready()
    finally:
        redis.config_set("maxmemory-policy", "noeviction")
    assert adapter.ready() is True


def test_retention_and_local_memory_rejected(redis, keys):
    with pytest.raises(ValueError, match="retention"):
        SharedReplayStore(redis, receiver="test", domain="request", retention=11)
    with pytest.raises((ValueError, AttributeError)):
        create_app(signer=keys[1], store=http_auth.InMemoryNonceStore(), handle=handler)


@pytest.mark.parametrize("mutation", ["body", "identity", "challenge", "requesthash", "nonce"])
def test_response_forgery_or_cross_request_rejected(redis, keys, mutation):
    sender, server = keys
    body, headers = prepare_request(capsule(), sender, server.ss58_address)
    receipt = {"schema_version": VERSION, "http_status": 200,
               "challenge_id": capsule()["qid"], "request_sha256": hashlib.sha256(body).hexdigest(),
               "request_nonce_ns": headers[http_auth.HEADER_NONCE],
               "responder": server.ss58_address, "receiver": sender.ss58_address,
               "differential": handler(capsule())}
    signer = server
    if mutation == "identity":
        signer = throwaway_key()
    elif mutation == "challenge":
        receipt["challenge_id"] = "unrelated"
    elif mutation == "requesthash":
        receipt["request_sha256"] = "0" * 64
    elif mutation == "nonce":
        receipt["request_nonce_ns"] = "0"
    response_body = canonical_bytes(receipt)
    response_headers = http_auth.sign(signer, method="RESPONSE", path=PATH,
                                      body=response_body, receiver_ss58=sender.ss58_address)
    if mutation == "body":
        response_body += b" "
    with pytest.raises(BoundaryError):
        verify_response(body=response_body, headers=response_headers, status_code=200,
                        request_body=body, request_headers=headers, receiver=sender.ss58_address,
                        expected_responder=server.ss58_address,
                        store=store(redis, sender.ss58_address, "response"))


def test_expired_deadline_and_rate_limit(redis, keys):
    sender, server = keys
    adapter = store(redis, server.ss58_address + "-rate", per_minute=1)
    assert adapter.check_and_store(sender.ss58_address, 1)
    with pytest.raises(BoundaryError, match="RATE_LIMITED"):
        adapter.check_and_store(sender.ss58_address, 2)
    app = create_app(signer=server, store=store(redis, server.ss58_address), handle=handler)
    raw, _ = signed(keys)
    envelope = json.loads(raw)
    envelope["deadline_ms"] = time.time_ns() // 1_000_000 - 1
    raw, headers = signed(keys, body=canonical_bytes(envelope))
    assert post(app, raw, headers).json()["error"] == "DEADLINE_REJECTED"


def test_handler_timeout_keeps_real_worker_admission(redis, keys):
    import threading
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow(value):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.3)
        with lock:
            active -= 1
        return handler(value)

    app = create_app(signer=keys[1], store=store(redis, keys[1].ss58_address), handle=slow,
                     config=TransportConfig(keys[1].ss58_address, max_inflight=1))

    async def probe():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://127.0.0.1") as client:
            statuses = []
            for _ in range(3):
                body, headers = prepare_request(capsule(), keys[0], keys[1].ss58_address,
                                                timeout_ms=40)
                response = await client.post(PATH, content=body, headers=headers)
                statuses.append(response.status_code)
            await asyncio.sleep(0.35)
            return statuses
    assert asyncio.run(probe()) == [504, 429, 429]
    assert peak == 1
    assert active == 0


# --- verify_bytes, direct -------------------------------------------------------------------


def test_verify_bytes_accepts_once_then_names_the_replay(redis, keys):
    sender, server = keys
    adapter = store(redis, server.ss58_address)
    config = TransportConfig(server.ss58_address)
    body, headers = signed(keys)
    caller = verify_bytes(headers, body, method="POST", path=PATH, config=config, store=adapter)
    assert caller.hotkey_ss58 == sender.ss58_address
    with pytest.raises(BoundaryError, match="REPLAYED_REQUEST"):
        verify_bytes(headers, body, method="POST", path=PATH, config=config, store=adapter)


def test_verify_bytes_rejects_a_forged_or_foreign_signature(redis, keys):
    sender, server = keys
    adapter = store(redis, server.ss58_address)
    config = TransportConfig(server.ss58_address)
    body, headers = signed(keys)
    flipped = headers[http_auth.HEADER_SIGNATURE]
    flipped = flipped[:-1] + ("0" if flipped[-1] != "0" else "1")
    for bad in (
        {**headers, http_auth.HEADER_SIGNATURE: flipped},
        # signed by another key while claiming the sender's hotkey
        {**signed((throwaway_key(), server))[1], http_auth.HEADER_HOTKEY: sender.ss58_address},
    ):
        with pytest.raises(BoundaryError, match="AUTHENTICATION_FAILED"):
            verify_bytes(bad, body, method="POST", path=PATH, config=config, store=adapter)
    # the rejected attempts did not consume the nonce: the genuine request still passes
    assert verify_bytes(headers, body, method="POST", path=PATH, config=config,
                        store=adapter).hotkey_ss58 == sender.ss58_address


def test_verify_bytes_rejects_another_receiver_hotkey(redis, keys):
    sender, server = keys
    other = throwaway_key()
    body, headers = signed(keys, receiver=other.ss58_address)
    with pytest.raises(BoundaryError, match="AUTHENTICATION_FAILED"):
        verify_bytes(headers, body, method="POST", path=PATH,
                     config=TransportConfig(server.ss58_address),
                     store=store(redis, server.ss58_address))


# --- create_app: bad signature, wrong hotkey, size, identity binding --------------------------


def test_app_rejects_bad_signature_and_wrong_hotkey_before_the_handler(redis, keys):
    sender, server = keys
    called = []
    app = create_app(signer=server, store=store(redis, server.ss58_address),
                     handle=lambda c: called.append(c) or handler(c))
    body, headers = signed(keys)
    sig = headers[http_auth.HEADER_SIGNATURE]
    forged = {**headers, http_auth.HEADER_SIGNATURE: sig[:-1] + ("0" if sig[-1] != "0" else "1")}
    assert post(app, body, forged).json() == {"error": "AUTHENTICATION_FAILED"}
    # a request meant for a different miner hotkey (the transport binds the receiver hotkey)
    wrong_body, wrong_headers = signed(keys, receiver=throwaway_key().ss58_address)
    response = post(app, wrong_body, wrong_headers)
    assert (response.status_code, response.json()) == (401, {"error": "AUTHENTICATION_FAILED"})
    assert called == []


def test_app_refuses_a_store_or_config_for_another_hotkey(redis, keys):
    sender, server = keys
    with pytest.raises(ValueError, match="identity"):
        create_app(signer=server, store=store(redis, sender.ss58_address), handle=handler)
    with pytest.raises(ValueError, match="identity"):
        create_app(signer=server, store=store(redis, server.ss58_address), handle=handler,
                   config=TransportConfig(sender.ss58_address))
    with pytest.raises(ValueError, match="configuration"):
        create_app(signer=server, store=store(redis, server.ss58_address, "response"),
                   handle=handler)


def test_app_rejects_an_oversize_body_with_and_without_a_declared_length(redis, keys):
    sender, server = keys
    config = TransportConfig(server.ss58_address, max_body_bytes=256)
    app = create_app(signer=server, store=store(redis, server.ss58_address), handle=handler,
                     config=config)
    big = {"qid": "q-transport-case", "payload": "x" * 400}
    body = canonical_bytes({
        "schema_version": VERSION, "challenge_id": big["qid"],
        "deadline_ms": time.time_ns() // 1_000_000 + 10_000, "capsule": big,
    })
    assert len(body) > config.max_body_bytes
    raw, headers = signed(keys, body=body)
    declared = post(app, raw, headers)
    assert (declared.status_code, declared.json()) == (413, {"error": "BODY_TOO_LARGE"})

    async def chunks():
        for start in range(0, len(raw), 100):
            yield raw[start:start + 100]

    async def undeclared():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://127.0.0.1") as client:
            return await client.post(PATH, content=chunks(), headers=headers)

    response = asyncio.run(undeclared())
    assert (response.status_code, response.json()) == (413, {"error": "BODY_TOO_LARGE"})


def test_ready_reports_the_replay_store(redis, keys):
    def get(app, path):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://127.0.0.1") as client:
                return await client.get(path)
        return asyncio.run(run())

    ready = create_app(signer=keys[1], store=store(redis, keys[1].ss58_address), handle=handler)
    response = get(ready, "/ready")
    assert (response.status_code, response.json()) == (200, {"ready": True})
    # a store this process has not yet seen is quarantined for a full freshness window
    warming = create_app(
        signer=keys[0], handle=handler,
        store=SharedReplayStore(redis, receiver=keys[0].ss58_address, domain="request"))
    response = get(warming, "/ready")
    assert (response.status_code, response.json()) == (503, {"error": "REPLAY_STORE_WARMING"})
