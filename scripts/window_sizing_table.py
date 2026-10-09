#!/usr/bin/env python3
"""Window size and reference-failure tolerance of the committed profiles (DIAGNOSTIC only).

  uv run python scripts/window_sizing_table.py [--check ADR_FILE]

Prints the markdown block that ADR-0020 embeds between its GENERATED markers. Every number is
read from the committed profile documents and from ``epoch_estimate``, the scorer's own Eq. 13
eligibility rule; nothing is typed. For each profile it sweeps the number k of assigned scored
cases that lose their reference truth (a reference failure removes the case from the admitted
supply) and reports whether a window of otherwise perfect, valid responses stays eligible.
With ``--check`` it exits 1 when the block in the ADR differs from the generated one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sn87_provenonce import profile as profiles
from sn87_provenonce.scoring import epoch_estimate

PROFILES = ("IC-FIRST-LIGHT-MIN-1", "IC-FIRST-LIGHT-MIN-2", "IC-FIRST-LIGHT-MIN-3")
BEGIN, END = "<!-- BEGIN GENERATED: window-sizing -->", "<!-- END GENERATED: window-sizing -->"
SWEEP = 4


def sizing(profile_id: str) -> dict:
    p = profiles.load(profile_id)
    assigned = sum(p.document["assignment"].values())
    sweep = []
    for k in range(SWEEP + 1):
        n = assigned - k
        result = epoch_estimate([1.0] * n, [True] * n, p)
        sweep.append({"failures": k, "eligible": result["eligible"], "reason": result["reason"]})
    first_void = next((s["failures"] for s in sweep if not s["eligible"]), None)
    return {"profile_id": profile_id, "assigned": assigned, "minimum": p.minimum,
            "tolerated": assigned - p.minimum, "first_void": first_void, "sweep": sweep,
            "ceiling": p.document["maximum_raw_invalid_or_missing_rate"]}


def block() -> str:
    rows = [sizing(pid) for pid in PROFILES]
    lines = ["Assigned scored cases per window, the profile minimum, and how many reference "
             "failures a window absorbs (a failed reference removes its case from the admitted "
             "supply):", "",
             "| Profile | Assigned scored | Minimum | Reference failures tolerated | "
             "Window void from |", "|---|---|---|---|---|"]
    for r in rows:
        void = f"{r['first_void']} failure(s)" if r["first_void"] is not None else f"> {SWEEP}"
        lines.append(f"| {r['profile_id']} | {r['assigned']} | {r['minimum']} | "
                     f"{r['tolerated']} | {void} |")
    lines += ["", "Eligibility of a window of valid responses after k reference failures "
              "(`epoch_estimate`):", "",
              "| k | " + " | ".join(r["profile_id"] for r in rows) + " |",
              "|---|" + "---|" * len(rows)]
    for k in range(SWEEP + 1):
        cells = []
        for r in rows:
            s = r["sweep"][k]
            cells.append("eligible" if s["eligible"] else f"void ({s['reason']})")
        lines.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", metavar="ADR_FILE", help="compare with the block in this ADR")
    args = p.parse_args(argv)
    generated = block()
    if not args.check:
        sys.stdout.write(generated)
        return 0
    text = Path(args.check).read_text("utf-8")
    embedded = text.split(BEGIN, 1)[1].split(END, 1)[0].strip("\n") + "\n"
    if embedded != generated:
        print("window sizing block differs from the generated one", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
