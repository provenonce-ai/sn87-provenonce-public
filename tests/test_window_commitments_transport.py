"""The contest window's open record travels in every request (contest protocol 0.2).

Local only: the signed server is the ASGI app run in-process, the replay store is in memory and the
keys come from public development URIs. NO NETWORK, NO CHAIN."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from bittensor import sp_core

from sn87_provenonce.canonical import parse_canonical
from sn87_provenonce.pilot.client import exchange, prepare_request
from sn87_provenonce.pilot.sender_policy import AllowAnySender
from sn87_provenonce.pilot.server import _window_commitments_ok, create_app
from sn87_provenonce.pilot.transport import SharedReplayStore

SENDER = sp_core.Keypair.create_from_uri("//Alice")
SERVER = sp_core.Keypair.create_from_uri("//Bob")
RECORD = {"generator": "sn87-contest-generator/0.2", "window_id": "cw-0001",
          "cases_commitment": "sha256:" + "1" * 64, "truth_commitment": "sha256:" + "2" * 64}


class MemoryStore(SharedReplayStore):
    def __init__(self, receiver, domain):
        super().__init__(None, receiver=receiver, domain=domain)
        self.seen = set()

    def check_and_store(self, hotkey_ss58, nonce_ns):
        if (hotkey_ss58, nonce_ns) in self.seen:
            return False
        self.seen.add((hotkey_ss58, nonce_ns))
        return True

    def ready(self):
        return True


def capsule():
    return {"qid": "q-window-record", "payload": "x"}


def app(seen):
    def handle(value):
        seen.append(value)
        return {"qid": value["qid"], "state": "NO_MATERIAL_DEVIATION", "rationale": "ok"}

    return create_app(signer=SERVER, store=MemoryStore(SERVER.ss58_address, "request"),
                      handle=handle, sender_policy=AllowAnySender())


def test_the_request_carries_the_record_inside_the_signed_body():
    body, _ = prepare_request(capsule(), SENDER, SERVER.ss58_address, window_commitments=RECORD)
    assert parse_canonical(body)["window_commitments"] == RECORD
    plain, _ = prepare_request(capsule(), SENDER, SERVER.ss58_address)
    assert "window_commitments" not in parse_canonical(plain)


def test_a_miner_server_accepts_the_record_and_an_old_request(monkeypatch):
    from sn87_provenonce.pilot.transport import PATH

    seen = []
    application = app(seen)

    def send(record):
        body, headers = prepare_request(capsule(), SENDER, SERVER.ss58_address,
                                        window_commitments=record)

        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                                         base_url="http://127.0.0.1") as client:
                return await client.post(PATH, content=body, headers=headers)

        return asyncio.run(go())

    assert send(RECORD).status_code == 200
    assert send(None).status_code == 200  # a request without it is the 0.1 shape and still works
    assert len(seen) == 2
    for bad in ({**RECORD, "extra": "x"}, {**RECORD, "truth_commitment": "sha256:zz"},
                {**RECORD, "window_id": "../x"}, {"window_id": "cw-0001"}, "text", 5):
        response = send(bad)
        assert response.status_code == 422 and response.json() == {"error": "INVALID_ENVELOPE"}
    assert len(seen) == 2


def test_the_shape_check_is_strict():
    assert _window_commitments_ok(RECORD)
    for bad in (None, [], {}, {**RECORD, "generator": "other"},
                {**RECORD, "cases_commitment": "sha256:" + "A" * 64},
                {**RECORD, "truth_commitment": 7}):
        assert not _window_commitments_ok(bad)


def test_exchange_sends_the_record_through_the_client():
    sent = {}

    async def handler(request):
        sent["body"] = request.content
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = MemoryStore(SENDER.ss58_address, "response")

    async def go():
        with pytest.raises(Exception):  # noqa: B017, PT011 - the mock answers 500 on purpose
            await exchange(endpoint="http://127.0.0.1:9", capsule=capsule(), signer=SENDER,
                           receiver=SERVER.ss58_address, store=store, client=client,
                           window_commitments=RECORD)
        await client.aclose()

    asyncio.run(go())
    assert parse_canonical(sent["body"])["window_commitments"] == RECORD


def test_the_generator_field_is_pinned_to_the_one_version_that_sends_it():
    for generator in ("sn87-contest-generator/0.1", "sn87-contest-generator/0.22",
                      "sn87-contest-generator/0.2 ", "sn87-contest-generator/0x2",
                      "sn87-contest-generator/0.2\n"):
        assert not _window_commitments_ok({**RECORD, "generator": generator})


def reject_with(status):
    from sn87_provenonce.pilot.client import verify_response
    from sn87_provenonce.pilot.transport import BoundaryError

    with pytest.raises(BoundaryError) as error:
        verify_response(body=b"{}", headers={}, status_code=status, request_body=b"{}",
                        request_headers={}, receiver="r", expected_responder="e", store=None)
    return str(error.value)


def test_a_rejected_request_says_which_status_and_a_422_is_the_documented_envelope_code():
    assert reject_with(403) == "REMOTE_REJECTED_403"
    assert reject_with(500) == "REMOTE_REJECTED_500"
    assert reject_with(429) == "REMOTE_REJECTED_429"
    assert reject_with(422) == "MINER_REJECTED_ENVELOPE"


def test_the_rejection_code_is_built_from_an_integer_status_only():
    from sn87_provenonce.pilot.client import RemoteRejected

    assert str(RemoteRejected(403)) == "REMOTE_REJECTED_403"
    for odd in (99, 600, "403", None, True, 4.0):
        assert str(RemoteRejected(odd)) == "REMOTE_REJECTED"
