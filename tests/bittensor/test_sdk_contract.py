from __future__ import annotations

import bittensor as bt
import pytest


def test_pinned_sdk_surface_is_exact() -> None:
    assert bt.__version__ == "11.1.0"
    assert bt.http_auth.PROTOCOL == "btauth/1"
    assert bt.SetWeights.__module__ == "bittensor.intents.weights"
    assert bt.Policy.__module__ == "bittensor.intents.plan"
    assert bt.Plan.__module__ == "bittensor.intents.plan"
    assert bt.Policy().allow_raw_calls is False


def test_btauth_binds_sender_receiver_method_path_body_and_nonce() -> None:
    sender = bt.sp_core.Keypair.create_from_uri("//Alice")
    receiver = bt.sp_core.Keypair.create_from_uri("//Bob")
    body = b'{"challenge_id":"q-sdk-contract"}'
    path = "/v1/assurance?round=1"
    nonce_ns = 1_800_000_000_000_000_000
    headers = bt.http_auth.sign(
        sender,
        method="POST",
        path=path,
        body=body,
        receiver_ss58=receiver.ss58_address,
        nonce_ns=nonce_ns,
    )
    store = bt.http_auth.InMemoryNonceStore(retention=60)

    caller = bt.http_auth.verify(
        headers,
        body,
        method="POST",
        path=path,
        self_hotkey_ss58=receiver.ss58_address,
        nonce_store=store,
        now_ns=nonce_ns,
    )
    assert caller.hotkey_ss58 == sender.ss58_address

    with pytest.raises(bt.http_auth.ReplayedRequest):
        bt.http_auth.verify(
            headers,
            body,
            method="POST",
            path=path,
            self_hotkey_ss58=receiver.ss58_address,
            nonce_store=store,
            now_ns=nonce_ns,
        )

    rejection_cases = (
        (
            {"self_hotkey_ss58": sender.ss58_address},
            bt.http_auth.WrongReceiver,
        ),
        ({"body": body + b" "}, bt.http_auth.BadSignature),
        ({"method": "PUT"}, bt.http_auth.BadSignature),
        ({"path": "/v1/assurance?round=2"}, bt.http_auth.BadSignature),
    )
    for overrides, expected_error in rejection_cases:
        arguments = {
            "headers": headers,
            "body": body,
            "method": "POST",
            "path": path,
            "self_hotkey_ss58": receiver.ss58_address,
            "nonce_store": bt.http_auth.InMemoryNonceStore(retention=60),
            "now_ns": nonce_ns,
        }
        arguments.update(overrides)
        with pytest.raises(expected_error):
            bt.http_auth.verify(**arguments)


def test_set_weights_intent_is_constructible_without_chain_access() -> None:
    intent = bt.SetWeights(
        netuid=87,
        uids=[1, 2],
        weights=[0.75, 0.25],
        mechid=0,
        version_key=0,
    )

    assert intent.netuid == 87
    assert intent.uids == [1, 2]
    assert intent.weights == [0.75, 0.25]
    assert intent.mechid == 0
    assert intent.version_key == 0
