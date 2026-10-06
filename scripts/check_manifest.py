#!/usr/bin/env python3
"""Check that PUBLIC_MANIFEST.json classifies every tracked file exactly once.

Classes: allow (exported), private (tracked, never exported), review_required (undecided; the
list is kept empty) and deny (secrets and run state). Precedence is deny > private >
review_required > allow. The check fails (exit 1) when a tracked file matches no class (it would
be default-deny without anyone having decided so), matches more than one class (the lists are
written to be disjoint) or when anything is review_required. Globs that match nothing are
reported but do not fail the check (the deny globs, and the private-only globs when run in the
exported tree, are expected to match nothing).

  scripts/check_manifest.py           # run from anywhere; checks the repo this script is in

Tracked files come from `git ls-files`. Without git, the tree is walked and .git, .venv and
caches are excluded.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ("deny", "private", "review_required", "allow")  # precedence order
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
             "dist", "build"}


def glob_regex(glob: str) -> re.Pattern:
    """`**/` matches zero or more directories, `**` anything, `*` anything but `/`."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"\Z")


@dataclass
class Result:
    files: list[str]
    classified: dict[str, str] = field(default_factory=dict)  # path -> winning class
    unmatched: list[str] = field(default_factory=list)
    overlaps: list[tuple[str, list[str]]] = field(default_factory=list)
    stale_globs: list[str] = field(default_factory=list)

    @property
    def undecided(self) -> list[str]:
        return [p for p, c in self.classified.items() if c == "review_required"]

    @property
    def ok(self) -> bool:
        return not self.unmatched and not self.overlaps and not self.undecided

    def counts(self) -> dict[str, int]:
        return {k: sum(v == k for v in self.classified.values()) for k in CLASSES}


def check(manifest: dict, files: list[str]) -> Result:
    """Classify `files` (repo-relative POSIX paths) against `manifest`."""
    rules = {k: [(g, glob_regex(g)) for e in manifest.get(k, []) for g in e["globs"]]
             for k in CLASSES}
    result = Result(files=sorted(files))
    for path in result.files:
        hits = [k for k in CLASSES if any(rx.match(path) for _, rx in rules[k])]
        if len(hits) > 1:
            result.overlaps.append((path, hits))
        if hits:
            result.classified[path] = hits[0]
        else:
            result.unmatched.append(path)
    result.stale_globs = [g for k in CLASSES for g, rx in rules[k]
                          if not any(rx.match(f) for f in result.files)]
    return result


def tracked_files(root: Path = ROOT) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        out = None
    if out is not None and out.returncode == 0:
        return [p for p in out.stdout.decode().split("\0") if p]
    files = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not any(part in SKIP_DIRS or part.endswith(".egg-info")
                                      for part in rel.parts):
            files.append(rel.as_posix())
    return files


def check_repo(root: Path = ROOT) -> Result:
    manifest = json.loads((root / "PUBLIC_MANIFEST.json").read_text())
    return check(manifest, tracked_files(root))


def main() -> int:
    result = check_repo()
    print(f"{len(result.files)} tracked; {result.counts()}")
    print("unmatched (default-deny, not classified):", result.unmatched)
    print("overlaps (more than one class):", result.overlaps)
    print("undecided (review_required):", result.undecided)
    print("globs matching nothing:", result.stale_globs)
    print("OK" if result.ok else "FAIL")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
