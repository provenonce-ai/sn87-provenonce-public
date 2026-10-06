"""Localhost miner server: byte identity with the in-process miner call, 4xx on malformed
input with the server still serving, loopback-only refusal, clean SIGTERM. LOCAL ONLY, NO CHAIN."""

import http.client
import importlib.util
import json
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from sn87_provenonce import classes
from sn87_provenonce.canonical import canonical_bytes, parse_canonical

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("miner_serve", ROOT / "scripts" / "miner_serve.py")
ms = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ms
spec.loader.exec_module(ms)


def _optional_staging():
    """The Provenonce staging harness, present only in the private source repository."""
    path = ROOT / "scripts" / "staging_subnet.py"
    if not path.exists():
        return None
    sspec = importlib.util.spec_from_file_location("staging_subnet", path)
    module = importlib.util.module_from_spec(sspec)
    sys.modules[sspec.name] = module
    sys.path.insert(0, str(ROOT / "scripts"))
    sspec.loader.exec_module(module)
    return module


staging = _optional_staging()
needs_staging = pytest.mark.skipif(staging is None,
                                   reason="the staging harness is private to Provenonce")


def public_instances(seed):
    """The 16 public challenge instances a validator derives for the committed profile
    (capsules only: the truth is the private reference executors' business)."""
    binding = classes.IC_APPROVAL_APPLICABILITY
    document = binding.profile.document
    plan = [family for section in ("assignment", "diagnostics")
            for family, n in document[section].items() for _ in range(n)]
    capsules = [binding.generate(family, seed * 1000 + index)
                for index, family in enumerate(plan)]
    return [{"qid": capsule["qid"], "capsule": capsule} for capsule in capsules]


def in_process(method, request):
    """The miner side of the byte boundary, called without HTTP."""
    return canonical_bytes(method(parse_canonical(request)))


@pytest.fixture(scope="module")
def compiled():
    return ms.compile_cmt()


@pytest.fixture(scope="module")
def cases(compiled):
    return public_instances(0)


@pytest.fixture(scope="module", params=["candidate", "baseline"])
def served(request, compiled):
    server = ms.MinerServer("127.0.0.1", 0, request.param, compiled)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield request.param, server
    server.shutdown()
    server.server_close()


def quad(*octets):
    """A dotted address built from octets: the tests refuse non-loopback hosts by value."""
    return ".".join(str(o) for o in octets)


def call(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data


def test_health(served):
    role, server = served
    status, data = call(server, "GET", "/health")
    assert status == 200
    h = json.loads(data)
    assert h["role"] == role and h["cmt_verified"] is True
    assert h["cmt_commitment"] == server.cmt_commitment


def test_responses_byte_identical_to_in_process(served, cases):
    role, server = served
    method = ms.role_method(role)
    assert len(cases) == 16
    for case in cases:
        request = canonical_bytes(case["capsule"])
        expected = in_process(method, request)
        status, data = call(server, "POST", "/cmt", request,
                            {"X-CMT-Commitment": server.cmt_commitment})
        assert status == 200 and data == expected


def test_malformed_gets_4xx_and_server_keeps_serving(served, cases):
    _, server = served
    good = canonical_bytes(cases[0]["capsule"])
    tampered = json.loads(good)
    tampered["nonce"] = "tampered"  # evidence commitment now broken
    bad = [(b"not json", {}), (b"", {}), (b"[1,2]", {}), (b"\xff\xfe", {}),
           (json.dumps(tampered).encode(), {}), (good[: len(good) // 2], {}),
           (b"x" * ((1 << 20) + 1), {})]
    for body, headers in bad:
        status, data = call(server, "POST", "/cmt", body, headers)
        assert 400 <= status < 500, (body[:20], status)
        assert "error" in json.loads(data)
    status, data = call(server, "POST", "/cmt", good, {"X-CMT-Commitment": "sha256:" + "0" * 64})
    assert status == 409 and json.loads(data)["error"] == "CMT_COMMITMENT_MISMATCH"
    status, data = call(server, "POST", "/other", good)
    assert status == 404
    status, data = call(server, "PUT", "/cmt", good)
    assert status == 405
    status, data = call(server, "GET", "/cmt")
    assert status == 404
    # still serving, still correct
    status, data = call(server, "POST", "/cmt", good)
    assert status == 200 and json.loads(data)["qid"] == cases[0]["qid"]


def test_grammar_mismatch_is_rejected(served, cases, monkeypatch):
    _, server = served
    monkeypatch.setattr(server, "grammar", "some-other-grammar/1")
    status, data = call(server, "POST", "/cmt", canonical_bytes(cases[0]["capsule"]))
    assert status == 400 and json.loads(data)["error"] == "CMT_GRAMMAR_MISMATCH"


def test_miner_failure_is_500_and_server_survives(served, cases, monkeypatch):
    _, server = served

    def boom(_capsule):
        raise RuntimeError("miner bug")
    monkeypatch.setattr(server, "method", boom)
    request = canonical_bytes(cases[0]["capsule"])
    status, data = call(server, "POST", "/cmt", request)
    assert status == 500 and json.loads(data)["error"] == "MINER_FAILED"
    monkeypatch.undo()
    assert call(server, "POST", "/cmt", request)[0] == 200


@pytest.mark.parametrize("host", [quad(0, 0, 0, 0), quad(192, 168, 1, 5), "example.com", "::", ""])
def test_non_loopback_refused(host, compiled):
    with pytest.raises(ms.RefusedHost):
        ms.MinerServer(host, 0, "candidate", compiled)
    assert ms.main(["--role", "candidate", "--port", "0", "--host",
                    host or quad(0, 0, 0, 0)]) == 2


def test_subprocess_serves_and_sigterm_exits_clean(cases):
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "miner_serve.py"), "--role", "candidate",
         "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        lines = [proc.stdout.readline(), proc.stdout.readline()]
        port = int(lines[1].split("http://127.0.0.1:")[1].split()[0])

        class S:
            server_address = ("127.0.0.1", port)
        status, data = call(S, "POST", "/cmt", canonical_bytes(cases[0]["capsule"]))
        assert status == 200
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_mapped_address_and_port_in_use_exit_2_cleanly(compiled, capsys):
    assert ms.main(["--role", "candidate", "--port", "0", "--host", "::ffff:127.0.0.1"]) == 2
    server = ms.MinerServer("127.0.0.1", 0, "candidate", compiled)
    try:
        port = server.server_address[1]
        assert ms.main(["--role", "baseline", "--port", str(port)]) == 2
        assert "MINER SERVE REFUSED" in capsys.readouterr().err
    finally:
        server.server_close()
    assert ms.Handler.timeout == 10


def test_importing_miner_serve_loads_no_bittensor():
    path = str(ROOT / "scripts" / "miner_serve.py")
    code = (
        "import importlib.util, sys\n"
        f"s = importlib.util.spec_from_file_location('m', {path!r})\n"
        "m = importlib.util.module_from_spec(s); sys.modules['m'] = m\n"
        "s.loader.exec_module(m)\n"
        "banned = ('bittensor', 'staging_subnet', 'pilot_chain_dry_run')\n"
        "bad = [k for k in sys.modules if k.split('.')[0] in banned]\n"
        "print(bad); sys.exit(1 if bad else 0)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


@needs_staging
def test_local_verify_matches_staging(compiled):
    assert ms.verify_compiled(compiled) == staging.verify_compiled(compiled)


@needs_staging
def test_local_verify_compiled_and_role_ids_agree_with_staging_subnet(compiled):
    """Drift guard: miner_serve keeps a local copy so it imports no bittensor."""
    assert ms.verify_compiled(compiled) == staging.verify_compiled(compiled)
    assert ms.verify_compiled(compiled) == compiled.compatibility.manifest_commitment
    assert (ms.CANDIDATE, ms.BASELINE_MINER) == (staging.CANDIDATE, staging.BASELINE_MINER)
    assert ms.ROLES == {"candidate": staging.CANDIDATE, "baseline": staging.BASELINE_MINER}
    wrong = compiled.model_copy(update={"compatibility": compiled.compatibility.model_copy(
        update={"manifest_commitment": "sha256:" + "0" * 64})})
    for fn, err in ((ms.verify_compiled, ms.StagingError),
                    (staging.verify_compiled, staging.StagingError)):
        with pytest.raises(err, match="CMT_HASH_VERIFICATION_FAILED"):
            fn(wrong)


def _fake_resolver(monkeypatch, addrs):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0)) for addr in addrs]
    monkeypatch.setattr(ms.socket, "getaddrinfo", fake)


def test_localhost_resolving_to_non_loopback_is_refused(monkeypatch, compiled):
    _fake_resolver(monkeypatch, ["127.0.0.1", quad(10, 0, 0, 5)])
    with pytest.raises(ms.RefusedHost, match="NON_LOOPBACK_HOST_REFUSED"):
        ms.require_loopback("localhost")
    with pytest.raises(ms.RefusedHost):
        ms.MinerServer("localhost", 0, "candidate", compiled)
    _fake_resolver(monkeypatch, [])
    with pytest.raises(ms.RefusedHost):
        ms.require_loopback("localhost")


def test_localhost_resolving_to_loopback_only_is_accepted(monkeypatch):
    _fake_resolver(monkeypatch, ["127.0.0.1", "::1"])
    assert ms.require_loopback("localhost") == "localhost"
    assert ms.require_loopback("127.0.0.1") == "127.0.0.1"


def test_body_read_timeout_logs_one_line_not_a_traceback(monkeypatch, compiled, capfd):
    import time
    monkeypatch.setattr(ms.Handler, "timeout", 0.3)
    server = ms.MinerServer("127.0.0.1", 0, "candidate", compiled)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        s = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=5)
        s.sendall(b"POST /cmt HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\nabc")
        time.sleep(1.0)  # the body never completes; the handler times out
        s.close()
        # the server still serves
        assert call(server, "GET", "/health")[0] == 200
    finally:
        server.shutdown()
        server.server_close()
    err = capfd.readouterr().err
    assert "Traceback" not in err
    assert len([ln for ln in err.splitlines() if "timed out" in ln]) == 1
