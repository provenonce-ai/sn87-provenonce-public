#!/usr/bin/env python3
"""Render docs/protocol/implementation-status.md from the status matrix, marking private files.

  uv run python scripts/render_status_matrix.py          # print the table
  uv run python scripts/render_status_matrix.py --check  # exit 1 if the document drifted
  uv run python scripts/render_status_matrix.py --write  # rewrite the table in the document

The table is ``sn87_provenonce.bundle.status_markdown()`` with one addition: a cited path that
lives only in Provenonce's private source repository gets the visible marker ``(private suite)``.
The marker is a rendering of the document only. ``STATUS_MATRIX`` is serialised into every
evidence bundle and the bundle digests are committed, so the matrix itself is not changed.
Reads local files only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sn87_provenonce.bundle import status_markdown  # noqa: E402

DOC = ROOT / "docs" / "protocol" / "implementation-status.md"
BEGIN = "<!-- BEGIN STATUS_MATRIX -->\n"
END = "<!-- END STATUS_MATRIX -->"
# Paths the matrix cites that are not in the public tree. tests/test_render_status_matrix.py
# checks this list against the manifest and against the matrix.
PRIVATE_SUITE_PREFIXES = ("tests/pilot/", "tests/test_golden.py", "scripts/pilot_chain_")
MARK = " (private suite)"
_CODE_SPAN = re.compile(r"`([^`]+)`")


def mark_private(table: str) -> str:
    """Add the marker after every code span that cites a private path."""
    def mark(match: re.Match) -> str:
        span = match.group(0)
        return span + MARK if match.group(1).startswith(PRIVATE_SUITE_PREFIXES) else span
    return "\n".join(_CODE_SPAN.sub(mark, line) for line in table.split("\n"))


def render() -> str:
    return mark_private(status_markdown())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    table = render()
    if not (args.check or args.write):
        print(table, end="")
        return 0
    text = DOC.read_text(encoding="utf-8")
    head, rest = text.split(BEGIN, 1)
    current, tail = rest.split(END, 1)
    if current == table:
        print("status matrix document: up to date")
        return 0
    if args.check:
        print("status matrix document drifted from the matrix", file=sys.stderr)
        return 1
    DOC.write_text(head + BEGIN + table + END + tail, encoding="utf-8")
    print("status matrix document: rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
