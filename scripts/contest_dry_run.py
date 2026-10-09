#!/usr/bin/env python3
"""End-to-end local dry run of one contest window: commit, open, miners, truth, results, reveal.

SHADOW TOOLING, LOCAL AND OFFLINE. No network, no chain, no key, no weight. Testnet 582 weights
are unchanged by anything this script does.

  uv run python scripts/contest_dry_run.py --out-dir NEW_DIR
         [--sizing-profile IC-FIRST-LIGHT-MIN-3] [--scoring-profile IC-FIRST-LIGHT-MIN-1]
         [--preset profile|messy] [--truth-source auto|reference|committed] [--timing]

Steps, each through the same code a real window uses (``contest_window.py`` phases, the miner
kit, the matched baseline, ``contest_results.py``):

1. commit: publish the seed and specification commitments, before the window opens;
2. open: generate the window's fresh capsules from the seed;
3. miners: the public candidate method (``approval_witness``) and the public-contract baseline
   answer the same capsules, in process, over canonical bytes;
4. truth: from the private reference executors (``--truth-source reference``) or, in a tree
   without them, from the committed truth of the demo window (``committed``). The demo window
   ``demo-0001`` uses a public demo seed, so its instances are public by construction and are
   never reused in a real window; the committed truth is checked against the regenerated
   instances before it is used;
5. results: the scores-only page, after the window closes (agreement, confusion and failure
   counts derive from truth and wait);
6. reveal and verify: the seed is published and every commitment is recomputed;
7. results-full and results-detail: truth-derived aggregates and per-case rows, which need the
   verified reveal and the explicit policy flag (the demo seed is public, so the flag is safe).

Output files are create-only and deterministic (no clock, no timing) unless ``--timing`` is given.
The default sizing profile has a window larger than the 12-case minimum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contest_results as cr  # noqa: E402
import contest_window as cw  # noqa: E402

from sn87_provenonce import miners  # noqa: E402
from sn87_provenonce.baselines import BASELINES  # noqa: E402
from sn87_provenonce.baselines import METHOD_ID as BASELINE  # noqa: E402
from sn87_provenonce.canonical import canonical_bytes, parse_canonical  # noqa: E402
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "examples" / "contest-window-demo"
DEMO_WINDOW = "demo-0001"
DEMO_OPENS, DEMO_CLOSES = "2026-10-20T00:00:00Z", "2026-10-21T00:00:00Z"
COMMIT_AT, REVEAL_AT = "2026-10-19T00:00:00Z", "2026-10-21T00:00:01Z"
# A public constant, not a secret: the demo window's seed is public by construction.
DEMO_MASTER_HEX = hashlib.sha256(b"sn87-contest-demo-master/v1").hexdigest()
# Fixed so the demo is byte-reproducible; a real window draws a random salt at truth time.
DEMO_TRUTH_SALT = hashlib.sha256(b"sn87-contest-demo-truth-salt/v1").hexdigest()[:32]
CLASS_ID = "IC-APPROVAL-APPLICABILITY"
CANDIDATE = "approval_witness"


def schedule_document(sizing_profile: str, preset: str) -> dict[str, Any]:
    return {"schema_version": cw.SCHEDULE_SCHEMA, "schedule_id": "demo-schedule-1",
            "profile_id": sizing_profile,
            "mix_preset": preset,
            "windows": [{"window_id": DEMO_WINDOW, "opens_at": DEMO_OPENS,
                         "closes_at": DEMO_CLOSES}]}


def answer(method, capsules: list[dict[str, Any]], timing: bool) -> dict[str, Any]:
    """Run a miner method on a fresh canonical copy of each capsule (the public view)."""
    out = {}
    for capsule in capsules:
        view = parse_canonical(canonical_bytes(capsule))
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        response = method(view)
        wall, cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
        entry: dict[str, Any] = {"response": response}
        if timing:  # volatile by nature: off by default so the output stays byte-deterministic
            entry["cost"] = {"wall_time": round(wall / 1e6, 3), "cpu_time": round(cpu / 1e6, 3)}
        out[capsule["qid"]] = entry
    return out


def responses_document(capsules: list[dict[str, Any]], timing: bool) -> dict[str, Any]:
    candidate = miners.for_class(CLASS_ID)[CANDIDATE]
    return {"schema_version": cr.RESPONSES_SCHEMA, "window_id": DEMO_WINDOW,
            "integrity_mode": "ASSERTED_FIXTURE",
            "methods": [
                {"method_id": CANDIDATE, "uid": None, "role": "candidate",
                 "responses": answer(candidate, capsules, timing)},
                {"method_id": BASELINE, "uid": None, "role": "baseline",
                 "responses": answer(BASELINES[CLASS_ID], capsules, timing)}]}


def _truth(entries: list[dict[str, Any]], source: str, row: dict[str, Any],
           cases_commitment: str) -> dict[str, Any]:
    if source in ("auto", "reference"):
        try:
            return cw.truth_document(DEMO_WINDOW, row["seed_commitment"], cases_commitment,
                                     DEMO_TRUTH_SALT, cw.derive_truth(entries))
        except PrivateReferenceExecutorUnavailable:
            if source == "reference":
                raise
    committed = json.loads((DEMO_DIR / f"window_{DEMO_WINDOW}.truth.json").read_text("utf-8"))
    # The committed truth must describe exactly the regenerated instances before it is used.
    if [(c["qid"], c["family"], c["track"], c["capsule_commitment"]) for c in committed["cases"]
            ] != [(e["qid"], e["family"], e["track"], e["capsule_commitment"]) for e in entries]:
        raise ValueError("COMMITTED_TRUTH_DOES_NOT_MATCH_THE_REGENERATED_WINDOW")
    cw.check_truth_document(committed)
    if (committed["seed_commitment"], committed["cases_commitment"]) != (
            row["seed_commitment"], cases_commitment):
        raise ValueError("COMMITTED_TRUTH_NOT_BOUND_TO_THIS_WINDOW")
    return committed


def dry_run(out: Path, *, sizing_profile: str, scoring_profile: str, preset: str,
            truth_source: str, timing: bool) -> dict[str, str]:
    """Run every step into ``out`` (must not exist); returns name -> path of the written files."""
    if out.exists():
        raise FileExistsError(f"{out} already exists")
    out.mkdir(parents=True)
    master_file = out / "private" / "master.hex"
    cw.write_new(master_file, DEMO_MASTER_HEX + "\n", mode=0o600)
    cw.write_new(out / "schedule.json", cw.dumps(schedule_document(sizing_profile, preset)))
    base = ["--schedule", str(out / "schedule.json"), "--master-seed-file", str(master_file),
            "--out-dir", str(out), "--demo",
            "--no-prior-ledger", "demo: a fresh directory with no earlier commitments"]
    written: dict[str, str] = {}

    def phase(name: str, at: str, *extra: str) -> None:
        args = cw.parser().parse_args(["--phase", name, "--now", at, *base, *extra])
        for path in cw.run(args):
            written[Path(path).name] = path

    phase("commit", COMMIT_AT)
    phase("open", DEMO_OPENS, "--window", DEMO_WINDOW)
    capsules_doc = json.loads((out / cw.names(DEMO_WINDOW)["capsules"]).read_text("utf-8"))
    cases_doc = json.loads((out / cw.names(DEMO_WINDOW)["cases"]).read_text("utf-8"))
    entries = [dict(row, capsule=c) for row, c in zip(
        cases_doc["cases"], capsules_doc["capsules"], strict=True)]
    # Miners see capsules only. Truth is derived after the answers are in.
    cw.write_new(out / f"window_{DEMO_WINDOW}.responses.json",
                 cw.dumps(responses_document(capsules_doc["capsules"], timing)))
    commitments = json.loads((out / "commitments.json").read_text("utf-8"))
    row = next(w for w in commitments["windows"] if w["window_id"] == DEMO_WINDOW)
    truth = _truth(entries, truth_source, row, capsules_doc["cases_commitment"])
    cw.write_new(out / cw.names(DEMO_WINDOW)["truth_private"], cw.dumps(truth), mode=0o600)
    common = ["--capsules", str(out / cw.names(DEMO_WINDOW)["capsules"]),
              "--truth", str(out / cw.names(DEMO_WINDOW)["truth_private"]),
              "--responses", str(out / f"window_{DEMO_WINDOW}.responses.json"),
              "--profile", scoring_profile, "--now", DEMO_CLOSES]
    for path in cr.run(_results_args(common, out / "results")):
        written["results/" + Path(path).name] = path
    phase("reveal", REVEAL_AT, "--window", DEMO_WINDOW)
    phase("verify", REVEAL_AT, "--window", DEMO_WINDOW)
    # Truth-derived aggregates need the verified reveal and the explicit policy flag. The demo
    # window has a public seed, so the flag is safe here; a real window waits for the decision.
    revealed = [*common, "--commitments", str(out / "commitments.json"),
                "--reveal", str(out / cw.names(DEMO_WINDOW)["reveal"]),
                "--publish-closed-window-truth"]
    for name, extra in (("results-full", []), ("results-detail", ["--include-case-detail"])):
        for path in cr.run(_results_args([*revealed, *extra], out / name)):
            written[name + "/" + Path(path).name] = path
    return written


def _results_args(argv: list[str], out_dir: Path) -> argparse.Namespace:
    return cr.parser().parse_args([*argv, "--out-dir", str(out_dir)])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out-dir", required=True, help="a new directory (must not exist)")
    p.add_argument("--sizing-profile", default="IC-FIRST-LIGHT-MIN-3",
                   help="profile that sizes the window (default %(default)s)")
    p.add_argument("--scoring-profile", default=None,
                   help="profile the results are scored under (default: the sizing profile)")
    p.add_argument("--preset", default="messy", choices=sorted(cw.PRESETS),
                   help="family mix (default %(default)s: wrong-scope and incomplete cases "
                   "in the scored track, a shadow experiment)")
    p.add_argument("--truth-source", default="auto", choices=("auto", "reference", "committed"))
    p.add_argument("--timing", action="store_true", help="record wall and CPU time (volatile)")
    args = p.parse_args(argv)
    try:
        written = dry_run(Path(args.out_dir), sizing_profile=args.sizing_profile,
                          scoring_profile=args.scoring_profile or args.sizing_profile,
                          preset=args.preset, truth_source=args.truth_source, timing=args.timing)
    except (cw.PhaseError, PrivateReferenceExecutorUnavailable, ValueError, FileExistsError,
            FileNotFoundError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for name in sorted(written):
        print(written[name])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
