#!/usr/bin/env python3
"""Verify the SN87 testnet attestation. READ ONLY: no key, no chain write.

  uv run --extra transport python scripts/verify_attestation.py [--attestation <file>]
                                                          # default: attestation 02

First run ``uv sync --locked --extra transport``: a plain ``uv run`` drops the bittensor
dependency and the chain checks then cannot run.

The same file runs in the full Provenonce tree and in the public tree. Sections:

  1. INTEGRITY (always runs)
     integrity  the attestation's own digest recomputes, and netuid/mecid/validator_uid are
                582/0/0. This is tamper evidence only: the digest sits in the file itself.
  2. CHAIN CORROBORATION (always runs; third-party checkable)
     chain      per run, AT ITS OWN BLOCK: uid 0's LastUpdate is the included block there and is
                strictly less one block earlier, the uid 0 weight row at that block equals the
                attested row, and the block lies inside the run's window. If the node cannot
                serve state at that block the run is UNVERIFIED, never PASS. The current-state
                read made afterwards is printed as supplementary information only.
  3. SCORING (runs only when its prerequisites are present)
     plan       per run, the approved plan digest, recomputed by running
                Provenonce's private flip-plan tool (``flip_to_testnet.py --plan --json``, run as a
                subprocess) equals the attested one.
     validator  per run, the validator pinned digest, recomputed in process from the committed
                fixtures (the private staging harness, ``staging_subnet.run_staging``, with the
                attested seed and timestamp, no network beyond loopback), equals the attested
                one.
     Both need the private reference executors. Where they are absent the two checks are
     UNVERIFIED with the reason "requires private reference executor", never FAIL: scoring is
     not verifiable outside Provenonce.

Verdicts are PASS, FAIL and UNVERIFIED, per run and overall. A run is FAIL if any check fails,
else UNVERIFIED if any check is, else PASS. Overall: FAIL if any FAIL; UNVERIFIED if none FAIL
but any is UNVERIFIED; PASS only if everything is PASS.
Exit codes: 0 = PASS, 1 = FAIL, 3 = UNVERIFIED (2 is argparse's usage error).

Chain reads use ``chain_read.ChainReader`` only (a minimal read-only client) under a scratch
HOME. The network endpoint defaults to the public testnet node; ``--endpoint`` names another
node, which must still serve the testnet genesis.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
from sn87_provenonce.canonical import canonical_bytes  # noqa: E402, F401  (digest rule)
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable  # noqa: E402

DEFAULT_ATTESTATION = ROOT / "attestation" / "SN87_TESTNET_ATTESTATION_02.json"
SCHEMA = "sn87.testnet_attestation.v1"
DIGEST_FIELD = "attestation_digest"
NETUID = 582
MECID = 0
VALIDATOR_UID = 0
WALLET_MODULES = ("flip_wallet", "flip_runlive", "bittensor_wallet", "bittensor.wallet",
                  "bittensor.keyfiles", "bittensor.wallets")
PRIVATE_REASON = "requires private reference executor"


class VerifyRefused(RuntimeError):
    """The verifier refuses to run in this environment (a real HOME)."""


class PrivateUnavailable(RuntimeError):
    """A prerequisite that only the private tree has is absent: the check is UNVERIFIED."""


def _is_int(value: Any) -> bool:
    return type(value) is int


# ------------------------------------------------------------------------------- environment
PLATFORM_POLICY = (
    "supported platforms are Linux and macOS (Windows through WSL2); native Windows is "
    "unsupported because it lacks the pwd database and the descriptor-anchored, "
    "symlink-refusing file controls (O_DIRECTORY, O_NOFOLLOW) the evidence bundle requires"
)


def _real_home() -> str:
    """The account database's home for this user. ``pwd`` is imported here, not at module
    level, so importing this script works on platforms that lack it."""
    try:
        import pwd
    except ImportError as error:
        raise VerifyRefused(
            f"the account database (pwd) is unavailable: {PLATFORM_POLICY}"
        ) from error
    return pwd.getpwuid(os.getuid()).pw_dir


def require_fake_home(env: dict[str, str] | None = None, real_home: str | None = None) -> None:
    """The chain read must run under a fake HOME so no wallet or key directory can be reached."""
    env = os.environ if env is None else env
    if real_home is None:
        real_home = _real_home()
    home = env.get("HOME")
    if not home or os.path.realpath(home) == os.path.realpath(real_home):
        raise VerifyRefused("run with HOME set to a scratch directory, not the real home")
    wallets = env.get("BT_WALLET_PATH", "")
    if wallets and not os.path.realpath(wallets).startswith(os.path.realpath(home) + os.sep):
        raise VerifyRefused("BT_WALLET_PATH must sit inside the fake HOME")


def isolate_home(fake_home: Path | None) -> tempfile.TemporaryDirectory | None:
    """Point HOME and BT_WALLET_PATH at a scratch directory before any SDK import. With no
    explicit directory, a fresh temporary one is made and returned (it removes itself)."""
    holder = None
    if fake_home is None:
        holder = tempfile.TemporaryDirectory(prefix="sn87-verify-home-")
        fake_home = Path(holder.name)
    fake_home.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(fake_home)
    os.environ["BT_WALLET_PATH"] = str(fake_home / "wallets")
    require_fake_home()
    return holder


# --------------------------------------------------------------------- recomputed references
def _private_import_error(error: ImportError) -> bool:
    """True when the failed import is a module of this tree (private or absent), not the SDK."""
    return not (error.name or "").startswith("bittensor")


def compute_plan_digest() -> str:
    """The plan digest from ``flip_to_testnet.py --plan --json`` in a child process."""
    tool = SCRIPTS / "flip_to_testnet.py"
    if not tool.is_file():
        raise PrivateUnavailable(PRIVATE_REASON)
    proc = subprocess.run([sys.executable, str(tool), "--plan", "--json"], cwd=ROOT,
                          capture_output=True, text=True, timeout=180, check=False)
    if proc.returncode != 0:
        if ("ModuleNotFoundError" in proc.stderr and "bittensor" not in proc.stderr) or (
                "PrivateReferenceExecutorUnavailable" in proc.stderr):
            raise PrivateUnavailable(PRIVATE_REASON)
        raise RuntimeError(f"flip_to_testnet --plan exited {proc.returncode}")
    digest = json.loads(proc.stdout).get("plan_digest")
    if not isinstance(digest, str):
        raise RuntimeError("flip_to_testnet --plan printed no plan_digest")
    return digest


TRANSPORT_HINT = ("run uv sync --locked --extra transport "
                  "(a plain uv run drops the bittensor dependency)")


def compute_validator_digest(seed: int, timestamp: str) -> str:
    """The validator pinned digest from the committed fixtures, in process (loopback only).

    Imported lazily: the staging module and the private reference executors it needs are not
    part of the public tree. Without them the check is UNVERIFIED, not a failure."""
    try:
        import staging_subnet  # noqa: PLC0415 - loads the SDK: only after the fake HOME is set
        receipt = staging_subnet.run_staging(seed=seed, timestamp=timestamp)
    except PrivateReferenceExecutorUnavailable as error:
        raise PrivateUnavailable(PRIVATE_REASON) from error
    except ImportError as error:
        if _private_import_error(error):
            raise PrivateUnavailable(PRIVATE_REASON) from error
        raise RuntimeError(f"{error}; {TRANSPORT_HINT}") from error
    if receipt["volatile"]["network_attempts"] != 0:
        raise RuntimeError("the staging run attempted a network connection")
    return receipt["pinned_digest"]


def make_read_client(endpoint: str | None = None) -> Any:
    """The minimal read-only chain client (``chain_read.ChainReader``)."""
    try:
        import chain_read  # noqa: PLC0415 - the module itself never loads the SDK on import
    except ImportError as error:
        raise RuntimeError(f"cannot load chain_read: {error}") from error
    return chain_read.ChainReader(endpoint or chain_read.ENDPOINT)


# ------------------------------------------------------------------------------------ checks
def check_integrity(doc: Any) -> tuple[bool, str]:
    if not isinstance(doc, dict):
        return False, "the file is not a JSON object"
    claimed = doc.get(DIGEST_FIELD)
    if not isinstance(claimed, str):
        return False, f"no {DIGEST_FIELD}"
    if doc.get("schema") != SCHEMA:
        return False, f"unknown schema {doc.get('schema')!r}"
    for field, expected in (("netuid", NETUID), ("mecid", MECID),
                            ("validator_uid", VALIDATOR_UID)):
        if not _is_int(doc.get(field)) or doc[field] != expected:
            return False, (f"{field} is {doc.get(field)!r}, this verifier checks {field} "
                           f"{expected} only")
    import hashlib  # noqa: PLC0415

    try:
        body = {k: v for k, v in doc.items() if k != DIGEST_FIELD}
        actual = "sha256:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
    except ValueError as error:
        return False, f"not canonical JSON: {error}"
    if actual != claimed:
        return False, f"digest mismatch: file says {claimed}, contents give {actual}"
    return True, f"digest recomputes ({claimed})"


def check_plan(run: dict[str, Any], computed: str | Exception) -> tuple[bool | None, str]:
    """``(None, reason)`` means UNVERIFIED."""
    if isinstance(computed, PrivateUnavailable):
        return None, str(computed)
    if isinstance(computed, Exception):
        return False, f"could not recompute the plan digest: {computed}"
    if run.get("plan_digest") != computed:
        return False, f"attested {run.get('plan_digest')}, recomputed {computed}"
    return True, f"plan digest recomputes ({computed})"


def check_validator(run: dict[str, Any],
                    computed: dict[tuple[int, str], str | Exception]
                    ) -> tuple[bool | None, str]:
    """``(None, reason)`` means UNVERIFIED."""
    seed, stamp = run.get("validator_seed"), run.get("validator_timestamp")
    if not (_is_int(seed) and isinstance(stamp, str)):
        return False, (f"malformed validator seed/timestamp: seed {seed!r} must be an integer "
                       f"and timestamp {stamp!r} a string")
    key = (seed, stamp)
    value = computed.get(key)
    if value is None:
        return False, f"no recomputation for seed/timestamp {key}"
    if isinstance(value, PrivateUnavailable):
        return None, str(value)
    if isinstance(value, Exception):
        return False, f"could not recompute the validator digest: {value}"
    if run.get("validator_pinned_digest") != value:
        return False, f"attested {run.get('validator_pinned_digest')}, recomputed {value}"
    return True, f"validator pinned digest recomputes (seed {key[0]}, {key[1]}; {value})"


PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"
EXIT_PASS, EXIT_FAIL, EXIT_UNVERIFIED = 0, 1, 3  # 2 is left to argparse (usage errors)


def worst(verdicts: list[str]) -> str:
    """FAIL if any FAIL; else UNVERIFIED if any UNVERIFIED; else PASS (PASS only if all PASS)."""
    if FAIL in verdicts:
        return FAIL
    return UNVERIFIED if UNVERIFIED in verdicts else PASS


def tally(verdicts: list[str]) -> dict[str, int]:
    return {PASS: verdicts.count(PASS), FAIL: verdicts.count(FAIL),
            UNVERIFIED: verdicts.count(UNVERIFIED)}


def _check(ok: bool | None, detail: str) -> dict[str, Any]:
    if ok is None:
        return {"verdict": UNVERIFIED, "ok": False, "detail": f"UNVERIFIED: {detail}"}
    return {"verdict": PASS if ok else FAIL, "ok": ok, "detail": detail}


def check_chain(run: dict[str, Any], client: Any) -> dict[str, Any]:
    """The chain corroboration of one run at ITS OWN block: PASS, FAIL or UNVERIFIED.

    UNVERIFIED means the node could not serve the state at that block. The current-state read
    that follows is shown as ``supplementary`` information only; it never makes a run PASS."""
    included, start, end = run.get("included_block"), run.get("window_start"), \
        run.get("window_end")
    row = run.get("row")
    if not (_is_int(included) and _is_int(start) and _is_int(end)
            and isinstance(row, dict) and "dests" in row and "weights" in row):
        return {**_check(False, "malformed run: block, window or row missing"),
                "supplementary": None}
    if not start <= included <= end:
        return {**_check(False, f"included block {included} is outside the window "
                                f"{start}-{end}"), "supplementary": None}
    try:
        at_block = client.weight_row(NETUID, MECID, VALIDATOR_UID, at_block=included)
        last_at = client.last_weights_block(NETUID, VALIDATOR_UID, at_block=included)
        last_before = client.last_weights_block(NETUID, VALIDATOR_UID, at_block=included - 1)
    except Exception as error:  # noqa: BLE001 - any failure here means history is unavailable
        historical_error = f"{type(error).__name__}: {error}" if str(error) \
            else type(error).__name__
    else:
        if at_block != row:
            return {**_check(False, f"uid {VALIDATOR_UID} row at block {included} is "
                                    f"{at_block}, attested {row}"), "supplementary": None}
        if last_at != included:
            return {**_check(False, f"uid {VALIDATOR_UID} LastUpdate at block {included} is "
                                    f"{last_at}, not {included}: no weights extrinsic from "
                                    f"uid {VALIDATOR_UID} landed in that block"),
                    "supplementary": None}
        if not last_before < included:
            return {**_check(False, f"uid {VALIDATOR_UID} LastUpdate at block {included - 1} "
                                    f"is {last_before}, not before {included}"),
                    "supplementary": None}
        return {**_check(True, f"uid {VALIDATOR_UID} set weights in exactly block {included} "
                               f"(LastUpdate {last_before} at block {included - 1}, {last_at} "
                               f"at block {included}) and the row at block {included} equals "
                               f"the attested row; block is inside the window {start}-{end}"),
                "supplementary": None}
    # The node cannot serve state at the run's own block: UNVERIFIED. Current state is read only
    # to give the reader context; it proves nothing about block N and never yields a PASS.
    try:
        last = client.last_weights_block(NETUID, VALIDATOR_UID)
        current = client.weight_row(NETUID, MECID, VALIDATOR_UID)
    except Exception as error:  # noqa: BLE001
        supplementary = f"current-state read also failed ({type(error).__name__})"
    else:
        consistent = last >= included and current == row
        supplementary = (f"current state, not proof: last weights block {last}, current row "
                         f"{'equals' if current == row else 'differs from'} the attested row"
                         f"{'' if consistent else ' (INCONSISTENT with the attestation)'}")
    detail = (f"UNVERIFIED: the node could not serve state at block {included} "
              f"({historical_error}), so this run is not corroborated at its own block")
    return {"verdict": UNVERIFIED, "ok": False, "detail": detail, "supplementary": supplementary}


# --------------------------------------------------------------------------------------- run
def verify(doc: Any, *, client: Any | None = None,
           chain_client: Callable[[], Any] | None = None,
           plan_digest_fn: Callable[[], str] = compute_plan_digest,
           validator_digest_fn: Callable[[int, str], str] = compute_validator_digest,
           ) -> dict[str, Any]:
    """The full report as plain data. ``chain_client`` is called lazily, at most once.

    Two sections: ``offline`` (file integrity, plan digest and validator digest recomputation,
    no chain) and ``chain`` (the per-block chain reads), each with its own tally and verdict.
    ``verdict`` is the overall PASS, FAIL or UNVERIFIED and ``ok`` is true only for PASS."""
    ok, detail = check_integrity(doc)
    report: dict[str, Any] = {"integrity": {"verdict": PASS if ok else FAIL, "ok": ok,
                                            "detail": detail}, "runs": []}
    runs = doc.get("runs") if isinstance(doc, dict) else None
    if not isinstance(runs, list) or not runs:
        report["integrity"] = {"verdict": FAIL, "ok": False,
                               "detail": detail + "; the file has no runs" if ok else detail}
        report["offline"] = {"verdict": FAIL, "tally": tally([FAIL])}
        report["chain"] = {"verdict": UNVERIFIED, "tally": tally([])}
        report["scoring"] = {"verdict": UNVERIFIED, "tally": tally([])}
        report["verdict"], report["ok"] = FAIL, False
        return report
    runs = [r if isinstance(r, dict) else {} for r in runs]

    try:
        plan: str | Exception = plan_digest_fn()
    except Exception as error:  # noqa: BLE001
        plan = error
    validators: dict[tuple[int, str], str | Exception] = {}
    for run in runs:
        key = (run.get("validator_seed"), run.get("validator_timestamp"))
        if _is_int(key[0]) and isinstance(key[1], str) and key not in validators:
            try:
                validators[key] = validator_digest_fn(*key)
            except Exception as error:  # noqa: BLE001
                validators[key] = error
    chain: Any = client
    chain_error: Exception | None = None
    if chain is None and chain_client is not None:
        try:
            chain = chain_client()
        except Exception as error:  # noqa: BLE001
            chain_error = error

    for run in runs:
        checks: dict[str, dict[str, Any]] = {}
        if chain is None:
            why = f"{type(chain_error).__name__}: {chain_error}" if chain_error else "none given"
            checks["chain"] = {"verdict": UNVERIFIED, "ok": False, "supplementary": None,
                               "detail": f"UNVERIFIED: no chain client ({why})"}
        else:
            checks["chain"] = check_chain(run, chain)
        checks["plan"] = _check(*check_plan(run, plan))
        checks["validator"] = _check(*check_validator(run, validators))
        verdict = worst([c["verdict"] for c in checks.values()])
        report["runs"].append({
            "run_id": run.get("run_id"), "confirm_seq": run.get("confirm_seq"),
            "included_block": run.get("included_block"), "checks": checks,
            "verdict": verdict, "ok": verdict == PASS})
    offline = [report["integrity"]["verdict"]] + [
        r["checks"][n]["verdict"] for r in report["runs"] for n in ("plan", "validator")]
    chain_verdicts = [r["checks"]["chain"]["verdict"] for r in report["runs"]]
    scoring = [r["checks"][n]["verdict"] for r in report["runs"] for n in ("plan", "validator")]
    report["offline"] = {"verdict": worst(offline), "tally": tally(offline)}
    report["scoring"] = {"verdict": worst(scoring), "tally": tally(scoring)}
    report["chain"] = {"verdict": worst(chain_verdicts), "tally": tally(chain_verdicts)}
    report["verdict"] = worst([report["offline"]["verdict"], report["chain"]["verdict"]])
    report["ok"] = report["verdict"] == PASS
    return report


def wallet_state() -> dict[str, Any]:
    loaded = sorted(name for name in WALLET_MODULES if name in sys.modules)
    return {"our_wallet_code_loaded": any(n in loaded for n in ("flip_wallet", "flip_runlive")),
            "wallet_modules_loaded": loaded}


def summary_line(report: dict[str, Any]) -> str:
    """One honest line: what was checked on chain and what could not be checked."""
    n = len(report["runs"])
    ct, st = report["chain"]["tally"], report["scoring"]["tally"]
    chain = f"chain: {ct[PASS]}/{n} PASS"
    if ct[FAIL]:
        chain += f", {ct[FAIL]} FAIL"
    if ct[UNVERIFIED]:
        chain += f", {ct[UNVERIFIED]} UNVERIFIED"
    total = sum(st.values())
    reasons = {c["detail"].removeprefix("UNVERIFIED: ") for r in report["runs"]
               for name, c in r["checks"].items()
               if name in ("plan", "validator") and c["verdict"] == UNVERIFIED}
    if total and st[UNVERIFIED] == total and len(reasons) == 1:
        scoring = (f"scoring: not verifiable outside Provenonce (plan and validator "
                   f"UNVERIFIED: {reasons.pop()})")
    else:
        scoring = f"scoring: {st[PASS]}/{total} PASS (plan and validator recomputed)"
        if st[FAIL]:
            scoring += f", {st[FAIL]} FAIL"
        if st[UNVERIFIED]:
            scoring += f", {st[UNVERIFIED]} UNVERIFIED"
    return f"SUMMARY integrity: {report['integrity']['verdict']}; {chain}; {scoring}"


def render(report: dict[str, Any]) -> str:
    runs = report["runs"]
    n = len(runs)
    off, chn = report["offline"], report["chain"]
    lines = ["SN87 testnet attestation verification (read only: no key, no chain write)", "",
             "== 1. OFFLINE REPRODUCTION (file integrity; plan and validator digest "
             "recomputation where the private reference executors are present; no chain "
             "read) =="]
    i = report["integrity"]
    lines.append(f"integrity  {i['verdict']}  {i['detail']}")
    for run in runs:
        lines.append(f"run {run['run_id']}  CONFIRM seq {run['confirm_seq']}")
        for name in ("plan", "validator"):
            c = run["checks"][name]
            lines.append(f"  {name:<10} {c['verdict']}  {c['detail']}")
    t = off["tally"]
    unver = f" / {t[UNVERIFIED]} UNVERIFIED" if t[UNVERIFIED] else ""
    lines.append(f"reproduces offline: {off['verdict']}  ({t[PASS]} PASS / {t[FAIL]} FAIL{unver} "
                 f"of {sum(t.values())} checks: integrity + plan and validator for {n} runs)")
    lines += ["", "== 2. CHAIN CORROBORATION (each run read at its own block on testnet 582) =="]
    for run in runs:
        c = run["checks"]["chain"]
        lines.append(f"run {run['run_id']}  block {run['included_block']}  {c['verdict']}  "
                     f"{c['detail']}")
        if c.get("supplementary"):
            lines.append(f"    supplementary ({c['supplementary']})")
    t = chn["tally"]
    lines.append(f"chain corroboration: {chn['verdict']}  ({t[PASS]} PASS / {t[FAIL]} FAIL / "
                 f"{t[UNVERIFIED]} UNVERIFIED of {n} runs)")
    lines += ["", "== PER-RUN VERDICT (FAIL if any check fails, else UNVERIFIED if any is, "
              "else PASS) =="]
    for run in runs:
        lines.append(f"run {run['run_id']}  block {run['included_block']}  {run['verdict']}")
    counts = tally([r["verdict"] for r in runs])
    extra = "" if i["ok"] else ", file integrity FAILED"
    if report.get("wallet_state", {}).get("our_wallet_code_loaded"):
        extra += ", key-handling code was loaded"
    lines.append(f"OVERALL {report['verdict']}: {counts[PASS]}/{n} runs PASS, "
                 f"{counts[FAIL]} FAIL, {counts[UNVERIFIED]} UNVERIFIED{extra}")
    lines.append(summary_line(report))
    lines.append(f"exit code {exit_code(report['verdict'])} (0 = PASS, 1 = FAIL, 3 = UNVERIFIED)")
    return "\n".join(lines)


def exit_code(verdict: str) -> int:
    return {PASS: EXIT_PASS, UNVERIFIED: EXIT_UNVERIFIED}.get(verdict, EXIT_FAIL)


def main(argv: list[str] | None = None, *,
         chain_client: Callable[[], Any] | None = None,
         plan_digest_fn: Callable[[], str] = compute_plan_digest,
         validator_digest_fn: Callable[[int, str], str] = compute_validator_digest) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--attestation", type=Path, default=DEFAULT_ATTESTATION)
    parser.add_argument("--fake-home", type=Path,
                        help="scratch HOME for the SDK (default: a fresh temporary directory)")
    parser.add_argument("--endpoint", default=None,
                        help="testnet node to read (default: the public node in chain_read); "
                             "it must serve the testnet genesis")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    holder = isolate_home(args.fake_home)
    try:
        try:
            doc = json.loads(args.attestation.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"cannot read {args.attestation}: {error}", file=sys.stderr)
            doc = None
        report = verify(doc, chain_client=chain_client or (lambda: make_read_client(args.endpoint)),
                        plan_digest_fn=plan_digest_fn, validator_digest_fn=validator_digest_fn)
        report["wallet_state"] = wallet_state()
        if report["wallet_state"]["our_wallet_code_loaded"]:
            report["ok"], report["verdict"] = False, FAIL
        print(json.dumps(report, indent=2, sort_keys=True) if args.json else render(report))
    finally:
        if holder is not None:
            holder.cleanup()
    return exit_code(report["verdict"])


if __name__ == "__main__":
    raise SystemExit(main())
