"""``sn87-miner serve``: configuration checks, one wire for both servers, a real socket run.

Every key here is a fresh random throwaway generated in the test. Nothing touches a chain."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import httpx
import pytest
from bittensor import sp_core
from transport_support import dotted, throwaway_key

from sn87_provenonce.canonical import canonical_bytes, parse_canonical
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.miner_node import loopback
from sn87_provenonce.miner_node.core import MinerCore
from sn87_provenonce.miner_node.launcher import build_signed_app, main, redact_url
from sn87_provenonce.pilot.client import exchange, prepare_request
from sn87_provenonce.pilot.transport import PATH, SharedReplayStore

HOTKEY_ENV = "SN87_TEST_MINER_HOTKEY"
FAMILIES = ("stale_authority", "fresh_review", "incomplete")

pytest_plugins = ["transport_fixtures"]


def mnemonic_key():
    mnemonic = sp_core.Keypair.generate_mnemonic()
    return mnemonic, sp_core.Keypair.create_from_mnemonic(mnemonic)


@pytest.fixture
def hotkey(monkeypatch):
    mnemonic, key = mnemonic_key()
    monkeypatch.setenv(HOTKEY_ENV, mnemonic)
    return mnemonic, key


def leaks(mnemonic, text):
    """True when the key phrase, or any three consecutive words of it, appear in ``text``."""
    words = mnemonic.split()
    return any(" ".join(words[i:i + 3]) in text for i in range(len(words) - 2))


def serve(*flags):
    return main(["serve", *flags])


def test_check_validates_probes_the_store_and_starts_nothing(hotkey, valkey_url, capsys):
    mnemonic, key = hotkey
    assert serve("--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--valkey-url", valkey_url,
                 "--port", "1", "--check") == 0
    out = capsys.readouterr()
    assert "CONFIGURATION CHECK ONLY" in out.out and "check: OK" in out.out
    assert key.ss58_address in out.out and "replay store check: ok" in out.out
    assert "role=candidate" in out.out and "cmt: sha256:" in out.out
    assert not leaks(mnemonic, out.out + out.err)
    assert serve("--role", "baseline", "--hotkey-env", HOTKEY_ENV, "--valkey-url", valkey_url,
                 "--dry-run") == 0


def test_check_fails_closed_when_the_store_is_unreachable_and_hides_credentials(hotkey, capsys):
    url = "redis://operator:sup3rsecretpw@127.0.0.1:1/0"
    assert serve("--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--valkey-url", url,
                 "--check") == 2
    out = capsys.readouterr()
    assert "REPLAY_STORE_UNAVAILABLE" in out.err
    assert "sup3rsecretpw" not in out.out + out.err and "operator" not in out.out + out.err
    assert redact_url(url) == "redis://127.0.0.1:1/0"


def test_check_reads_the_url_and_key_from_named_variables(hotkey, valkey_url, monkeypatch, capsys):
    monkeypatch.setenv("SN87_TEST_STORE_URL", valkey_url)
    assert serve("--role", "candidate", "--hotkey-env", HOTKEY_ENV,
                 "--valkey-url-env", "SN87_TEST_STORE_URL", "--check") == 0
    assert "check: OK" in capsys.readouterr().out


def test_keyfile_source_requires_a_private_file(tmp_path, valkey_url, capsys):
    mnemonic, key = mnemonic_key()
    path = tmp_path / "miner.secret"
    path.write_text(mnemonic)
    path.chmod(0o644)
    flags = ("--role", "candidate", "--hotkey-keyfile", str(path), "--valkey-url", valkey_url,
             "--check")
    assert serve(*flags) == 2
    assert "HOTKEY_FILE_PERMISSIONS_TOO_OPEN" in capsys.readouterr().err
    path.chmod(0o600)
    assert serve(*flags) == 0
    assert key.ss58_address in capsys.readouterr().out
    # the SDK's own unencrypted key file format is accepted as well
    sdk = tmp_path / "miner.sdk"
    sdk.write_bytes(sp_core.serialized_keypair_to_keyfile_data(key))
    sdk.chmod(0o600)
    assert serve("--role", "candidate", "--hotkey-keyfile", str(sdk), "--valkey-url",
                 valkey_url, "--check") == 0


@pytest.mark.parametrize("flags, code", [
    (["--role", "candidate"], "HOTKEY_SOURCE_REQUIRED"),
    (["--role", "candidate", "--hotkey-env", "SN87_TEST_UNSET_VARIABLE"], "HOTKEY_ENV_UNSET"),
    ([], "METHOD_REQUIRED"),
    (["--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--host", dotted(0, 0, 0, 0)],
     "NON_LOOPBACK_HOST_REFUSED"),
    (["--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--port", "0"], "PORT_INVALID"),
    (["--method", "no-such path", "--hotkey-env", HOTKEY_ENV], "METHOD_PATH_INVALID"),
    (["--method", "transport_support:missing", "--hotkey-env", HOTKEY_ENV], "METHOD_NOT_FOUND"),
    (["--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--valkey-url", "http://127.0.0.1/0"],
     "VALKEY_URL_SCHEME_INVALID"),
    (["--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--valkey-url", "redis://127.0.0.1/0",
      "--announcement", "unused.json"], "NETUID_REQUIRED"),
])
def test_configuration_errors_exit_2_with_a_stable_code(hotkey, capsys, flags, code):
    assert serve(*flags, "--check") == 2
    assert code in capsys.readouterr().err


def test_bad_key_text_is_refused_without_echoing_it(monkeypatch, valkey_url, capsys):
    monkeypatch.setenv(HOTKEY_ENV, "plainly not a key phrase xyzzy")
    assert serve("--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--valkey-url", valkey_url,
                 "--check") == 2
    out = capsys.readouterr()
    assert "HOTKEY_FORMAT_UNRECOGNIZED" in out.err and "xyzzy" not in out.out + out.err


def test_role_and_method_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as stop:
        serve("--role", "candidate", "--method", "transport_support:echo_differential")
    assert stop.value.code == 2


def test_a_custom_method_path_is_served_and_checked(hotkey, valkey_url, capsys):
    assert serve("--method", "transport_support:echo_differential", "--hotkey-env", HOTKEY_ENV,
                 "--valkey-url", valkey_url, "--check") == 0
    out = capsys.readouterr().out
    assert "method=transport_support:echo_differential" in out and "cmt:" not in out


def test_unsigned_loopback_is_explicit_and_takes_no_signing_flags(hotkey, capsys):
    assert serve("--unsigned-loopback", "--role", "candidate", "--check") == 0
    out = capsys.readouterr()
    assert "UNSIGNED" in out.err and "check: OK (unsigned loopback" in out.out
    assert serve("--unsigned-loopback", "--role", "candidate", "--hotkey-env", HOTKEY_ENV,
                 "--check") == 2
    assert "UNSIGNED_LOOPBACK_TAKES_NO: --hotkey-env" in capsys.readouterr().err
    assert serve("--unsigned-loopback", "--role", "candidate", "--host", dotted(0, 0, 0, 0),
                 "--check") == 2


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_one_method_one_set_of_bytes_on_the_signed_and_the_loopback_wire(valkey_url, redis):
    sender, server = throwaway_key(), throwaway_key()
    core = MinerCore.from_role("candidate")
    store = SharedReplayStore.from_url(valkey_url, receiver=server.ss58_address,
                                       domain="request")
    redis.set(store.prefix + ":generation", redis.info("server")["run_id"] + ":0")
    app = build_signed_app(core, server, store)
    loop = loopback.MinerServer("127.0.0.1", 0, "candidate", core.compiled)
    thread = threading.Thread(target=loop.serve_forever, daemon=True)
    thread.start()
    try:
        async def signed_answer(capsule):
            body, headers = prepare_request(capsule, sender, server.ss58_address)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://127.0.0.1") as client:
                response = await client.post(PATH, content=body, headers=headers)
            assert response.status_code == 200, response.content
            return canonical_bytes(parse_canonical(response.content)["differential"])

        for family in FAMILIES:
            capsule = build_case(family)
            request = urllib.request.Request(
                f"http://127.0.0.1:{loop.server_address[1]}/cmt",
                data=canonical_bytes(capsule), method="POST")
            with urllib.request.urlopen(request) as response:
                unsigned = response.read()
            assert unsigned == core.answer(canonical_bytes(capsule))
            assert asyncio.run(signed_answer(capsule)) == unsigned
    finally:
        loop.shutdown()
        loop.server_close()


def test_signed_app_serves_the_announcement_verbatim_and_nothing_else_new(valkey_url, redis):
    from sn87_provenonce.miner_node import announcement as ann

    server = throwaway_key()
    now = time.time_ns() // 1_000_000
    record = ann.sign(ann.Announcement(
        netuid=582, hotkey=server.ss58_address, endpoint="https://example.invalid",
        sequence=1, issued_at_ms=now, expires_at_ms=now + 3_600_000), server)
    store = SharedReplayStore.from_url(valkey_url, receiver=server.ss58_address,
                                       domain="request")
    app = build_signed_app(MinerCore.from_path("transport_support:echo_differential"), server,
                           store, announcement_record=record)

    async def get(path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://127.0.0.1") as client:
            return await client.get(path)

    served = asyncio.run(get(ann.WELL_KNOWN_PATH))
    assert served.status_code == 200 and served.content == record
    assert asyncio.run(get("/unlisted")).status_code == 404


def _wait_ready(port, process, deadline=30):
    started = time.monotonic()
    while time.monotonic() - started < deadline:
        if process.poll() is not None:
            pytest.fail(f"miner exited early with {process.returncode}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/ready", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    pytest.fail("miner endpoint did not become ready")


def test_a_real_process_answers_a_signed_request_over_a_socket(tmp_path, valkey_url, redis):
    """The whole path: the CLI starts uvicorn behind create_app; the repo's client sends a
    signed request; the response verifies; a replay is refused; SIGTERM stops it cleanly."""
    mnemonic, miner = mnemonic_key()
    caller = throwaway_key()
    port = free_port()
    request_store = SharedReplayStore(redis, receiver=miner.ss58_address, domain="request")
    # skip the first-start quarantine: this store is new and belongs to this test only
    redis.set(request_store.prefix + ":generation", redis.info("server")["run_id"] + ":0")
    log = tmp_path / "miner.log"
    with log.open("wb") as sink:
        process = subprocess.Popen(
            [sys.executable, "-m", "sn87_provenonce.miner_node", "serve", "--role", "candidate",
             "--port", str(port), "--hotkey-env", HOTKEY_ENV, "--valkey-url", valkey_url],
            env={**os.environ, HOTKEY_ENV: mnemonic}, stdout=sink, stderr=sink)
    try:
        _wait_ready(port, process)
        response_store = SharedReplayStore.from_url(
            valkey_url, receiver=caller.ss58_address, domain="response")
        redis.set(response_store.prefix + ":generation", redis.info("server")["run_id"] + ":0")
        capsule = build_case("stale_authority")
        differential = asyncio.run(exchange(
            endpoint=f"http://127.0.0.1:{port}", capsule=capsule, signer=caller,
            receiver=miner.ss58_address, store=response_store))
        assert differential["state"] == "FINDINGS"
        assert [f["code"] for f in differential["findings"]] == ["STALE_APPROVAL"]
        body, headers = prepare_request(capsule, caller, miner.ss58_address)
        first = httpx.post(f"http://127.0.0.1:{port}{PATH}", content=body, headers=headers)
        again = httpx.post(f"http://127.0.0.1:{port}{PATH}", content=body, headers=headers)
        assert (first.status_code, again.status_code) == (200, 401)
        assert again.json() == {"error": "REPLAYED_REQUEST"}
        # the unsigned development wire is not exposed on the signed endpoint
        assert httpx.post(f"http://127.0.0.1:{port}/cmt", content=canonical_bytes(capsule)
                          ).status_code in {404, 405}
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()
    text = log.read_text()
    assert miner.ss58_address in text and "no chain access" in text
    assert not leaks(mnemonic, text)


def test_the_launcher_starts_the_unsigned_loopback_server_on_request(tmp_path):
    log = tmp_path / "loopback.log"
    with log.open("wb") as sink:
        process = subprocess.Popen(
            [sys.executable, "-m", "sn87_provenonce.miner_node", "serve", "--unsigned-loopback",
             "--role", "baseline", "--port", "0"], stdout=subprocess.PIPE, stderr=sink, text=True)
    try:
        lines = [process.stdout.readline(), process.stdout.readline()]
        port = int(lines[1].split("http://127.0.0.1:")[1].split()[0])
        health = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/health"))
        assert health["role"] == "baseline" and "UNSIGNED" in health["label"]
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()


def test_probe_round_trip_against_a_running_endpoint(valkey_url, redis, capsys):
    """The probe is the self-test for an outside miner: one signed fixture request from a
    throwaway caller key, the response verified. The caller's response store is pre-set here
    (it is quarantined for one freshness window on first use otherwise)."""
    from sn87_provenonce.miner_node.transport_glue import probe_exchange

    mnemonic, miner = mnemonic_key()
    caller = throwaway_key()
    port = free_port()
    for receiver, domain in ((miner.ss58_address, "request"), (caller.ss58_address, "response")):
        store = SharedReplayStore(redis, receiver=receiver, domain=domain)
        redis.set(store.prefix + ":generation", redis.info("server")["run_id"] + ":0")
    process = subprocess.Popen(
        [sys.executable, "-m", "sn87_provenonce.miner_node", "serve", "--role", "baseline",
         "--port", str(port), "--hotkey-env", HOTKEY_ENV, "--valkey-url", valkey_url],
        env={**os.environ, HOTKEY_ENV: mnemonic}, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    try:
        _wait_ready(port, process)
        differential = probe_exchange(f"http://127.0.0.1:{port}", miner.ss58_address,
                                      valkey_url, caller=caller)
        assert differential["state"] == "FINDINGS"
        with pytest.raises(Exception):  # noqa: B017 - any verification failure is the point
            probe_exchange(f"http://127.0.0.1:{port}", throwaway_key().ss58_address, valkey_url,
                           caller=caller)
    finally:
        process.terminate()
        process.wait(timeout=15)


def test_probe_refuses_a_bad_store_url_before_sending_anything(capsys):
    assert main(["probe", "--endpoint", "http://127.0.0.1:1", "--miner-hotkey", "x",
                 "--valkey-url", "http://127.0.0.1:1/0"]) == 2
    assert "VALKEY_URL_SCHEME_INVALID" in capsys.readouterr().err


def test_malformed_store_urls_and_unset_variables_give_codes_without_echo(hotkey, monkeypatch,
                                                                         capsys):
    secret_url = "redis://user:p4ssw0rd@127.0.0.1:abc/0"
    assert serve("--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--valkey-url", secret_url,
                 "--check") == 2
    out = capsys.readouterr()
    assert "VALKEY_URL_INVALID" in out.err and "Traceback" not in out.err
    assert "p4ssw0rd" not in out.out + out.err
    # a URL passed where a variable NAME belongs is not echoed back
    assert serve("--role", "candidate", "--hotkey-env", HOTKEY_ENV,
                 "--valkey-url-env", "redis://user:p4ssw0rd@127.0.0.1/0", "--check") == 2
    out = capsys.readouterr()
    assert "VALKEY_URL_ENV_UNSET" in out.err and "p4ssw0rd" not in out.out + out.err
    assert serve("--role", "candidate", "--hotkey-env", "SN87_TEST_UNSET_VARIABLE",
                 "--valkey-url", "redis://127.0.0.1/0", "--check") == 2
    assert "SN87_TEST_UNSET_VARIABLE" not in capsys.readouterr().err


def test_probe_failure_prints_a_code_not_a_library_message(monkeypatch, capsys):
    import sn87_provenonce.miner_node.transport_glue as glue

    def boom(*args, **kwargs):
        raise RuntimeError("GET http://127.0.0.1:1/secret-path failed")

    monkeypatch.setattr(glue, "probe_exchange", boom)
    assert main(["probe", "--endpoint", "http://127.0.0.1:1", "--miner-hotkey", "x",
                 "--valkey-url", "redis://127.0.0.1:1/0"]) == 2
    err = capsys.readouterr().err
    assert "PROBE_FAILED: RuntimeError" in err and "secret-path" not in err


def test_localhost_is_loopback_only_if_every_resolved_address_is(monkeypatch, valkey_url, hotkey,
                                                                 capsys):
    from sn87_provenonce.miner_node import launcher

    def resolver(*addresses):
        def fake(host, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, 0)) for x in addresses]
        return fake

    monkeypatch.setattr(launcher.socket, "getaddrinfo", resolver("127.0.0.1", "::1"))
    assert launcher.is_loopback("localhost") is True
    monkeypatch.setattr(launcher.socket, "getaddrinfo",
                        resolver("127.0.0.1", dotted(10, 0, 0, 5)))
    assert launcher.is_loopback("localhost") is False
    monkeypatch.setattr(launcher.socket, "getaddrinfo", resolver())
    assert launcher.is_loopback("localhost") is False

    def failing(*a, **k):
        raise socket.gaierror

    monkeypatch.setattr(launcher.socket, "getaddrinfo", failing)
    assert launcher.is_loopback("localhost") is False
    # the serve command refuses it without --allow-non-loopback
    monkeypatch.setattr(launcher.socket, "getaddrinfo",
                        resolver("127.0.0.1", dotted(10, 0, 0, 5)))
    assert serve("--role", "candidate", "--hotkey-env", HOTKEY_ENV, "--valkey-url", valkey_url,
                 "--host", "localhost", "--check") == 2
    assert "NON_LOOPBACK_HOST_REFUSED" in capsys.readouterr().err


def test_announce_sequence_is_strictly_monotonic_and_never_repeats(tmp_path, hotkey, capsys):
    first, second, third = (tmp_path / n for n in ("a1.json", "a2.json", "a3.json"))
    base = ["announce", "--hotkey-env", HOTKEY_ENV, "--netuid", "582", "--endpoint",
            "https://example.invalid", "--issued-at-ms", "1800000000000"]
    assert main([*base, "--out", str(first)]) == 0
    seq1 = json.loads(first.read_bytes())["announcement"]["sequence"]
    assert seq1 == 1800000000000
    # same issue time (a collision in the old seconds-based scheme): one more than the previous
    assert main([*base, "--previous", str(first), "--out", str(second)]) == 0
    assert json.loads(second.read_bytes())["announcement"]["sequence"] == seq1 + 1
    # an explicit sequence that does not exceed the previous one is refused
    for explicit in (seq1 + 1, seq1):
        capsys.readouterr()
        assert main([*base, "--previous", str(second), "--sequence", str(explicit),
                     "--out", str(third)]) == 2
        assert "SEQUENCE_NOT_INCREASING" in capsys.readouterr().err
    assert not third.exists()
    # a previous file for another hotkey or netuid is refused
    other = tmp_path / "other.json"
    assert main([*base[:-2], "--netuid", "1", "--endpoint", "https://example.invalid",
                 "--issued-at-ms", "1", "--previous", str(first), "--out", str(other)]) == 2
    assert "PREVIOUS_ANNOUNCEMENT_INVALID" in capsys.readouterr().err


def test_announce_with_a_maximum_previous_sequence_has_a_clear_error(tmp_path, hotkey, capsys):
    base = ["announce", "--hotkey-env", HOTKEY_ENV, "--netuid", "582", "--endpoint",
            "https://example.invalid", "--issued-at-ms", "1800000000000"]
    last = tmp_path / "last.json"
    assert main([*base, "--sequence", str(2**53 - 1), "--out", str(last)]) == 0
    capsys.readouterr()
    assert main([*base, "--previous", str(last), "--out", str(tmp_path / "next.json")]) == 2
    assert "SEQUENCE_EXHAUSTED" in capsys.readouterr().err
