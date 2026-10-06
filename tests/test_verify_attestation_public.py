"""The attestation verifier as an outsider runs it: offline, standalone, no executors.

Uses only the verifier, the read-only chain client module and the canonical-JSON helper. A
synthetic attestation and an injected fake read client stand in for the files and the network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from sn87_provenonce.canonical import canonical_bytes

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_public_test",
                                                  ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


va = _load("verify_attestation")
cr = _load("chain_read")

REASON = "requires private reference executor"
ROW = {"dests": [1, 2], "weights": [65535, 65535]}


@pytest.fixture(autouse=True)
def _no_key_handling_modules_from_other_tests(monkeypatch):
    """Other tests may import key-handling code into this process; the verifier reports it."""
    for name in va.WALLET_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)


def seal(doc):
    body = {k: v for k, v in doc.items() if k != "attestation_digest"}
    doc["attestation_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
    return doc


def make_doc(blocks=(102, 202, 302)):
    runs = [{"run_id": f"r{i}", "confirm_seq": 10 + i, "included_block": b,
             "window_start": b - 2, "window_end": b + 50, "row": dict(ROW),
             "plan_digest": "sha256:" + "ab" * 32, "validator_seed": 0,
             "validator_timestamp": "2026-10-04T00:00:00Z",
             "validator_pinned_digest": "sha256:" + "cd" * 32}
            for i, b in enumerate(blocks)]
    return seal({"schema": "sn87.testnet_attestation.v1", "title": "synthetic", "netuid": 582,
                 "mecid": 0, "validator_uid": 0, "run_count": len(runs), "runs": runs})


class FakeReader:
    """Implements only the read interface (weight_row, last_weights_block)."""

    def __init__(self, doc, *, history=True, row=None, last_at=None, last_before=None):
        self.blocks = {r["included_block"] for r in doc["runs"]}
        self.history, self.row = history, row
        self.last_at, self.last_before = last_at, last_before

    def last_weights_block(self, netuid, uid, at_block=None):
        if at_block is None:
            return max(self.blocks)
        if not self.history:
            raise ConnectionError("state not available")
        if at_block in self.blocks:
            return at_block if self.last_at is None else self.last_at
        return (at_block - 3) if self.last_before is None else self.last_before

    def weight_row(self, netuid, mecid, uid, at_block=None):
        if at_block is not None and not self.history:
            raise ConnectionError("state not available")
        return dict(ROW) if self.row is None else self.row


def private_absent():
    raise va.PrivateUnavailable(REASON)


def run(doc, reader, **kw):
    kw.setdefault("plan_digest_fn", private_absent)
    kw.setdefault("validator_digest_fn", lambda seed, stamp: private_absent())
    return va.verify(doc, client=reader, **kw)


# ------------------------------------------------------------------------------- integrity
def test_integrity_passes_and_detects_tampering():
    doc = make_doc()
    assert va.check_integrity(doc)[0]
    doc["runs"][0]["row"]["weights"] = [1, 1]
    ok, detail = va.check_integrity(doc)
    assert not ok and "digest mismatch" in detail
    report = run(doc, FakeReader(doc))
    assert report["integrity"]["verdict"] == va.FAIL and report["verdict"] == va.FAIL


# ----------------------------------------------------------------------------------- chain
def test_chain_pass_for_a_faithful_attestation():
    doc = make_doc()
    report = run(doc, FakeReader(doc))
    assert report["chain"]["verdict"] == va.PASS and report["chain"]["tally"][va.PASS] == 3
    assert report["integrity"]["verdict"] == va.PASS


@pytest.mark.parametrize("kwargs", [{"row": {"dests": [1, 2], "weights": [1, 1]}},
                                    {"last_at": 5}, {"last_before": 102}])
def test_chain_fail_when_the_chain_disagrees(kwargs):
    doc = make_doc()
    report = run(doc, FakeReader(doc, **kwargs))
    assert report["chain"]["verdict"] == va.FAIL and report["verdict"] == va.FAIL


def test_chain_block_outside_window_fails():
    doc = make_doc()
    doc["runs"][0]["window_end"] = 100
    seal(doc)
    assert run(doc, FakeReader(doc))["chain"]["verdict"] == va.FAIL


def test_chain_without_history_is_unverified_never_pass():
    doc = make_doc()
    report = run(doc, FakeReader(doc, history=False))
    assert report["chain"]["verdict"] == va.UNVERIFIED and report["verdict"] != va.PASS
    assert all(r["checks"]["chain"]["verdict"] == va.UNVERIFIED for r in report["runs"])


def test_no_chain_client_is_unverified():
    doc = make_doc()
    report = va.verify(doc, plan_digest_fn=private_absent,
                       validator_digest_fn=lambda s, t: private_absent())
    assert report["chain"]["verdict"] == va.UNVERIFIED and report["verdict"] == va.UNVERIFIED


# ------------------------------------------------------------- private prerequisites absent
def test_plan_and_validator_are_unverified_with_the_private_reason_never_fail():
    doc = make_doc()
    report = run(doc, FakeReader(doc))
    for r in report["runs"]:
        for name in ("plan", "validator"):
            check = r["checks"][name]
            assert check["verdict"] == va.UNVERIFIED and REASON in check["detail"]
        assert r["verdict"] == va.UNVERIFIED
    assert va.FAIL not in (report["offline"]["verdict"], report["scoring"]["verdict"],
                           report["verdict"])
    assert report["verdict"] == va.UNVERIFIED and not report["ok"]
    text = va.render(report)
    assert "uv sync" not in text
    assert ("SUMMARY integrity: PASS; chain: 3/3 PASS; scoring: not verifiable outside "
            f"Provenonce (plan and validator UNVERIFIED: {REASON})") in text
    assert "OVERALL UNVERIFIED" in text and "exit code 3" in text


def test_real_default_functions_report_private_absence_when_prerequisites_are_missing(monkeypatch):
    """Simulate a public tree by monkeypatching, without deleting any file."""
    monkeypatch.setattr(va, "SCRIPTS", ROOT / "scripts" / "no_such_dir")
    with pytest.raises(va.PrivateUnavailable, match=REASON):
        va.compute_plan_digest()

    def fail_import(name, *args, **kwargs):
        raise ModuleNotFoundError("No module named 'classes'", name="classes")

    monkeypatch.delitem(sys.modules, "staging_subnet", raising=False)
    real_import = __import__
    monkeypatch.setattr("builtins.__import__",
                        lambda name, *a, **k: fail_import(name) if name == "staging_subnet"
                        else real_import(name, *a, **k))
    with pytest.raises(va.PrivateUnavailable, match=REASON):
        va.compute_validator_digest(0, "2026-10-04T00:00:00Z")
    doc = make_doc()
    report = va.verify(doc, client=FakeReader(doc))  # the real default functions
    assert report["verdict"] == va.UNVERIFIED and report["chain"]["verdict"] == va.PASS
    assert all(REASON in r["checks"]["validator"]["detail"] for r in report["runs"])


def test_a_missing_sdk_is_a_real_failure_with_the_fix_named(monkeypatch):
    import types

    def no_sdk(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'bittensor'", name="bittensor")

    fake = types.ModuleType("staging_subnet")
    fake.run_staging = no_sdk
    monkeypatch.setitem(sys.modules, "staging_subnet", fake)
    with pytest.raises(RuntimeError, match="uv sync --locked --extra transport"):
        va.compute_validator_digest(0, "t")


def test_a_real_scoring_mismatch_still_fails():
    doc = make_doc()
    report = run(doc, FakeReader(doc), plan_digest_fn=lambda: "sha256:" + "00" * 32,
                 validator_digest_fn=lambda s, t: "sha256:" + "cd" * 32)
    assert report["runs"][0]["checks"]["plan"]["verdict"] == va.FAIL
    assert report["runs"][0]["checks"]["validator"]["verdict"] == va.PASS
    assert report["verdict"] == va.FAIL


def test_overall_pass_needs_every_section_pass():
    doc = make_doc()
    report = run(doc, FakeReader(doc), plan_digest_fn=lambda: "sha256:" + "ab" * 32,
                 validator_digest_fn=lambda s, t: "sha256:" + "cd" * 32)
    assert report["verdict"] == va.PASS and report["ok"]
    assert "scoring: 6/6 PASS" in va.render(report)
    for verdict_set in ([va.PASS, va.UNVERIFIED], [va.UNVERIFIED, va.FAIL, va.PASS]):
        assert va.worst(verdict_set) != va.PASS


# --------------------------------------------------------------------------- cli, exit codes
def test_cli_exit_codes(tmp_path, capsys):
    doc = make_doc()
    path = tmp_path / "att.json"
    path.write_text(json.dumps(doc))
    reader = FakeReader(doc)
    args = ["--attestation", str(path), "--fake-home", str(tmp_path / "home")]
    kw = {"chain_client": lambda: reader, "plan_digest_fn": private_absent,
          "validator_digest_fn": lambda s, t: private_absent()}
    assert va.main(args, **kw) == 3
    assert "OVERALL UNVERIFIED" in capsys.readouterr().out
    full = {**kw, "plan_digest_fn": lambda: "sha256:" + "ab" * 32,
            "validator_digest_fn": lambda s, t: "sha256:" + "cd" * 32}
    assert va.main(args, **full) == 0
    assert "OVERALL PASS: 3/3" in capsys.readouterr().out
    bad = json.loads(path.read_text())
    bad["runs"][0]["row"]["weights"] = [1, 1]
    path.write_text(json.dumps(bad))
    assert va.main(args, **full) == 1
    assert va.main(["--attestation", str(tmp_path / "missing.json"),
                    "--fake-home", str(tmp_path / "home")], **kw) == 1


def test_verifier_has_no_process_wording_or_private_paths_or_eager_private_imports():
    source = (ROOT / "scripts" / "verify_attestation.py").read_text()
    # spelled in parts so that this test file does not itself contain them
    for needle in ("Q7" "3", "stew" "ard", "W" "26", "W" "29", "/Use" "rs/", "Drop" "box",
                   "ore" "sund", "flip_" "chain"):
        assert needle not in source, needle
    top_level = [ln for ln in source.splitlines() if re.match(r"(import|from) ", ln)]
    for line in top_level:
        for private in ("staging_subnet", "classes", "flip_", "shadow_", "pilot_chain"):
            assert private not in line, line


# --------------------------------------------------------------- the read-only client module
def test_chain_client_source_has_no_write_capable_names():
    source = (ROOT / "scripts" / "chain_read.py").read_text().lower()
    for needle in ("submit", "set_weights", "keypair", "wallet", "sign", "os.environ", "getenv",
                   "mnemonic", "password"):
        assert needle not in source, needle
    imports = re.findall(r"^\s*(?:import|from)\s+(\S+)", source, flags=re.M)
    assert set(imports) <= {"__future__", "collections.abc", "typing", "bittensor"}


def test_chain_client_exposes_only_reads_and_checks_the_genesis(monkeypatch):
    public = {n for n in dir(cr.ChainReader) if not n.startswith("_")}
    assert public == {"endpoint", "current_block", "last_weights_block", "weight_row"}

    class Sub:
        block = 7

        def __init__(self, genesis):
            self.genesis = genesis
            self._client = self
            self._substrate = self
            self.asked = []

        def block_hash(self, n):
            return self.genesis

        def _call(self, value):
            return value

        def query(self, descriptor, params, block=None):
            self.asked.append((descriptor, params, block))
            return [(1, 65535), (2, 65535)]

    sub = Sub(cr.GENESIS)
    reader = cr.ChainReader("wss://example.invalid", subtensor_factory=lambda e: sub)
    assert reader.current_block() == 7
    stub = type("S", (), {"Weights": "W", "LastUpdate": "L"})
    monkeypatch.setattr(cr, "_storage", lambda: stub)
    assert reader.weight_row(582, 0, 0, at_block=9) == ROW
    assert sub.asked[-1] == ("W", [582, 0], 9)
    wrong = cr.ChainReader(subtensor_factory=lambda e: Sub("0xdead"))
    with pytest.raises(cr.ChainRefused):
        wrong.current_block()


# ------------------------------------- executors absent: UNVERIFIED (exit 3), never FAIL
def test_a_late_private_executor_error_is_unverified_not_fail(monkeypatch):
    """After decoupling the staging module imports; the executor is missing only when called."""
    import types

    from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable

    def run_staging(**kwargs):
        raise PrivateReferenceExecutorUnavailable

    fake = types.ModuleType("staging_subnet")
    fake.run_staging = run_staging
    monkeypatch.setitem(sys.modules, "staging_subnet", fake)
    with pytest.raises(va.PrivateUnavailable, match=REASON):
        va.compute_validator_digest(0, "t")


def test_a_plan_child_failing_on_a_missing_executor_is_unverified(monkeypatch, tmp_path):
    tool = tmp_path / "flip_to_testnet.py"
    tool.write_text("import sys\nsys.stderr.write('PrivateReferenceExecutorUnavailable: x')\n"
                    "sys.exit(1)\n")
    monkeypatch.setattr(va, "SCRIPTS", tmp_path)
    with pytest.raises(va.PrivateUnavailable, match=REASON):
        va.compute_plan_digest()


def test_verifier_with_executors_blocked_reports_unverified_exit_3(tmp_path):
    """End to end in a subprocess: executors blocked, integrity PASS, scoring UNVERIFIED."""
    import subprocess

    doc = make_doc()
    path = tmp_path / "att.json"
    path.write_bytes(canonical_bytes(doc))
    code = f"""
import pathlib, sys
for n in ("sn87_provenonce.institutional_v02.references", "sn87_provenonce.pilot.reference",
          "sn87_provenonce.simulation.type_c_reference"):
    sys.modules[n] = None
sys.path.insert(0, {str(ROOT / "scripts")!r})
import verify_attestation as va
va.SCRIPTS = pathlib.Path({str(tmp_path / "no_scripts")!r})  # no plan tool: private-absent
doc = __import__("json").loads(open({str(path)!r}).read())
report = va.verify(doc, client=None)
print(report["verdict"], report["scoring"]["verdict"], report["integrity"]["ok"])
sys.exit(va.exit_code(report["verdict"]))
"""
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=ROOT, timeout=300)
    assert done.returncode == 3, (done.stdout, done.stderr)
    verdict, scoring, integrity = done.stdout.split()
    assert verdict == "UNVERIFIED" and scoring == "UNVERIFIED" and integrity == "True"
