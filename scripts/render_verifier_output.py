#!/usr/bin/env python3
"""Render the verifier output shown in the README, from a real run, and check it has not drifted.

  uv run --extra transport python scripts/render_verifier_output.py --write   # reads the chain
  uv run --extra transport python scripts/render_verifier_output.py --check   # offline
  uv run --extra transport python scripts/render_verifier_output.py           # print the block

The block is the trimmed output of ``scripts/verify_attestation.py`` on the default attestation,
as an outsider sees it: the validator check recomputes from the published truth, and the plan
check is treated as absent (Provenonce's private plan tool is not run, even in the private
tree), so the block is the same wherever it is generated. ``--write`` runs the verifier,
including its read-only chain reads, and rewrites the marked block in README.md and
attestation/README.md; it refuses to write unless every chain check is PASS. ``--check`` needs no
network: it recomputes the offline lines (integrity, published truth, the first run's validator
and plan lines, the offline tally) and fails if the block differs from them. The chain lines of
the block come from the last ``--write`` and are not rechecked offline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_attestation as va  # noqa: E402

TARGETS = [ROOT / "README.md", ROOT / "attestation" / "README.md"]
BEGIN = "<!-- BEGIN VERIFIER_OUTPUT -->"
END = "<!-- END VERIFIER_OUTPUT -->"
WIDTH = 150
OFFLINE_PREFIXES = ("integrity ", "published truth:", "reproduces offline:")


def shown(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def plan_absent() -> str:
    raise va.PrivateUnavailable(va.PLAN_REASON)


def trim(line: str) -> str:
    return line if len(line) <= WIDTH else line[:WIDTH - 4].rstrip() + " ..."


def lines_of(report: dict) -> tuple[list[str], list[str]]:
    """``(offline lines, chain-dependent lines)`` of the trimmed block, in print order."""
    first = report["runs"][0]["run_id"]
    offline, chain = [], []
    section, in_first = 0, False
    for line in va.render(report).splitlines():
        if line.startswith("== "):
            section = 1 if line.startswith("== 1.") else 2 if line.startswith("== 2.") else 3
            continue
        if section == 1:
            if line.startswith("run "):
                in_first = line.startswith(f"run {first} ")
            elif in_first and line.split()[:1] in (["validator"], ["plan"]):
                offline.append(trim(line))
            elif line.startswith(OFFLINE_PREFIXES):
                offline.append(line)
        elif section == 2:
            if line.startswith(f"run {first} "):
                chain.append(trim(line))
            elif line.startswith("chain corroboration:"):
                chain.append(line)
        elif line.startswith(("OVERALL", "SUMMARY", "exit code")):
            chain.append(line)
    return offline, chain


def block_text(report: dict) -> str:
    offline, chain = lines_of(report)
    return "\n".join(offline + chain)


def render_block(report: dict) -> str:
    return "\n".join([BEGIN, "```", block_text(report), "```", END])


def offline_lines_in(block: str) -> list[str]:
    return [ln for ln in block.splitlines()
            if ln.startswith(OFFLINE_PREFIXES) or ln.startswith(("  validator", "  plan"))]


def offline_report(doc: dict) -> dict:
    return va.verify(doc, client=None, plan_digest_fn=plan_absent)


def current_block(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return None
    return text[text.index(BEGIN):text.index(END) + len(END)]


def check() -> int:
    doc = json.loads(va.DEFAULT_ATTESTATION.read_text(encoding="utf-8"))
    holder = va.isolate_home(None)
    try:
        report = offline_report(doc)
        report["truth"] = va.TRUTH_NOTE.get("truth")
    finally:
        if holder is not None:
            holder.cleanup()
    expected = lines_of(report)[0]
    wanted = [ln for ln in expected]
    bad = 0
    for path in TARGETS:
        block = current_block(path)
        found = None if block is None else offline_lines_in(block)
        if found is None or sorted(found) != sorted(wanted):
            print(f"STALE: {shown(path)} verifier block differs from the offline "
                  f"recomputation; run render_verifier_output.py --write", file=sys.stderr)
            bad += 1
    if not bad:
        print("verifier output blocks are current (offline lines)")
    return 1 if bad else 0


def write() -> int:
    doc = json.loads(va.DEFAULT_ATTESTATION.read_text(encoding="utf-8"))
    holder = va.isolate_home(None)
    try:
        report = va.verify(doc, chain_client=lambda: va.make_read_client(None),
                           plan_digest_fn=plan_absent)
        report["truth"] = va.TRUTH_NOTE.get("truth")
    finally:
        if holder is not None:
            holder.cleanup()
    if report["chain"]["verdict"] != va.PASS:
        print("refusing to write: the chain section is not PASS "
              f"({report['chain']['verdict']})", file=sys.stderr)
        return 1
    block = render_block(report)
    for path in TARGETS:
        old = current_block(path)
        if old is None:
            print(f"no marked block in {path}", file=sys.stderr)
            return 1
        path.write_text(path.read_text(encoding="utf-8").replace(old, block), encoding="utf-8")
        print(f"wrote {shown(path)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if args.write:
        return write()
    doc = json.loads(va.DEFAULT_ATTESTATION.read_text(encoding="utf-8"))
    holder = va.isolate_home(None)
    try:
        report = offline_report(doc)
        report["truth"] = va.TRUTH_NOTE.get("truth")
    finally:
        if holder is not None:
            holder.cleanup()
    print("(offline view; chain lines need --write)")
    print(block_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
