#!/usr/bin/env python3
"""Check that every repository path cited in the documents and scripts of a tree exists in it.

  uv run python scripts/check_doc_paths.py            # the repository this script is in
  uv run python scripts/check_doc_paths.py --root DIR # any tree, for example a public export

Two kinds of pointer are checked: relative markdown links, and repository paths named in prose,
code spans, code blocks and docstrings of ``.md``, ``.toml``, ``.yml`` files and of ``.py`` files
under ``src/`` and ``scripts/``. A path that holds a glob must match at least one file. A path
that only the export overlay directory supplies counts as present. Exit 0
when every pointer resolves, 1 otherwise (each problem is printed as ``file:line: ...``).

A reference to a file that lives only in Provenonce's private source repository is allowed when
it starts with one of PRIVATE_PREFIXES and the text right after it says
``(private suite)``; the status matrix uses that marker. The one
other exception is KNOWN_PRIVATE_POINTERS, for source files that serialise such names as data.

This is the rule the public export applies to the tree it builds; the export script imports it
from here, so there is one implementation. Reads local files only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Never scanned: the lock file is machine output from the package index.
SCAN_SKIP = {"uv.lock"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
             "dist", "build", "node_modules"}
# Python files are pointer-checked only under these directories: tests name absent paths on
# purpose (skip conditions, fake paths in manifest tests).
POINTER_DIRS = ("src/", "scripts/")
# Source files that may name private paths as data: the evidence bundle serialises a status
# matrix that cites tests and scripts of the private source repository, and the two scripts
# below hold the list of those prefixes.
PRIVATE_PREFIXES = ("tests/test_golden.py", "tests/pilot/", "scripts/pilot_chain_")
KNOWN_PRIVATE_POINTERS = {
    "src/sn87_provenonce/bundle.py": PRIVATE_PREFIXES,
    "scripts/check_doc_paths.py": PRIVATE_PREFIXES,
    "scripts/render_status_matrix.py": PRIVATE_PREFIXES,
}
# directly after the path span: an optional ``::test`` or ``:symbol``, an optional closing
# backtick, then the marker
PRIVATE_MARKER = re.compile(r"(?::{1,2}[\w.\[\]-]+)?`?[ ]\(private suite\)")

PATH_ROOTS = ("scripts", "docs", "src", "tests", "attestation", "examples", "protocol",
              "reproduce", "export")
PATH_RE = re.compile(r"(?<![\w./-])((?:" + "|".join(PATH_ROOTS) + r")/[\w.\-*/]*[\w*/])")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
PATH_SUFFIXES = (".py", ".md", ".json", ".jsonl", ".toml", ".yml", ".yaml", ".txt", ".lock")


def walk(root: Path) -> list[str]:
    """Files of the tree: the tracked files when ``root`` is a git checkout, else every file
    outside the usual build and environment directories."""
    if (root / ".git").exists():
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, timeout=120)
        if out.returncode == 0:
            names = [p for p in out.stdout.decode().split("\0") if p]
            if names:  # an empty index (a fresh git init) falls through to the walk
                return sorted(p for p in names if (root / p).is_file())
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts))


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


OVERLAY = "export/overlay"


def _path_exists(root: Path, token: str) -> bool:
    token = token.rstrip(".,;:)")
    if "*" in token:
        return any(root.glob(token))
    return (root / token).exists()


def _target_exists(root: Path, base: Path, target: str) -> bool:
    """A link target exists in the tree, or in the export overlay that supplies it (the private
    repository holds the public CI workflow in its overlay directory)."""
    resolved = (base / target).resolve()
    if resolved.exists():
        return True
    try:
        rel = resolved.relative_to(root.resolve())
    except ValueError:
        return False
    return (root / OVERLAY / rel).exists()


def check_links(root: Path, files: list[str] | None = None) -> list[str]:
    """Dangling pointers: relative markdown links, and repository paths named in documents and
    scripts (in prose, code spans, code blocks and docstrings alike)."""
    problems: list[str] = []
    for rel in walk(root) if files is None else files:
        path = root / rel
        if rel in SCAN_SKIP or path.suffix not in (".md", ".py", ".toml", ".yml"):
            continue
        if path.suffix == ".py" and not rel.startswith(POINTER_DIRS):
            continue
        text = _text(path)
        if text is None:
            continue
        if path.suffix == ".md":
            for match in LINK_RE.finditer(text):
                target = match.group(1)
                if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                target = target.split("#", 1)[0]
                if target and not _target_exists(root, path.parent, target):
                    line = text.count("\n", 0, match.start()) + 1
                    problems.append(f"{rel}:{line}: link target missing: {target}")
        for match in PATH_RE.finditer(text):
            token = match.group(1).rstrip(".,;:")
            if "<" in token or "{" in token:
                continue
            if not token.endswith(PATH_SUFFIXES) and not token.endswith("/"):
                continue  # a word after a slash, not a file or directory path
            if token.startswith(KNOWN_PRIVATE_POINTERS.get(rel, ())):
                continue
            if token.startswith(PRIVATE_PREFIXES) and PRIVATE_MARKER.match(text, match.end()):
                continue  # explicitly marked as living in the private suite
            if not (_path_exists(root, token) or _path_exists(root, f"{OVERLAY}/{token}")):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{rel}:{line}: path missing: {token}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="tree to check (default: this repo)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1
    problems = check_links(root)
    for problem in problems:
        print("DOC PATH FAIL:", problem)
    print("DOC PATHS", "FAIL" if problems else "OK", f"({len(problems)} problems)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
