"""Cross-branch (trusted sender and sender allowlist, contest protocol 0.2): the shadow
service signs requests that carry the window open record (``window_commitments``). A trusted
sender is accepted with it, a stranger is refused before the method runs whether or not the
record is present, a malformed record from a trusted sender is an envelope error, not a
permission one, and a permitted validator still works. Fakes only: no network, no chain."""

from __future__ import annotations

import asyncio

import httpx
from transport_support import throwaway_key

from sn87_provenonce.pilot import sender_policy as sp
from sn87_provenonce.pilot.client import prepare_request
from sn87_provenonce.pilot.server import create_app
from sn87_provenonce.pilot.transport import PATH, SharedReplayStore

NETUID = 582
RECORD = {"generator": "sn87-contest-generator/0.2", "window_id": "cw-0001",
          "cases_commitment": "sha256:" + "1" * 64, "truth_commitment": "sha256:" + "2" * 64}


class Provider:
    def __init__(self, *permitted):
        self.permitted = frozenset(permitted)

    def fetch(self, netuid):
        return sp.PermitSnapshot(netuid=NETUID, permitted=self.permitted, block=1)


class Store(SharedReplayStore):
    def __init__(self, receiver):
        super().__init__(None, receiver=receiver, domain="request")
        self.seen = set()

    def check_and_store(self, hotkey, nonce):
        if (hotkey, nonce) in self.seen:
            return False
        self.seen.add((hotkey, nonce))
        return True

    def ready(self):
        return True


def endpoint(permitted, trusted):
    policy = sp.SenderPolicy(
        Provider(*permitted),
        sp.SenderPolicyConfig(netuid=NETUID, trusted_senders=tuple(trusted), burst=1000,
                              rate_per_second=1000.0, sender_burst=1000,
                              sender_rate_per_second=1000.0))
    policy.load()
    server, handled = throwaway_key(), []

    def handle(value):
        handled.append(value["qid"])
        return {"qid": value["qid"], "state": "NO_MATERIAL_DEVIATION"}

    app = create_app(signer=server, store=Store(server.ss58_address), handle=handle,
                     sender_policy=policy)

    def send(sender, record):
        body, headers = prepare_request({"qid": "q-trusted", "payload": "x"}, sender,
                                        server.ss58_address, window_commitments=record)

        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://127.0.0.1") as client:
                return await client.post(PATH, content=body, headers=headers)

        return asyncio.run(go())

    return send, handled


def test_the_trusted_shadow_signer_is_answered_with_the_open_record():
    shadow, validator, stranger = throwaway_key(), throwaway_key(), throwaway_key()
    send, handled = endpoint([validator.ss58_address], [shadow.ss58_address])
    assert send(shadow, RECORD).status_code == 200      # trusted, no permit, 0.2 envelope
    assert send(shadow, None).status_code == 200        # and the 0.1 shape
    assert send(validator, RECORD).status_code == 200   # a permitted validator is unaffected
    assert len(handled) == 3
    for record in (RECORD, None):
        refused = send(stranger, record)
        assert refused.status_code == 403 and refused.json() == {"error": "SENDER_NOT_PERMITTED"}
    assert len(handled) == 3                             # the method never ran for a stranger


def test_a_malformed_record_from_a_trusted_sender_is_an_envelope_error():
    shadow = throwaway_key()
    send, handled = endpoint([], [shadow.ss58_address])
    response = send(shadow, {**RECORD, "extra": "x"})
    assert response.status_code == 422 and response.json() == {"error": "INVALID_ENVELOPE"}
    assert handled == []
