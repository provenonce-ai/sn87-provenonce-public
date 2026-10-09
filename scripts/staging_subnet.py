#!/usr/bin/env python3
"""Local staging subnet harness: ONE validator, TWO miners, in-process.

  uv run python scripts/staging_subnet.py --out <dir> [--seed N] [--timestamp ISO8601Z]

LOCAL STAGING, FICTIONAL FIXTURES, NO CHAIN, NOT AN INCENTIVE-BEARING RESULT.

Truth: the private tree computes per-case truth with the reference executor. Anywhere, ``--truth
golden`` (or ``run_staging(truth_for=...)``) takes it from the published golden vectors under
``protocol/golden_truth`` instead; the receipt's pinned digest is the same either way.

Flow: compile the CMT (``cmt.compile_cmt``) and verify its commitment; the validator derives
challenge instances for that CMT from the public FICTIONAL generator the CMT names
(``institutional_v02.fixtures.build_case``); each instance is sent as canonical bytes to two
miners (miner A: the replaceable candidate ``miners.witness_ic.approval_witness``; miner B:
the public-contract baseline algorithm run as a miner); returns are collected and scored by
the EXISTING scorer (``bundle.evaluate`` over the committed profile); the existing preference
row feeds the dry-run quantizer (``sn87_provenonce.weights_dry_run.dry_run``) to produce u16
weights. Nothing is signed, submitted, or sent: no wallet, no keys, no chain, no network (a
guard turns any non-loopback socket use into a hard failure). No new scoring logic, no profile
change. The transport is an in-process byte boundary, not ``runtime.local``: the CMT binds the
``institution/0.2`` contract, while the ``runtime`` seams carry the unbound v0alpha1 models
(see the CMT compatibility report, V0ALPHA1_MODELS_NOT_BOUND).

The receipt (JSON and Markdown) has a ``pinned`` section, fully determined by (seed, timestamp,
committed code), whose ``pinned_digest`` tests can pin; timings, versions and git identity sit
in ``volatile`` and are excluded from the digest.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import platform
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Imports that may pull in heavy dependencies happen before any network guard is installed.
from sn87_provenonce import bundle, miners  # noqa: E402
from sn87_provenonce.baselines import BASELINES  # noqa: E402
from sn87_provenonce.canonical import canonical_bytes, parse_canonical  # noqa: E402
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY  # noqa: E402
from sn87_provenonce.cmt import (  # noqa: E402
    CompiledCMT,
    cmt_canonical_bytes,
    cmt_commitment,
    compile_cmt,
    compiled_bytes,
    verify_cmt,
)
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable  # noqa: E402
from sn87_provenonce.scoring import Integrity, wire  # noqa: E402
from sn87_provenonce.weights_dry_run import TESTNET_GENESIS, dry_run  # noqa: E402

SCHEMA = "sn87-staging-run-receipt/0.1"
LABEL = ("LOCAL STAGING, FICTIONAL FIXTURES, NO CHAIN, "
         "NOT AN INCENTIVE-BEARING RESULT")
DEFAULT_TIMESTAMP = "2026-10-04T00:00:00Z"
CANDIDATE = "approval_witness"
BASELINE_MINER = "baseline_miner"
# Fictional placeholders. Not keys, not chain identities; they exist only to label rows.
VALIDATOR_PLACEHOLDER = {"uid": 0, "hotkey": "FICTIONAL-PLACEHOLDER-VALIDATOR"}
MINER_PLACEHOLDERS = {
    CANDIDATE: {"uid": 1, "hotkey": "FICTIONAL-PLACEHOLDER-MINER-A",
                "description": "candidate: miners.witness_ic.approval_witness"},
    BASELINE_MINER: {"uid": 2, "hotkey": "FICTIONAL-PLACEHOLDER-MINER-B",
                     "description": "baseline algorithm (baselines.ic_approval_applicability) "
                                    "run as a miner"},
}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class StagingError(RuntimeError):
    """The staging run failed closed; no receipt is written."""


class NetworkBlocked(BaseException):  # not an Exception: a miner cannot swallow it
    """A non-loopback socket operation was attempted during the staging run."""


# --------------------------------------------------------------------------- network guard
@contextlib.contextmanager
def no_network():
    """Fail any socket connect or name resolution that is not loopback; log attempts."""
    attempts: list[str] = []
    originals = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)

    def host_of(address: Any) -> str:
        return str(address[0]) if isinstance(address, tuple) and address else str(address)

    def check(address: Any) -> None:
        host = host_of(address)
        if host not in LOOPBACK and not host.startswith("127."):
            attempts.append(host)
            raise NetworkBlocked(f"NETWORK_FORBIDDEN_IN_STAGING: {host}")

    def connect(self, address):
        check(address)
        return originals[0](self, address)

    def connect_ex(self, address):
        check(address)
        return originals[1](self, address)

    def getaddrinfo(host, *args, **kwargs):
        check((host,))
        return originals[2](host, *args, **kwargs)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    socket.getaddrinfo = getaddrinfo
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = originals


# --------------------------------------------------------------------------------- helpers
def digest(value: Any) -> str:
    return bundle.sha256(value)


def _stage(timings: dict[str, float], name: str):
    class Timer:
        def __enter__(self):
            self.t = time.perf_counter()

        def __exit__(self, *exc):
            timings[name] = round((time.perf_counter() - self.t) * 1000, 3)
    return Timer()


def verify_compiled(compiled: CompiledCMT, binding=IC_APPROVAL_APPLICABILITY) -> str:
    """Fail closed unless the CMT bytes reproduce their commitment and bind the real profile."""
    manifest = compiled.manifest
    commitment = compiled.compatibility.manifest_commitment
    try:
        verify_cmt(cmt_canonical_bytes(manifest), commitment)
    except ValueError as error:
        raise StagingError(f"CMT_HASH_VERIFICATION_FAILED: {error}") from error
    if cmt_commitment(manifest) != commitment:
        raise StagingError("CMT_HASH_VERIFICATION_FAILED: commitment mismatch")
    if manifest.evaluation.profile_commitment != binding.profile.commitment:
        raise StagingError("CMT_PROFILE_COMMITMENT_MISMATCH")
    if manifest.identity.class_id != binding.class_id:
        raise StagingError("CMT_CLASS_MISMATCH")
    return commitment


def derive_instances(compiled: CompiledCMT, seed: int, binding=IC_APPROVAL_APPLICABILITY,
                     truth_for: Callable[[dict[str, Any]], dict[str, Any]] | None = None
                     ) -> list[dict[str, Any]]:
    """Validator: the profile's assignment from the generator the CMT names (fictional).

    Truth comes from ``truth_for(capsule)`` when given (for example the published golden
    vectors, ``golden_truth.GoldenTruth.truth_for``), else from the binding's reference
    executor, which only the Provenonce-private tree has."""
    truth_of = truth_for or binding.reference
    renewal = compiled.manifest.renewal
    if renewal.generator_reference != "sn87_provenonce.institutional_v02.fixtures.build_case":
        raise StagingError("CMT_GENERATOR_NOT_THE_FICTIONAL_FIXTURE")
    document = binding.profile.document
    plan = [(family, "scored") for family, n in document["assignment"].items()
            for _ in range(n)]
    plan += [(family, "diagnostic") for family, n in document["diagnostics"].items()
             for _ in range(n)]
    cases = []
    for index, (family, track) in enumerate(plan):
        capsule = binding.generate(family, seed * 1000 + index)
        if capsule["policy"]["grammar"] != renewal.generator_version:
            raise StagingError("CMT_GRAMMAR_MISMATCH")
        cases.append({"qid": capsule["qid"], "track": track, "family": family,
                      "capsule": capsule, "truth": truth_of(capsule)})
    return cases


def _miner_call(method, request: bytes, *, pure: bool) -> tuple[bytes | None, bool]:
    """The miner side of the byte boundary: sees only the public canonical capsule."""
    try:
        response = method(parse_canonical(request))
        return canonical_bytes(response), False
    except Exception:  # noqa: BLE001 - a miner-owned method's failure is its own zero
        if not pure:
            raise
        return None, True


def collect(cases: list[dict[str, Any]], methods: dict[str, Any], timings: dict[str, float]
            ) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, list[bytes | None]]]:
    """Send every instance to every miner; return bundle observations and raw return bytes."""
    observations: dict[str, dict[str, dict[str, Any]]] = {}
    raw: dict[str, list[bytes | None]] = {}
    for method_id, method in methods.items():
        observations[method_id], raw[method_id] = {}, []
        started = time.perf_counter()
        for case in cases:
            request = canonical_bytes(case["capsule"])  # the public view, as on a wire
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            returned, raised = _miner_call(method, request, pure=True)
            wall, cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
            response = None if returned is None else parse_canonical(returned)
            measured = {"wall_time": (wall / 1e6, "perf_counter_ns"),
                        "cpu_time": (cpu / 1e6, "process_time_ns"),
                        "bytes_in": (float(len(request)), "canonical_capsule_bytes")}
            missing = {"model_tokens": "NOT_APPLICABLE_DETERMINISTIC_METHOD",
                       "oracle_time": "NOT_APPLICABLE_CANDIDATE_USES_NO_ORACLE"}
            if returned is not None:
                measured["bytes_out"] = (float(len(returned)), "canonical_response_bytes")
            else:
                missing["bytes_out"] = ("NO_RESPONSE_METHOD_RAISED" if raised
                                        else "NO_RESPONSE_METHOD_RETURNED_NONE")
            observations[method_id][case["qid"]] = {
                "response": response,
                "integrity": Integrity(response is not None, True, True, True, True, True),
                "cost": bundle.cost_record(measured, missing)}
            raw[method_id].append(returned)
        timings[f"dispatch_{method_id}"] = round((time.perf_counter() - started) * 1000, 3)
    return observations, raw


def staging_binding(methods: dict[str, Any]):
    """The IC class with exactly the two staged miners as participants (both 'candidate')."""
    if len(methods) != 2 or bundle.BASELINE in methods:
        raise StagingError("EXACTLY_TWO_MINERS_REQUIRED")
    return replace(IC_APPROVAL_APPLICABILITY, candidates=dict(methods),
                   roles=dict.fromkeys(methods, "candidate"))


def fictional_target(uids: list[int]) -> dict[str, Any]:
    """A placeholder target for the dry-run quantizer's checks. It names no real chain state."""
    return {"network": "test", "genesis": TESTNET_GENESIS, "sdk_version": "11.1.0",
            "netuid": 87, "block": 1000, "spec_version": 471, "version_key": 0,
            "min_allowed_weights": 1, "max_weights_limit": 65535,
            "validator_uid": VALIDATOR_PLACEHOLDER["uid"], "rate_limit_blocks": 100,
            "last_update_block": 0, "registered": True, "validator_permit": True,
            "active": True, "commit_reveal": False,
            "FICTIONAL_PLACEHOLDER_NOT_A_CHAIN_READ": True, "miner_uids": sorted(uids)}


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], capture_output=True, cwd=ROOT, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return out.stdout.decode().strip() if out.returncode == 0 else "UNKNOWN"


def tool_versions() -> dict[str, str]:
    def version(name: str) -> str:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return "UNKNOWN"
    return {"python": platform.python_version(), "platform": platform.platform(),
            "sn87_provenonce": version("sn87-provenonce"), "bittensor": version("bittensor"),
            "pydantic": version("pydantic"), "uv_lock_sha256": "sha256:" + hashlib.sha256(
                (ROOT / "uv.lock").read_bytes()).hexdigest()}


# ------------------------------------------------------------------------------- the run
def run_staging(*, seed: int = 0, timestamp: str = DEFAULT_TIMESTAMP,
                compiled: CompiledCMT | None = None,
                methods: dict[str, Any] | None = None,
                truth_for: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                truth_source: str = "reference executor") -> dict[str, Any]:
    """Run the staging subnet once and return the receipt. Writes nothing; touches no network.

    ``truth_for`` and ``truth_source`` select where per-case truth comes from (see
    ``derive_instances``). The pinned digest does not depend on the source, only on the truth
    values; the source is recorded in ``volatile`` so a reader can see which one was used."""
    timings: dict[str, float] = {}
    started = time.perf_counter()
    with no_network() as attempts:
        with _stage(timings, "compile_cmt"):
            compiled = compiled or compile_cmt()
        with _stage(timings, "verify_cmt"):
            cmt_hash = verify_compiled(compiled)
        with _stage(timings, "derive_instances"):
            cases = derive_instances(compiled, seed, truth_for=truth_for)
        miner_methods = methods or {
            CANDIDATE: miners.for_class(IC_APPROVAL_APPLICABILITY.class_id)[CANDIDATE],
            BASELINE_MINER: BASELINES[IC_APPROVAL_APPLICABILITY.class_id]}
        binding = staging_binding(miner_methods)
        with _stage(timings, "dispatch_and_collect"):
            observations, raw = collect(cases, miner_methods, timings)
        with _stage(timings, "score"):
            result = bundle.evaluate(
                binding, cases, observations, mode="FIXTURE", run_id=f"staging-seed-{seed}",
                profile_commitment=binding.profile.commitment,
                window={"opened_at": timestamp, "closed_at": timestamp},
                source_digest=digest([c["capsule"]["evidence_commitment"] for c in cases]),
                per_case=True)
        with _stage(timings, "quantize_weights"):
            uids = {m: MINER_PLACEHOLDERS[m]["uid"] for m in miner_methods}
            row = result["row"]
            rows = [] if row["weights"] is None else [
                {"uid": uids[m], "weight": row["weights"][m]} for m in miner_methods]
            target = fictional_target(list(uids.values()))
            quantized = dry_run({"target": target, "weights": rows})
    if attempts:
        raise StagingError("NETWORK_ATTEMPTED")
    timings["total"] = round((time.perf_counter() - started) * 1000, 3)
    receipt = build_receipt(seed, timestamp, compiled, cmt_hash, cases, miner_methods, raw,
                            result, row, uids, quantized)
    receipt["volatile"] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timings_ms": timings, "tool_versions": tool_versions(),
        "git": {"core_commit": _git("rev-parse", "HEAD"),
                "core_tree": _git("rev-parse", "HEAD^{tree}"),
                "worktree": "DIRTY" if _git("status", "--porcelain") not in ("", "UNKNOWN")
                else "CLEAN",
                },
        "truth_source": truth_source,
        "command": "python scripts/staging_subnet.py --out <dir>",
        "network_attempts": len(attempts)}
    return receipt


def build_receipt(seed, timestamp, compiled, cmt_hash, cases, methods, raw, result, row, uids,
                  quantized) -> dict[str, Any]:
    per_case = {c["qid"]: c for c in result["cases"]}
    miners_out = []
    for method_id in methods:
        returns = []
        for case, data in zip(cases, raw[method_id], strict=True):
            response = None if data is None else parse_canonical(data)
            returns.append({
                "qid": case["qid"], "family": case["family"], "track": case["track"],
                "response_sha256": "sha256:" + hashlib.sha256(data).hexdigest()
                if data is not None else None,
                "state": "NO_RESPONSE" if response is None else response["state"],
                "finding_codes": [] if response is None
                else sorted(f["code"] for f in response["findings"]),
                "score": per_case[case["qid"]]["methods"][method_id]["score"],
                "valid": per_case[case["qid"]]["methods"][method_id]["valid"]})
        states: dict[str, int] = {}
        for r in returns:
            states[r["state"]] = states.get(r["state"], 0) + 1
        miners_out.append({
            "method_id": method_id, **MINER_PLACEHOLDERS[method_id],
            "placeholder_label": "FICTIONAL PLACEHOLDER, NOT A KEY OR CHAIN IDENTITY",
            "returns_summary": {"n": len(returns), "states": dict(sorted(states.items()))},
            "returns_digest": digest([r["response_sha256"] for r in returns]),
            "returns": returns})
    comparison = result["comparison"]
    candidate_cmp = comparison.get(CANDIDATE) or next(iter(comparison.values()))
    scores = result["scores"]
    pinned = wire({
        "schema_version": SCHEMA, "label": LABEL,
        "labels": ["LOCAL STAGING", "FICTIONAL FIXTURES", "NO CHAIN",
                   "NOT AN INCENTIVE-BEARING RESULT"],
        "inputs": {"seed": seed, "timestamp": timestamp,
                   "class_id": IC_APPROVAL_APPLICABILITY.class_id,
                   "profile_id": result["manifest"]["profile_id"],
                   "profile_commitment": result["manifest"]["profile_commitment"],
                   "cmt_commitment": cmt_hash, "cmt_commitment_domain": "SN87:CMT:gra/0.1",
                   "cmt_verified": True,
                   "compiled_cmt_sha256": "sha256:" + hashlib.sha256(
                       compiled_bytes(compiled)).hexdigest(),
                   "cmt_adoption_status": compiled.manifest.adoption_status},
        "validator": {**VALIDATOR_PLACEHOLDER,
                      "placeholder_label": "FICTIONAL PLACEHOLDER, NOT A KEY OR CHAIN IDENTITY",
                      "instances": [{"qid": c["qid"], "family": c["family"],
                                     "track": c["track"],
                                     "capsule_commitment": c["capsule"]["evidence_commitment"]}
                                    for c in cases]},
        "miners": miners_out,
        "per_case_scores": [{"qid": c["qid"], "track": c["track"], "family": c["family"],
                             "methods": c["methods"]} for c in result["cases"]],
        "aggregates": {"scores": scores, "diagnostics": result["diagnostics"],
                       "comparison_to_baseline": comparison,
                       "baseline_method": bundle.BASELINE},
        "weights": {
            "preference_row_state": row["state"],
            "weights_float_strings_binary64_17g": row["weights"],
            "chain_dry_run_state": quantized["state"],
            "uids": quantized["uids"], "u16_weights": quantized["u16_weights"],
            "u16_sum": sum(quantized["u16_weights"]),
            "dry_run_input_sha256": quantized["input_sha256"],
            "broadcast": quantized["broadcast"],
            "target": quantized["target"],
            "target_label": "FICTIONAL PLACEHOLDER TARGET; NO CHAIN READ OR WRITE",
            "uid_to_method": {str(MINER_PLACEHOLDERS[m]["uid"]): m for m in methods}},
        "headline": {
            "candidate_estimate": scores[CANDIDATE]["estimate"] if CANDIDATE in scores else "NA",
            "baseline_estimate": scores[bundle.BASELINE]["estimate"],
            "candidate_vs_baseline": candidate_cmp["result"],
            "estimate_delta": candidate_cmp["estimate_delta"]},
        "not_claimed": ["no chain read or write", "no network", "no wallet or key",
                        "fictional fixtures only", "integrity predicates asserted in-process",
                        "not an incentive-bearing result", "not a performance claim",
                        "CMT v0.1 is a candidate schema, not adopted"],
    })
    return {"schema_version": SCHEMA, "pinned": pinned, "pinned_digest": digest(pinned)}


def render_markdown(receipt: dict[str, Any]) -> str:
    p, v = receipt["pinned"], receipt["volatile"]
    w, h = p["weights"], p["headline"]
    lines = ["# Staging run receipt", "", f"**{LABEL}**", "",
             f"- Pinned digest: `{receipt['pinned_digest']}`",
             f"- CMT commitment: `{p['inputs']['cmt_commitment']}` (verified: "
             f"{p['inputs']['cmt_verified']}; candidate schema, not adopted)",
             f"- Profile: `{p['inputs']['profile_id']}` `{p['inputs']['profile_commitment']}`",
             f"- Seed {p['inputs']['seed']}, timestamp {p['inputs']['timestamp']}, "
             f"generated {v['generated_at']}",
             f"- Core commit `{v['git']['core_commit']}` ({v['git']['worktree']})", "",
             "## Headline", "",
             f"- Candidate estimate: {h['candidate_estimate']}; baseline estimate: "
             f"{h['baseline_estimate']}; delta {h['estimate_delta']}",
             f"- Candidate vs baseline: **{h['candidate_vs_baseline']}** (null results are "
             "kept; no headroom is manufactured)", "", "## Weights", "",
             f"- Preference row: {w['preference_row_state']}; dry-run: "
             f"{w['chain_dry_run_state']}; broadcast: {w['broadcast']}",
             "", "| Miner | Placeholder uid | Weight (float string) | u16 |", "|---|---|---|---|"]
    u16 = dict(zip(w["uids"], w["u16_weights"], strict=True))
    floats = w["weights_float_strings_binary64_17g"] or {}
    for m in p["miners"]:
        lines.append(f"| {m['method_id']} ({m['hotkey']}) | {m['uid']} | "
                     f"{floats.get(m['method_id'], 'none')} | {u16.get(m['uid'], 0)} |")
    lines += ["", f"u16 sum: {w['u16_sum']}", "", "## Miner returns", "",
              "| Miner | Returns | States | Returns digest |", "|---|---|---|---|"]
    for m in p["miners"]:
        lines.append(f"| {m['method_id']} | {m['returns_summary']['n']} | "
                     f"{m['returns_summary']['states']} | `{m['returns_digest']}` |")
    lines += ["", "## Aggregates", "", "| Method | Admitted | Evaluable | Estimate | Eligible |",
              "|---|---|---|---|---|"]
    for name, s in p["aggregates"]["scores"].items():
        lines.append(f"| {name} | {s['admitted']} | {s['evaluable']} | {s['estimate']} | "
                     f"{s['eligible']} |")
    lines += ["", "## Per-case scores", "", "| qid | track | family | "
              + " | ".join(m["method_id"] for m in p["miners"]) + " | baseline |",
              "|---|---|---|" + "---|" * (len(p["miners"]) + 1)]
    for c in p["per_case_scores"]:
        cells = [c["methods"][m["method_id"]]["score"] for m in p["miners"]]
        cells.append(c["methods"][bundle.BASELINE]["score"])
        lines.append(f"| {c['qid']} | {c['track']} | {c['family']} | "
                     + " | ".join(map(str, cells)) + " |")
    lines += ["", "## Timings (ms, not pinned)", ""]
    lines += [f"- {k}: {t}" for k, t in v["timings_ms"].items()]
    lines += ["", "## Tool versions", ""] + [f"- {k}: {t}" for k, t in v["tool_versions"].items()]
    lines += ["", "## Not claimed", ""] + [f"- {x}" for x in p["not_claimed"]]
    return "\n".join(lines) + "\n"


def write_receipts(receipt: dict[str, Any], out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / "STAGING_RUN_RECEIPT.json", out / "STAGING_RUN_RECEIPT.md"
    with json_path.open("x", encoding="utf-8") as handle:  # create-only: never overwrite
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with md_path.open("x", encoding="utf-8") as handle:
        handle.write(render_markdown(receipt))
    return json_path, md_path


def select_truth(choice: str) -> tuple[Callable[[dict[str, Any]], dict[str, Any]] | None, str]:
    """``(truth_for, label)`` for ``--truth``; ``(None, ...)`` means the reference executor."""
    if choice in ("auto", "executor"):
        try:
            IC_APPROVAL_APPLICABILITY.reference(
                IC_APPROVAL_APPLICABILITY.generate("fresh_review", 0))
            return None, "reference executor"
        except PrivateReferenceExecutorUnavailable:
            if choice == "executor":
                raise StagingError("REFERENCE_EXECUTOR_NOT_AVAILABLE") from None
    try:
        import golden_truth  # noqa: PLC0415 - sits beside this script

        store = golden_truth.load()
    except (golden_truth.GoldenTruthMissing, golden_truth.GoldenTruthInvalid) as error:
        raise StagingError(f"GOLDEN_TRUTH_UNAVAILABLE: {error}") from error
    return store.truth_for, f"published golden vectors ({store.describe()})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True,
                        help="output directory (created; files are create-only)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timestamp", default=DEFAULT_TIMESTAMP)
    parser.add_argument("--truth", choices=("auto", "executor", "golden"), default="auto",
                        help="per-case truth: the private reference executor, the published "
                             "golden vectors (protocol/golden_truth), or auto (the executor "
                             "when present, else the golden vectors)")
    args = parser.parse_args(argv)
    try:
        truth_for, truth_source = select_truth(args.truth)
        receipt = run_staging(seed=args.seed, timestamp=args.timestamp, truth_for=truth_for,
                              truth_source=truth_source)
    except StagingError as error:
        print(f"STAGING RUN FAILED: {error}", file=sys.stderr)
        return 1
    except LookupError as error:  # golden_truth.GoldenTruthMissing: no published truth
        print(f"STAGING RUN FAILED: NO_PUBLISHED_TRUTH_FOR_SEED_{args.seed}: {error}",
              file=sys.stderr)
        return 1
    json_path, md_path = write_receipts(receipt, args.out)
    h = receipt["pinned"]["headline"]
    print(LABEL)
    print("truth source:", truth_source)
    print(json_path, md_path)
    print("u16", dict(zip(receipt["pinned"]["weights"]["uids"],
                          receipt["pinned"]["weights"]["u16_weights"], strict=True)),
          h["candidate_vs_baseline"], receipt["pinned_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
