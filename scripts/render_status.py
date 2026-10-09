#!/usr/bin/env python3
"""Render the status figures that documents quote from the attestation files, and check them.

  uv run python scripts/render_status.py            # print every generated block
  uv run python scripts/render_status.py --check    # exit 1 if a document differs from the data
  uv run python scripts/render_status.py --write    # rewrite the generated blocks in place

A document marks a generated block with a pair of comments::

  <!-- BEGIN STATUS:work_in_public -->
  ...generated text...
  <!-- END STATUS:work_in_public -->

Everything between the markers is produced here from
``attestation/SN87_TESTNET_ATTESTATION_02.json``
(run count, first and latest run id and block, the run-id letters that are absent), from
``attestation/SN87_TESTNET_ATTESTATION_01.json`` (its run count and the check that every run of it
is in 02 unchanged) and from ``attestation/TESTNET_582_PARTICIPANTS.json`` (the block of the
First Light weight row, the validator's first recorded set-weights block). A fact that none of
these files holds does not appear in a generated block; in particular the attestation holds no
calendar dates, so none is printed.

The guide's expectations for the verifier step are filled from the same data; the first chain line
is derived (the previous set-weights block of the first run is the First Light block).
``scripts/run_guide.py --network`` runs the verifier against the chain and compares the real output
with those lines. (The README verifier block is a real run, kept by render_verifier_output.py.)
Reads local files only; no network, no wallet.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATT = ROOT / "attestation"
ATTESTATION_01 = ATT / "SN87_TESTNET_ATTESTATION_01.json"
ATTESTATION_02 = ATT / "SN87_TESTNET_ATTESTATION_02.json"
PARTICIPANTS = ATT / "TESTNET_582_PARTICIPANTS.json"
# Document -> the blocks it must carry. Any other document may carry blocks of the known names.
REQUIRED = {
    "README.md": ("work_in_public",),
    "attestation/README.md": ("attestation_files", "attestation_gaps"),
    "docs/guides/reviewer-test-guide.md": ("guide_attested_runs", "guide_verify_expect"),
}
GUIDE_DIR = ROOT / "docs" / "guides"
_BLOCK = re.compile(
    r"(<!-- BEGIN STATUS:(?P<name>[a-z_]+) -->\n)(?P<body>.*?)(<!-- END STATUS:(?P=name) -->)",
    re.S)


class StatusError(ValueError):
    """The data files disagree with each other or with their own totals."""


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def facts() -> dict:
    """The figures, each read from the file that holds it."""
    second, first = _load(ATTESTATION_02), _load(ATTESTATION_01)
    runs = second["runs"]
    if second["run_count"] != len(runs) or first["run_count"] != len(first["runs"]):
        raise StatusError("run_count differs from the length of the runs list")
    by_id = {run["run_id"]: run for run in runs}
    for run in first["runs"]:
        if by_id.get(run["run_id"]) != run:
            raise StatusError(f"run {run['run_id']} of attestation 01 is not in 02 unchanged")
    blocks = [run["included_block"] for run in runs]
    if blocks != sorted(blocks) or len(set(blocks)) != len(blocks):
        raise StatusError("runs are not in strictly increasing block order")
    light = _load(PARTICIPANTS)["periods"]["first_light"]["from_block"]
    if not isinstance(light, int) or light >= blocks[0]:
        raise StatusError("the First Light block is missing or not before the first run")
    return {"count": len(runs), "count_01": len(first["runs"]), "runs": runs, "first": runs[0],
            "latest": runs[-1], "light_block": light, "digest": second["attestation_digest"],
            "digest_01": first["attestation_digest"], "netuid": second["netuid"]}


def missing_run_ids(runs: list[dict]) -> list[str]:
    """Run ids absent from the letter sequence of each day (``r5-20261005-i`` between h and j)."""
    seen: dict[str, set[str]] = {}
    for run in runs:
        prefix, _, letter = run["run_id"].rpartition("-")
        if len(letter) != 1:
            raise StatusError(f"run id {run['run_id']} does not end in one letter")
        seen.setdefault(prefix, set()).add(letter)
    absent = []
    for prefix, letters in sorted(seen.items()):
        for code in range(ord(min(letters)), ord(max(letters)) + 1):
            if chr(code) not in letters:
                absent.append(f"{prefix}-{chr(code)}")
    return absent


def chain_line(f: dict, index: int) -> str:
    """The line the verifier prints for run ``index`` in its chain section."""
    run = f["runs"][index]
    block = run["included_block"]
    previous = f["light_block"] if index == 0 else f["runs"][index - 1]["included_block"]
    return (f"run {run['run_id']}  block {block}  PASS  uid 0 set weights in exactly block {block} "
            f"(LastUpdate {previous} at block {block - 1}, {block} at block {block}) and the row "
            f"at block {block} equals the attested row; block is inside the window "
            f"{run['window_start']}-{run['window_end']}")


def verifier_lines(f: dict) -> dict[str, str]:
    """Named lines of the public-tree verifier output that the data determines."""
    n = f["count"]
    return {
        "integrity": f"integrity  PASS  digest recomputes ({f['digest']})",
        "offline": (f"reproduces offline: UNVERIFIED  (1 PASS / 0 FAIL / {2 * n} UNVERIFIED of "
                    f"{2 * n + 1} checks: integrity + plan and validator for {n} runs)"),
        "first_chain": chain_line(f, 0),
        "last_chain": chain_line(f, n - 1),
        "corroboration": (f"chain corroboration: PASS  ({n} PASS / 0 FAIL / 0 UNVERIFIED of "
                          f"{n} runs)"),
        "overall": f"OVERALL UNVERIFIED: 0/{n} runs PASS, 0 FAIL, {n} UNVERIFIED",
        "summary": (f"SUMMARY integrity: PASS; chain: {n}/{n} PASS; scoring: not verifiable "
                    "outside Provenonce (plan and validator UNVERIFIED: requires private "
                    "reference executor)"),
        "exit": "exit code 3 (0 = PASS, 1 = FAIL, 3 = UNVERIFIED)",
    }


def work_in_public(f: dict) -> str:
    first, latest = f["first"], f["latest"]
    return (
        f"SN87 is live on Bittensor testnet {f['netuid']}. The validator's first recorded "
        f"set-weights row (First Light) was applied at block {f['light_block']:,}. The attested "
        f"series is {f['count']} runs in attestation 02: it starts with `{first['run_id']}` at "
        f"block {first['included_block']:,}, and its latest run, `{latest['run_id']}`, landed at "
        f"block {latest['included_block']:,}. The code is open under the MIT License, and anyone "
        "can check the chain proof themselves with the public verifier below.\n")


def attestation_files(f: dict) -> str:
    rows = []
    for path in (ATTESTATION_01, ATTESTATION_02):
        runs = _load(path)["runs"]
        rows.append(f"| `{path.name}` | {len(runs)} | `{runs[0]['run_id']}` "
                    f"({runs[0]['included_block']:,}) | `{runs[-1]['run_id']}` "
                    f"({runs[-1]['included_block']:,}) |")
    return ("Generated by `scripts/render_status.py` from the two files.\n\n"
            "| File | Runs | First run (block) | Latest run (block) |\n| --- | --- | --- | --- |\n"
            + "\n".join(rows) + "\n\n"
            f"Attestation 02 contains all {f['count_01']} runs of 01 with identical records "
            "(`scripts/render_status.py --check` verifies this).\n")


def attestation_gaps(f: dict) -> str:
    absent = missing_run_ids(f["runs"])
    listed = ", ".join(f"`{a}`" for a in absent) if absent else "none"
    return ("Run ids carry one letter per run for each day. Letters absent from the sequence in "
            f"attestation 02 (generated): {listed}. A run is absent when it was excluded under "
            "the rule above.\n")


def guide_attested_runs(f: dict) -> str:
    return (f"The file called attestation 02 lists {f['count']} of those runs, from "
            f"`{f['first']['run_id']}` to `{f['latest']['run_id']}`.\n")


def guide_verify_expect(f: dict) -> str:
    v = verifier_lines(f)
    lines = ["SN87 testnet attestation verification (read only: no key, no chain write)", "...",
             v["integrity"], "...", v["first_chain"], "...", v["last_chain"], "...",
             v["corroboration"], "...",
             r"re: OVERALL (PASS|UNVERIFIED): .*", "...", r"re: exit code [03] \(.*\)"]
    return "```text expect\n" + "\n".join(lines) + "\n```\n"


RENDERERS = {
    "work_in_public": work_in_public,
    "attestation_files": attestation_files,
    "attestation_gaps": attestation_gaps,
    "guide_attested_runs": guide_attested_runs,
    "guide_verify_expect": guide_verify_expect,
}


def targets() -> list[Path]:
    found = [ROOT / name for name in REQUIRED]
    found += sorted(p for p in GUIDE_DIR.glob("*.md") if p not in found)
    return [p for p in found if p.exists()]


def rewrite(text: str, f: dict, where: str) -> str:
    def swap(match: re.Match) -> str:
        name = match.group("name")
        if name not in RENDERERS:
            raise StatusError(f"{where}: unknown status block {name!r}")
        return match.group(1) + RENDERERS[name](f) + match.group(4)
    return _BLOCK.sub(swap, text)


def problems(f: dict) -> list[str]:
    out = []
    for name, needed in REQUIRED.items():
        path = ROOT / name
        if not path.exists():
            out.append(f"{name}: file is missing")
            continue
        text = path.read_text(encoding="utf-8")
        found = {m.group("name") for m in _BLOCK.finditer(text)}
        out += [f"{name}: missing generated block {n!r}" for n in needed if n not in found]
        if text.count("<!-- BEGIN STATUS:") != len(found) or \
           text.count("<!-- END STATUS:") != len(found):
            out.append(f"{name}: a STATUS marker is unpaired or repeated")
    for path in targets():
        text = path.read_text(encoding="utf-8")
        if rewrite(text, f, path.name) != text:
            out.append(f"{path.relative_to(ROOT)}: generated block differs from the data")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    f = facts()
    if not (args.check or args.write):
        for name, render in RENDERERS.items():
            print(f"--- {name}\n{render(f)}", end="")
        return 0
    if args.write:
        for path in targets():
            text = path.read_text(encoding="utf-8")
            new = rewrite(text, f, path.name)
            if new != text:
                path.write_text(new, encoding="utf-8")
                print(f"rewrote {path.relative_to(ROOT)}")
    found = problems(f)
    for line in found:
        print(line, file=sys.stderr)
    if found and args.check:
        print("run: uv run python scripts/render_status.py --write", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
