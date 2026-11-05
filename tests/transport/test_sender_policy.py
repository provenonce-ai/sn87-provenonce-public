"""The miner's sender allowlist.

Fakes only: a fake snapshot provider, a fake clock, an in-memory replay store, a fake chain
client. No network, no chain, no Valkey, and every key is a fresh random throwaway."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx
import pytest
from transport_support import throwaway_key

from sn87_provenonce.miner_node import launcher
from sn87_provenonce.miner_node import transport_glue as glue
from sn87_provenonce.pilot import sender_policy as sp
from sn87_provenonce.pilot.client import prepare_request
from sn87_provenonce.pilot.server import create_app
from sn87_provenonce.pilot.transport import PATH, BoundaryError

NETUID = 582


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeProvider:
    """Stands in for the metagraph read. ``permitted`` is the list a refresh would see."""

    def __init__(self, *permitted, netuid=NETUID):
        self.permitted = set(permitted)
        self.netuid = netuid
        self.calls = 0
        self.fail = None

    def fetch(self, netuid):
        self.calls += 1
        if self.fail:
            raise self.fail
        return sp.PermitSnapshot(netuid=self.netuid, permitted=frozenset(self.permitted),
                                 block=1000 + self.calls)


def make_policy(*permitted, clock=None, load=True, **config):
    """A policy over a fake provider, already loaded (the miner loads it at start-up)."""
    clock = clock or FakeClock()
    provider = FakeProvider(*permitted)
    config.setdefault("burst", 1000)
    config.setdefault("rate_per_second", 1000.0)
    config.setdefault("sender_burst", 1000)
    config.setdefault("sender_rate_per_second", 1000.0)
    policy = sp.SenderPolicy(provider, sp.SenderPolicyConfig(netuid=NETUID, **config),
                             clock=clock)
    if load:
        policy.load()
    return policy, provider, clock


def code_of(policy, hotkey, settle=False):
    """The decision for one request; ``settle`` then waits for any background read."""
    try:
        policy.admit(hotkey)
        result = "ADMITTED"
    except BoundaryError as error:
        result = str(error)
    if settle:
        policy.wait_idle()
    return result


# ---------------------------------------------------------------------- the allowlist

def test_a_hotkey_with_validator_permit_is_accepted():
    policy, _, _ = make_policy("validator-1")
    assert code_of(policy, "validator-1") == "ADMITTED"


def test_a_hotkey_without_validator_permit_is_rejected_with_a_defined_code():
    policy, _, _ = make_policy("validator-1")
    assert code_of(policy, "some-miner") == "SENDER_NOT_PERMITTED"
    assert policy.rejected == 1


def test_before_the_first_snapshot_everyone_is_refused_and_the_read_starts_off_the_request():
    policy, provider, _ = make_policy("validator-1", load=False)
    assert code_of(policy, "validator-1", settle=True) == "SENDER_POLICY_UNAVAILABLE"
    assert code_of(policy, "validator-1") == "ADMITTED" and provider.calls == 1


def test_a_permit_revoked_on_chain_is_rejected_after_the_next_refresh_not_before():
    policy, provider, clock = make_policy("validator-1", refresh_seconds=600.0)
    provider.permitted.clear()                       # revoked on chain
    clock.advance(599)
    assert code_of(policy, "validator-1", settle=True) == "ADMITTED"   # snapshot still current
    clock.advance(2)
    assert code_of(policy, "validator-1", settle=True) == "ADMITTED"   # this call starts the read
    assert code_of(policy, "validator-1") == "SENDER_NOT_PERMITTED"    # the next sees it


def test_a_newly_granted_permit_is_honoured_after_the_next_refresh():
    policy, provider, clock = make_policy("validator-1", refresh_seconds=600.0)
    provider.permitted.add("validator-2")
    assert code_of(policy, "validator-2") == "SENDER_NOT_PERMITTED"
    clock.advance(601)
    code_of(policy, "validator-1", settle=True)
    assert code_of(policy, "validator-2") == "ADMITTED"


def test_the_snapshot_is_read_at_most_once_per_refresh_interval():
    policy, provider, clock = make_policy("validator-1", refresh_seconds=600.0)
    assert provider.calls == 1
    for _ in range(50):
        code_of(policy, "validator-1", settle=True)
        code_of(policy, "stranger", settle=True)
        clock.advance(10)                            # 500 s in all
    assert provider.calls == 1
    clock.advance(200)
    for _ in range(20):
        code_of(policy, "validator-1", settle=True)
    assert provider.calls == 2


def test_a_failed_refresh_keeps_the_snapshot_until_it_is_too_old_then_fails_closed():
    policy, provider, clock = make_policy("validator-1", refresh_seconds=600.0,
                                          retry_seconds=30.0)
    provider.fail = RuntimeError("chain down SECRETDETAIL")
    clock.advance(601)                               # due; refresh fails; snapshot kept
    assert code_of(policy, "validator-1", settle=True) == "ADMITTED"
    calls = provider.calls
    for _ in range(10):                              # not retried within retry_seconds
        code_of(policy, "validator-1", settle=True)
    assert provider.calls == calls
    clock.advance(700)                               # now 1301 s old: over 2 x the interval
    assert code_of(policy, "validator-1", settle=True) == "SENDER_POLICY_UNAVAILABLE"
    assert code_of(policy, "stranger") == "SENDER_POLICY_UNAVAILABLE"
    provider.fail = None                             # chain back: the next retry recovers
    clock.advance(31)
    code_of(policy, "validator-1", settle=True)
    assert code_of(policy, "validator-1") == "ADMITTED"


def test_with_no_snapshot_at_all_everyone_but_the_probe_key_is_refused():
    policy, provider, _ = make_policy("validator-1", probe_hotkey="probe", load=False)
    provider.fail = RuntimeError("down")
    assert code_of(policy, "validator-1", settle=True) == "SENDER_POLICY_UNAVAILABLE"
    assert code_of(policy, "probe") == "ADMITTED"


def test_start_up_fails_if_the_first_snapshot_cannot_be_read_and_names_no_detail():
    policy, provider, _ = make_policy("validator-1", load=False)
    provider.fail = RuntimeError("SECRETDETAIL")
    with pytest.raises(sp.SnapshotError) as raised:
        policy.load()
    assert str(raised.value) == "RuntimeError"


def test_a_snapshot_for_another_netuid_is_not_used():
    policy, provider, _ = make_policy("validator-1", load=False)
    provider.netuid = 1
    with pytest.raises(sp.SnapshotError, match="SENDER_SNAPSHOT_WRONG_NETUID"):
        policy.load()


def test_the_probe_hotkey_is_accepted_without_a_permit_and_nobody_else_gets_that():
    policy, _, _ = make_policy("validator-1", probe_hotkey="probe-key")
    assert code_of(policy, "probe-key") == "ADMITTED"
    assert code_of(policy, "other-key") == "SENDER_NOT_PERMITTED"


# ------------------------------------------------- a hung chain read never blocks requests

class BlockingProvider(FakeProvider):
    """Its read hangs until the test lets go."""

    def __init__(self, *permitted):
        super().__init__(*permitted)
        self.release = threading.Event()
        self.entered = threading.Event()
        self.hang = False

    def fetch(self, netuid):
        if self.hang:
            self.entered.set()
            self.release.wait(10)
        return super().fetch(netuid)


def blocking_policy(**config):
    clock = FakeClock()
    provider = BlockingProvider("validator-1")
    config.setdefault("refresh_seconds", 600.0)
    config.setdefault("fetch_timeout_seconds", 60.0)
    config.setdefault("sender_burst", 1000)
    config.setdefault("burst", 1000)
    policy = sp.SenderPolicy(provider, sp.SenderPolicyConfig(netuid=NETUID, **config),
                             clock=clock)
    policy.load()
    return policy, provider, clock


def test_a_hung_refresh_does_not_block_requests_and_the_stale_limit_still_applies():
    policy, provider, clock = blocking_policy()
    provider.hang = True
    clock.advance(601)
    started = time.monotonic()
    assert code_of(policy, "validator-1") == "ADMITTED"       # old snapshot, read started
    assert provider.entered.wait(5)
    for _ in range(20):                                        # the read is still hanging
        assert code_of(policy, "validator-1") == "ADMITTED"
        assert code_of(policy, "stranger") == "SENDER_NOT_PERMITTED"
    assert time.monotonic() - started < 3
    clock.advance(700)                                         # over twice the interval
    assert code_of(policy, "validator-1") == "SENDER_POLICY_UNAVAILABLE"
    provider.release.set()
    policy.wait_idle()


def test_a_hung_read_is_abandoned_after_its_timeout_and_a_new_one_recovers():
    policy, provider, clock = blocking_policy()
    provider.hang = True
    clock.advance(601)
    code_of(policy, "validator-1")
    assert provider.entered.wait(5)
    clock.advance(61)                                          # past fetch_timeout_seconds
    provider.hang = False                                      # the next read does not hang
    code_of(policy, "validator-1", settle=True)                # abandons the hung one
    assert provider.calls >= 2
    provider.release.set()


def test_start_up_gives_up_on_a_hung_first_read():
    clock = FakeClock()
    provider = BlockingProvider("validator-1")
    provider.hang = True
    policy = sp.SenderPolicy(provider, sp.SenderPolicyConfig(
        netuid=NETUID, refresh_seconds=60.0, fetch_timeout_seconds=0.2), clock=clock)
    with pytest.raises(sp.SnapshotError, match="SENDER_SNAPSHOT_TIMEOUT"):
        policy.load()
    provider.release.set()


# ---------------------------------------------------------------------- the rate limits

def test_the_global_rate_limit_trips_with_a_defined_code_and_refills():
    policy, _, clock = make_policy("v1", "v2", rate_per_second=2.0, burst=3)
    assert [code_of(policy, "v1"), code_of(policy, "v2"), code_of(policy, "v1")] == \
        ["ADMITTED"] * 3
    assert code_of(policy, "v2") == "GLOBAL_RATE_LIMITED"      # shared by all senders
    clock.advance(1.0)                                         # two tokens back
    assert [code_of(policy, "v1"), code_of(policy, "v1"), code_of(policy, "v1")] == \
        ["ADMITTED", "ADMITTED", "GLOBAL_RATE_LIMITED"]


def test_one_sender_cannot_use_up_the_allowance_of_the_others():
    policy, _, clock = make_policy("v1", "v2", probe_hotkey="probe", rate_per_second=100.0,
                                   burst=100, sender_rate_per_second=1.0, sender_burst=2)
    assert [code_of(policy, "v1") for _ in range(4)] == \
        ["ADMITTED", "ADMITTED", "SENDER_RATE_LIMITED", "SENDER_RATE_LIMITED"]
    assert code_of(policy, "v2") == "ADMITTED"                 # untouched by v1's flood
    assert [code_of(policy, "probe") for _ in range(3)] == \
        ["ADMITTED", "ADMITTED", "SENDER_RATE_LIMITED"]        # the probe key has its own limit
    assert code_of(policy, "v2") == "ADMITTED"
    clock.advance(1.0)
    assert code_of(policy, "v1") == "ADMITTED"


def test_a_sender_without_a_permit_cannot_drain_either_bucket():
    policy, _, _ = make_policy("v1", rate_per_second=1.0, burst=2, sender_burst=2,
                               sender_rate_per_second=1.0)
    for _ in range(100):
        assert code_of(policy, "stranger") == "SENDER_NOT_PERMITTED"
    assert code_of(policy, "v1") == "ADMITTED"
    assert len(policy._sender_buckets) == 1                    # strangers get no bucket


def test_the_probe_key_is_rate_limited_too():
    policy, _, _ = make_policy("v1", probe_hotkey="probe", rate_per_second=1.0, burst=1)
    assert code_of(policy, "probe") == "ADMITTED"
    assert code_of(policy, "probe") == "GLOBAL_RATE_LIMITED"


@pytest.mark.parametrize("bad", [
    {"refresh_seconds": 5.0}, {"refresh_seconds": float("nan")}, {"retry_seconds": 0.0},
    {"refresh_seconds": sp.MAX_REFRESH_SECONDS + 1},
    {"fetch_timeout_seconds": 0.0}, {"fetch_timeout_seconds": 99999.0},
    {"rate_per_second": 0.0}, {"burst": 0}, {"netuid": -1},
    {"sender_rate_per_second": 0.0}, {"sender_burst": 0},
    {"refresh_seconds": 600.0, "max_stale_seconds": 100.0},
    {"max_stale_seconds": sp.MAX_STALE_SECONDS + 1},
    {"max_stale_seconds": float("inf")},
])
def test_configuration_is_validated(bad):
    config = {"netuid": NETUID, **bad}
    with pytest.raises(ValueError):
        sp.SenderPolicyConfig(**config)


def test_the_longest_refresh_interval_is_accepted():
    sp.SenderPolicyConfig(netuid=NETUID, refresh_seconds=sp.MAX_REFRESH_SECONDS)


def test_an_empty_permit_set_fails_closed_and_says_so(caplog):
    with caplog.at_level(logging.WARNING, logger="sn87.miner.sender_policy"):
        policy, _, _ = make_policy(probe_hotkey="probe")
    assert policy.snapshot_size == 0 and "NO hotkey holds validator_permit" in caplog.text
    assert "WARNING: no hotkey holds validator_permit" in policy.describe()
    assert code_of(policy, "anyone") == "SENDER_NOT_PERMITTED"
    assert code_of(policy, "probe") == "ADMITTED"


# ---------------------------------------------------------------------- the opt-out

def test_the_opt_out_accepts_any_signed_sender_keeps_the_rate_limit_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="sn87.miner.sender_policy"):
        policy = sp.AllowAnySender(rate_per_second=1.0, burst=2, clock=FakeClock())
    assert "ALLOWLIST DISABLED" in caplog.text
    assert code_of(policy, "anyone") == "ADMITTED"
    assert code_of(policy, "someone-else") == "ADMITTED"
    assert code_of(policy, "third") == "GLOBAL_RATE_LIMITED"
    assert "DISABLED" in policy.describe()


# ---------------------------------------------------------------------- over HTTP

class MemoryStore:
    """An in-memory stand-in for the replay store: just what create_app and the SDK use."""

    domain, retention = "request", 13.0

    def __init__(self, receiver):
        self.receiver = receiver
        self.seen = set()
        self.writes = 0

    def check_and_store(self, hotkey, nonce):
        self.writes += 1
        if (hotkey, nonce) in self.seen:
            return False
        self.seen.add((hotkey, nonce))
        return True

    def ready(self):
        return True


def capsule():
    return {"qid": "q-sender-policy", "payload": "x"}


class Endpoint:
    def __init__(self, policy):
        self.server = throwaway_key()
        self.store = MemoryStore(self.server.ss58_address)
        self.handled = []

        def handle(value):
            self.handled.append(value["qid"])
            return {"qid": value["qid"], "state": "NO_MATERIAL_DEVIATION"}

        self.app = create_app(signer=self.server, store=self.store, handle=handle,
                              sender_policy=policy)

    def send(self, sender):
        body, headers = prepare_request(capsule(), sender, self.server.ss58_address)

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                         base_url="http://127.0.0.1") as client:
                return await client.post(PATH, content=body, headers=headers)
        return asyncio.run(run())


def test_over_http_a_permitted_validator_is_answered_and_a_stranger_never_reaches_the_method():
    validator, stranger = throwaway_key(), throwaway_key()
    policy, _, _ = make_policy(validator.ss58_address)
    endpoint = Endpoint(policy)
    assert endpoint.send(validator).status_code == 200
    assert endpoint.handled == ["q-sender-policy"]
    writes = endpoint.store.writes
    refused = endpoint.send(stranger)
    assert refused.status_code == 403 and refused.json() == {"error": "SENDER_NOT_PERMITTED"}
    assert endpoint.handled == ["q-sender-policy"]       # not called again
    assert endpoint.store.writes == writes               # no replay key written either


def test_over_http_a_revoked_permit_is_refused_after_the_refresh():
    validator = throwaway_key()
    policy, provider, clock = make_policy(validator.ss58_address, refresh_seconds=600.0)
    endpoint = Endpoint(policy)
    assert endpoint.send(validator).status_code == 200
    provider.permitted.clear()
    clock.advance(601)
    assert endpoint.send(validator).status_code == 200      # old snapshot; the read starts
    policy.wait_idle()
    assert endpoint.send(validator).json() == {"error": "SENDER_NOT_PERMITTED"}
    assert endpoint.handled == ["q-sender-policy"] * 2


def test_over_http_the_global_limit_answers_429_with_its_code():
    validator = throwaway_key()
    policy, _, _ = make_policy(validator.ss58_address, rate_per_second=0.001, burst=1)
    endpoint = Endpoint(policy)
    assert endpoint.send(validator).status_code == 200
    limited = endpoint.send(validator)
    assert limited.status_code == 429 and limited.json() == {"error": "GLOBAL_RATE_LIMITED"}
    assert endpoint.handled == ["q-sender-policy"]


def test_over_http_an_unavailable_policy_answers_503_and_fails_closed():
    validator = throwaway_key()
    policy, provider, _ = make_policy(validator.ss58_address, load=False)
    provider.fail = RuntimeError("down")
    refused = Endpoint(policy).send(validator)
    assert refused.status_code == 503 and refused.json() == {"error": "SENDER_POLICY_UNAVAILABLE"}


def test_over_http_one_sender_over_its_limit_gets_429_and_others_are_still_answered():
    flooder, other = throwaway_key(), throwaway_key()
    policy, _, _ = make_policy(flooder.ss58_address, other.ss58_address,
                               sender_rate_per_second=0.001, sender_burst=1)
    endpoint = Endpoint(policy)
    assert endpoint.send(flooder).status_code == 200
    limited = endpoint.send(flooder)
    assert limited.status_code == 429 and limited.json() == {"error": "SENDER_RATE_LIMITED"}
    assert endpoint.send(other).status_code == 200


def test_over_http_the_probe_key_is_answered_and_the_opt_out_answers_anyone():
    probe, stranger = throwaway_key(), throwaway_key()
    policy, _, _ = make_policy("someone", probe_hotkey=probe.ss58_address)
    endpoint = Endpoint(policy)
    assert endpoint.send(probe).status_code == 200
    assert endpoint.send(stranger).status_code == 403
    assert Endpoint(sp.AllowAnySender()).send(stranger).status_code == 200


# ---------------------------------------------------------------------- the command line

HOTKEY_ENV = "SN87_TEST_SENDER_POLICY_HOTKEY"


@pytest.fixture
def serve_env(monkeypatch):
    """`serve --check` with the store and the chain replaced by fakes."""
    from bittensor import sp_core

    monkeypatch.setenv(HOTKEY_ENV, sp_core.Keypair.generate_mnemonic())
    provider = FakeProvider("validator-1", "validator-2")
    monkeypatch.setattr(launcher, "build_store", lambda url, receiver: MemoryStore(receiver))
    monkeypatch.setattr(launcher, "probe_store", lambda store: "ok")
    monkeypatch.setattr(launcher, "build_permit_provider", lambda args: provider)
    return provider


def serve(*flags):
    return launcher.main(["serve", "--role", "candidate", "--hotkey-env", HOTKEY_ENV,
                          "--valkey-url", "redis://127.0.0.1:1/0", "--check", *flags])


def test_default_is_on_serve_without_a_netuid_or_the_opt_out_refuses(serve_env, capsys):
    assert serve() == 2
    assert "NETUID_REQUIRED" in capsys.readouterr().err
    assert serve_env.calls == 0


def test_default_is_on_check_reads_the_snapshot_and_reports_the_policy(serve_env, capsys):
    assert serve("--netuid", str(NETUID)) == 0
    out = capsys.readouterr().out
    assert "validator_permit allowlist on netuid 582" in out and "check: OK" in out
    assert serve_env.calls == 1


def test_serve_refuses_to_start_if_the_first_snapshot_cannot_be_read(serve_env, capsys):
    serve_env.fail = RuntimeError("SECRETDETAIL")
    assert serve("--netuid", str(NETUID)) == 2
    err = capsys.readouterr().err
    assert "SENDER_SNAPSHOT_FAILED: RuntimeError" in err and "SECRETDETAIL" not in err


def test_the_opt_out_flag_works_and_is_loud(serve_env, capsys, caplog):
    with caplog.at_level(logging.WARNING, logger="sn87.miner.sender_policy"):
        assert serve("--allow-any-sender") == 0
    captured = capsys.readouterr()
    assert "WARNING: --allow-any-sender" in captured.err
    assert "ALLOWLIST DISABLED" in captured.out and "ALLOWLIST DISABLED" in caplog.text
    assert serve_env.calls == 0                           # no chain read in this mode


def test_the_opt_out_is_refused_unless_the_bind_host_is_loopback(serve_env, capsys):
    assert serve("--allow-any-sender", "--host", ".".join(["0"] * 4), "--allow-non-loopback") == 2
    assert "ALLOW_ANY_SENDER_NON_LOOPBACK" in capsys.readouterr().err
    assert serve("--allow-any-sender", "--host", "127.0.0.1") == 0


def test_an_empty_permit_list_warns_on_stderr_and_in_the_policy_line(serve_env, capsys):
    serve_env.permitted.clear()
    assert serve("--netuid", str(NETUID)) == 0
    captured = capsys.readouterr()
    assert "WARNING: no hotkey holds validator_permit" in captured.err
    assert "WARNING: no hotkey holds validator_permit" in captured.out   # the policy line


def test_the_policy_line_names_the_chain_it_reads(monkeypatch, capsys):
    from bittensor import sp_core

    monkeypatch.setenv(HOTKEY_ENV, sp_core.Keypair.generate_mnemonic())
    monkeypatch.setattr(launcher, "build_store", lambda url, receiver: MemoryStore(receiver))
    monkeypatch.setattr(launcher, "probe_store", lambda store: "ok")
    sub, storage = fake_chain(genesis="0xmain")
    monkeypatch.setattr(glue.ChainPermitProvider, "_storage", staticmethod(lambda: storage))
    monkeypatch.setattr(glue.ChainPermitProvider, "_default_factory",
                        staticmethod(lambda endpoint: sub))
    assert serve("--netuid", str(NETUID), "--chain-endpoint", "wss://example.invalid:443",
                 "--chain-genesis", "0xmain") == 0
    assert "chain wss://example.invalid:443 (genesis 0xmain)" in capsys.readouterr().out


def test_another_netuid_needs_its_own_chain_endpoint_and_genesis(serve_env, monkeypatch, capsys):
    monkeypatch.undo()                                    # use the real build_permit_provider
    from bittensor import sp_core

    monkeypatch.setenv(HOTKEY_ENV, sp_core.Keypair.generate_mnemonic())
    monkeypatch.setattr(launcher, "build_store", lambda url, receiver: MemoryStore(receiver))
    monkeypatch.setattr(launcher, "probe_store", lambda store: "ok")
    assert serve("--netuid", "87") == 2
    assert "CHAIN_GENESIS_REQUIRED" in capsys.readouterr().err


def test_the_sender_rate_flags_are_validated(serve_env, capsys):
    assert serve("--netuid", str(NETUID), "--sender-rate-per-second", "1",
                 "--sender-rate-burst", "3") == 0
    assert "per sender 1/s burst 3" in capsys.readouterr().out
    assert serve("--netuid", str(NETUID), "--sender-rate-burst", "0") == 2
    assert serve("--netuid", str(NETUID), "--sender-refresh-seconds",
                 str(sp.MAX_REFRESH_SECONDS + 1)) == 2
    assert "SENDER_POLICY_INVALID: refresh_seconds" in capsys.readouterr().err


def test_the_opt_out_refuses_flags_that_only_mean_something_with_the_allowlist(serve_env, capsys):
    probe = throwaway_key().ss58_address
    assert serve("--allow-any-sender", "--probe-hotkey", probe) == 2
    assert "SENDER_POLICY_FLAGS_CONFLICT" in capsys.readouterr().err


def test_probe_hotkey_must_be_an_ss58_address_and_good_flags_are_accepted(serve_env, capsys):
    assert serve("--netuid", str(NETUID), "--probe-hotkey", "not-an-address") == 2
    assert "PROBE_HOTKEY_INVALID" in capsys.readouterr().err
    good = throwaway_key().ss58_address
    assert serve("--netuid", str(NETUID), "--probe-hotkey", good,
                 "--sender-refresh-seconds", "600", "--global-rate-per-second", "5",
                 "--global-rate-burst", "10") == 0
    assert "trusted senders" in capsys.readouterr().out


def test_bad_numbers_give_a_code(serve_env, capsys):
    assert serve("--netuid", str(NETUID), "--sender-refresh-seconds", "5") == 2
    assert "SENDER_POLICY_INVALID: refresh_seconds" in capsys.readouterr().err
    assert serve("--netuid", str(NETUID), "--global-rate-burst", "0") == 2
    assert "SENDER_POLICY_INVALID: rate" in capsys.readouterr().err


def test_a_chain_endpoint_override_needs_its_genesis(monkeypatch, capsys):
    from bittensor import sp_core

    monkeypatch.setenv(HOTKEY_ENV, sp_core.Keypair.generate_mnemonic())
    monkeypatch.setattr(launcher, "build_store", lambda url, receiver: MemoryStore(receiver))
    monkeypatch.setattr(launcher, "probe_store", lambda store: "ok")
    assert serve("--netuid", str(NETUID), "--chain-endpoint", "wss://example.invalid:443") == 2
    assert "CHAIN_GENESIS_REQUIRED" in capsys.readouterr().err


def test_probe_command_signs_with_the_named_probe_key(monkeypatch, capsys):
    from bittensor import sp_core

    mnemonic = sp_core.Keypair.generate_mnemonic()
    expected = sp_core.Keypair.create_from_mnemonic(mnemonic).ss58_address
    monkeypatch.setenv("SN87_TEST_PROBE_KEY", mnemonic)
    seen = {}

    def fake_exchange(endpoint, miner, url, **kwargs):
        seen["caller"] = kwargs.get("caller")
        return {"state": "FINDINGS", "findings": []}

    monkeypatch.setattr(glue, "probe_exchange", fake_exchange)
    base = ["probe", "--endpoint", "http://127.0.0.1:1", "--miner-hotkey", "x",
            "--valkey-url", "redis://127.0.0.1:1/0"]
    assert launcher.main([*base, "--probe-hotkey-env", "SN87_TEST_PROBE_KEY"]) == 0
    assert seen["caller"].ss58_address == expected
    assert launcher.main(base) == 0 and seen["caller"] is None     # the throwaway default
    assert launcher.main([*base, "--probe-hotkey-env", "SN87_TEST_UNSET_VARIABLE"]) == 2
    assert "HOTKEY_ENV_UNSET" in capsys.readouterr().err


def test_probe_against_an_allowlisted_endpoint_without_the_key_reports_the_code(monkeypatch,
                                                                                capsys):
    def refused(*args, **kwargs):
        raise BoundaryError("REMOTE_REJECTED")

    monkeypatch.setattr(glue, "probe_exchange", refused)
    assert launcher.main(["probe", "--endpoint", "http://127.0.0.1:1", "--miner-hotkey", "x",
                          "--valkey-url", "redis://127.0.0.1:1/0"]) == 2
    assert "PROBE_FAILED: REMOTE_REJECTED" in capsys.readouterr().err


# ---------------------------------------------------------------------- the chain provider

class FakeSubtensor:
    """Read-only SDK stand-in: storage values keyed by (name, params). Has no write method."""

    def __init__(self, genesis, values, block=4242):
        self.genesis, self.values, self.block = genesis, values, block
        self.queried = []
        self._client = self
        self._substrate = self

    def block_hash(self, number):
        return number

    def _call(self, value):
        return self.genesis

    def query(self, descriptor, params, block=None):
        self.queried.append((descriptor, tuple(params), block))
        return self.values[(descriptor, tuple(params))]


def fake_chain(genesis="0xgood"):
    names = {}

    class Storage:
        def __getattr__(self, name):
            return names.setdefault(name, f"storage:{name}")

    values = {("storage:SubnetworkN", (NETUID,)): 4,
              ("storage:ValidatorPermit", (NETUID,)): [True, False, True, False],
              ("storage:Keys", (NETUID, 0)): "hk-0", ("storage:Keys", (NETUID, 1)): "hk-1",
              ("storage:Keys", (NETUID, 2)): "hk-2", ("storage:Keys", (NETUID, 3)): "hk-3"}
    return FakeSubtensor(genesis, values), Storage()


def test_the_chain_provider_reads_only_permitted_hotkeys_through_storage_queries(monkeypatch):
    sub, storage = fake_chain()
    monkeypatch.setattr(glue.ChainPermitProvider, "_storage", staticmethod(lambda: storage))
    provider = glue.ChainPermitProvider("wss://example.invalid", "0xgood",
                                        subtensor_factory=lambda endpoint: sub)
    snapshot = provider.fetch(NETUID)
    assert snapshot.permitted == frozenset({"hk-0", "hk-2"}) and snapshot.block == 4242
    assert {name for name in dir(sub) if "submit" in name or "sign" in name} == set()
    assert all(call[0].startswith("storage:") for call in sub.queried)
    assert {call[2] for call in sub.queried} == {4242}         # every query pinned to one block
    assert [call[0] for call in sub.queried].count("storage:SubnetworkN") == 1


def test_the_chain_provider_refuses_an_endpoint_with_the_wrong_genesis(monkeypatch):
    sub, storage = fake_chain(genesis="0xhostile")
    monkeypatch.setattr(glue.ChainPermitProvider, "_storage", staticmethod(lambda: storage))
    provider = glue.ChainPermitProvider("wss://example.invalid", "0xgood",
                                        subtensor_factory=lambda endpoint: sub)
    with pytest.raises(sp.SnapshotError, match="CHAIN_GENESIS_MISMATCH"):
        provider.fetch(NETUID)
    assert sub.queried == []


def test_the_chain_provider_turns_any_read_error_into_a_code(monkeypatch):
    sub, storage = fake_chain()
    sub.values.clear()                                    # every query now raises KeyError
    monkeypatch.setattr(glue.ChainPermitProvider, "_storage", staticmethod(lambda: storage))
    provider = glue.ChainPermitProvider("wss://example.invalid", "0xgood",
                                        subtensor_factory=lambda endpoint: sub)
    with pytest.raises(sp.SnapshotError, match="SENDER_SNAPSHOT_READ_FAILED"):
        provider.fetch(NETUID)


def test_default_is_on_the_app_builder_cannot_be_called_without_a_sender_policy():
    import inspect

    parameter = inspect.signature(launcher.build_signed_app).parameters["sender_policy"]
    assert parameter.default is inspect.Parameter.empty
    assert launcher.build_parser().parse_args(
        ["serve", "--role", "candidate"]).allow_any_sender is False


# ---------------------------------------------------------------------- trusted senders

def test_trusted_senders_skip_only_the_permit_check_and_are_still_rate_limited():
    policy, _, clock = make_policy("v1", trusted_senders=("shadow-service", "other-service"),
                                   probe_hotkey="probe", sender_rate_per_second=1.0,
                                   sender_burst=2)
    for name in ("shadow-service", "other-service", "probe"):
        assert code_of(policy, name) == "ADMITTED"
    assert [code_of(policy, "shadow-service") for _ in range(2)] == \
        ["ADMITTED", "SENDER_RATE_LIMITED"]
    assert code_of(policy, "stranger") == "SENDER_NOT_PERMITTED"
    assert policy.config.trusted == ("shadow-service", "other-service", "probe")
    text = policy.describe()
    assert "trusted senders" in text and "shadow-service" in text and "probe" in text


def test_trusted_senders_are_listed_in_the_log_at_start_up(caplog):
    with caplog.at_level(logging.WARNING, logger="sn87.miner.sender_policy"):
        make_policy("v1", trusted_senders=("shadow-service",))
    assert "trusted sender(s) skip the permit check: shadow-service" in caplog.text


def test_the_trusted_sender_list_is_capped_and_deduplicated():
    ok = tuple(f"k{i}" for i in range(sp.MAX_TRUSTED_SENDERS))
    assert len(sp.SenderPolicyConfig(netuid=NETUID, trusted_senders=ok).trusted) == 8
    with pytest.raises(ValueError):
        sp.SenderPolicyConfig(netuid=NETUID, trusted_senders=(*ok, "one-more"))
    # seven trusted senders plus the probe key make eight: accepted
    assert len(sp.SenderPolicyConfig(netuid=NETUID, trusted_senders=ok[:7],
                                     probe_hotkey="p1x").trusted) == 8
    # eight trusted senders plus a ninth, the probe key: refused
    with pytest.raises(ValueError):
        sp.SenderPolicyConfig(netuid=NETUID, trusted_senders=ok, probe_hotkey="p2x")
    assert sp.SenderPolicyConfig(netuid=NETUID, trusted_senders=("a", "a"),
                                 probe_hotkey="a").trusted == ("a",)


def test_serve_takes_repeated_trusted_senders_and_probe_hotkey_as_an_alias(serve_env, capsys):
    one, two, three = (throwaway_key().ss58_address for _ in range(3))
    assert serve("--netuid", str(NETUID), "--trusted-sender", one, "--trusted-sender", two,
                 "--probe-hotkey", three) == 0
    out = capsys.readouterr().out
    assert all(address in out for address in (one, two, three)) and "trusted senders" in out
    assert serve("--netuid", str(NETUID), "--trusted-sender", "not-an-address") == 2
    assert "TRUSTED_SENDER_INVALID" in capsys.readouterr().err
    nine = [throwaway_key().ss58_address for _ in range(9)]
    flags = [f for address in nine for f in ("--trusted-sender", address)]
    assert serve("--netuid", str(NETUID), *flags) == 2
    assert "SENDER_POLICY_INVALID: trusted_senders" in capsys.readouterr().err
    assert serve("--allow-any-sender", "--trusted-sender", one) == 2
    assert "SENDER_POLICY_FLAGS_CONFLICT" in capsys.readouterr().err
