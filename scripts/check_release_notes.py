#!/usr/bin/env python3
"""Public-safety gate for release notes: scan CHANGELOG.md, ``changes/**`` and generated notes.

  uv run python scripts/check_release_notes.py                   # CHANGELOG.md and changes/**
  uv run python scripts/check_release_notes.py --notes FILE ...  # also scan generated notes
  uv run python scripts/check_release_notes.py --root DIR        # any tree, for example an export

Exit 0 when the text is clean, 1 on any hit (each is printed as ``file:line: [class] line``).
The words come from ``public_words.py``, the one list the export builder also uses, applied here
case-insensitively and with no allow-list: internal names and labels, local paths, e-mail
addresses and hosts that are not on the allowed list, token and market words, customer names,
mainnet dates, and the tree-wide style rules. Fragments must also be named
``<slug>.<type>.md`` and hold one or two plain sentences (see ``changes/README.md``). The
patterns that name people and organisations are applied only where this checkout has them (the
private repository and the export self-check).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import public_words  # noqa: E402
import release_notes  # noqa: E402


def scan_text(text: str, rel: str) -> list[str]:
    """``rel:line: [class] excerpt`` for every public-safety hit in ``text``."""
    patterns = public_words.release_patterns()
    hits = public_words.new_hits(patterns)
    public_words.scan_text(text, rel, patterns, hits, ignore_case=True)
    lines = text.splitlines()
    found = []
    for name, where in hits.items():
        for item in where:
            place, _, extra = item.partition(" ")
            number = int(place.rsplit(":", 1)[1])
            excerpt = extra or lines[number - 1].strip()
            found.append(f"{place}: [{name}] {excerpt[:100]}")
    return sorted(found, key=lambda s: (s.split(":")[0], int(s.split(":")[1]), s))


def scan_name(rel: str) -> list[str]:
    """Hits in a file name or path. Separators become spaces so ``quorum-fix`` and ``w34_x``
    are read as words; the name is judged by the same list as the text."""
    spaced = re.sub(r"[-_./\\]+", " ", rel)
    found = []
    for line in scan_text(spaced, rel):
        found.append(re.sub(r"^.*?:1: ", f"{rel}: ", line) + "  (file name)")
    return found


def check_fragments(root: Path) -> list[str]:
    """Name and shape problems of the fragments directly in ``changes/``."""
    problems = []
    for path in release_notes.fragment_files(root):
        try:
            release_notes.parse_name(path.name)
            release_notes.normalise(path.read_text(encoding="utf-8"), path.name)
        except release_notes.ReleaseError as error:
            problems.append(f"changes/{path.name}: {error}")
    return problems


def files_to_scan(root: Path, notes: list[Path] | None = None) -> list[tuple[Path, str]]:
    found = []
    if (root / "CHANGELOG.md").is_file():
        found.append((root / "CHANGELOG.md", "CHANGELOG.md"))
    folder = root / "changes"
    if folder.is_dir():
        found += [(p, p.relative_to(root).as_posix()) for p in sorted(folder.rglob("*"))
                  if p.is_file() and p.suffix in (".md", ".txt")]
    for note in notes or []:
        found.append((note, note.name))
    return found


def check_tree(root: Path, notes: list[Path] | None = None) -> list[str]:
    problems = check_fragments(root)
    folder = root / "changes"
    if folder.is_dir():  # every path below changes/, whatever its suffix
        for path in sorted(folder.rglob("*")):
            problems += scan_name(path.relative_to(root).as_posix())
    for path, rel in files_to_scan(root, notes):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            problems.append(f"{rel}: unreadable: {error}")
            continue
        problems += scan_text(text, rel)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="tree to check (default: this one)")
    parser.add_argument("--notes", type=Path, nargs="*", default=[],
                        help="generated release notes files to scan as well")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    problems = check_tree(root, args.notes)
    for problem in problems:
        print(problem)
    scanned = len(files_to_scan(root, args.notes))
    print(f"check_release_notes: {scanned} files, {len(problems)} problems, "
          f"{'FAIL' if problems else 'OK'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
