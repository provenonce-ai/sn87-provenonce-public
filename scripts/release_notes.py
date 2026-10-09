#!/usr/bin/env python3
"""Assemble the change fragments in ``changes/`` into release notes.

  uv run python scripts/release_notes.py --version 0.1.0 --date 2026-10-08 --dry-run
  uv run python scripts/release_notes.py --version 0.1.0 --date 2026-10-08 \\
      --title "Public testnet release"

A fragment is ``changes/<slug>.<type>.md`` with type one of added, changed, fixed, security,
docs, holding one or two plain sentences (see ``changes/README.md``). This script

1. checks every fragment, CHANGELOG.md and the notes it generates with the public-safety words
   (``check_release_notes``) and refuses on any hit,
2. inserts a ``## [X.Y.Z] - YYYY-MM-DD`` section into CHANGELOG.md below the ``## Unreleased``
   heading, with sections Added, Changed, Fixed, Security, Docs in that order and the fragments
   sorted by slug (digits compared as numbers),
3. writes the GitHub Release body to ``dist/RELEASE_NOTES_<version>.md`` (``dist/`` is
   gitignored; ``--out`` names another file or directory), and
4. moves each consumed fragment to ``changes/archive/<version>/`` with ``git mv``.

``--dry-run`` prints the notes and the planned moves and writes nothing. The same fragments and
arguments always produce the same bytes. It refuses when the version already has a section in
CHANGELOG.md or an archive directory, and when there is no fragment. It never creates a tag or a
release: the tag name (``vX.Y.Z``) is printed for the maintainer who performs that public step.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Fixed order of the sections; the heading is the capitalised type.
TYPES = ("added", "changed", "fixed", "security", "docs")
HEADINGS = {t: t.capitalize() for t in TYPES}
VERSION_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")  # lower-case slugs: same order on every platform
MAX_FRAGMENT_CHARS = 600


class ReleaseError(RuntimeError):
    """The release is refused; nothing was written."""


@dataclass(frozen=True)
class Fragment:
    path: str  # repo-relative, POSIX
    slug: str
    type: str
    text: str


def _natural(slug: str) -> list:
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"([0-9]+)", slug) if p]


def parse_name(name: str) -> tuple[str, str]:
    """``<slug>.<type>.md`` -> (slug, type); ReleaseError when the name does not fit."""
    if not name.endswith(".md"):
        raise ReleaseError(f"{name}: a fragment is <slug>.<type>.md")
    stem, _, kind = name[:-3].rpartition(".")
    if not stem or kind not in TYPES:
        raise ReleaseError(f"{name}: a fragment is <slug>.<type>.md with type one of "
                           f"{', '.join(TYPES)}")
    if not SLUG_RE.match(stem):
        raise ReleaseError(f"{name}: the slug uses lower-case letters, digits, '-' and '_' only")
    return stem, kind


def normalise(raw: str, name: str) -> str:
    """The fragment text as one line: whitespace collapsed, no bullet marker, not empty."""
    text = " ".join(raw.split())
    if not text:
        raise ReleaseError(f"{name}: the fragment is empty")
    if text[:2] in ("- ", "* ") or text.startswith("#"):
        raise ReleaseError(f"{name}: write plain sentences, not a list item or heading")
    if len(text) > MAX_FRAGMENT_CHARS:
        raise ReleaseError(f"{name}: {len(text)} characters; keep it to one or two sentences "
                           f"(at most {MAX_FRAGMENT_CHARS})")
    return text


def fragment_files(repo: Path) -> list[Path]:
    """Fragment files directly in ``changes/`` (README.md and archive/ are not fragments)."""
    folder = repo / "changes"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix == ".md" and p.name != "README.md")


def collect(repo: Path) -> list[Fragment]:
    """All fragments in deterministic order: by type order, then slug, then file name."""
    found = []
    for path in fragment_files(repo):
        slug, kind = parse_name(path.name)
        text = normalise(path.read_text(encoding="utf-8"), path.name)
        found.append(Fragment(f"changes/{path.name}", slug, kind, text))
    return sorted(found, key=lambda f: (TYPES.index(f.type), _natural(f.slug), f.path))


def render_sections(fragments: list[Fragment], level: str) -> str:
    """The ``### Added`` ... blocks; ``level`` is the heading prefix, for example ``###``."""
    blocks = []
    for kind in TYPES:
        items = [f for f in fragments if f.type == kind]
        if items:
            lines = "\n".join(f"- {f.text}" for f in items)
            blocks.append(f"{level} {HEADINGS[kind]}\n\n{lines}\n")
    return "\n".join(blocks)


def changelog_section(version: str, date: str, title: str | None,
                      fragments: list[Fragment]) -> str:
    head = f"## [{version}] - {date}\n\n"
    if title:
        head += f"{title}\n\n"
    return head + render_sections(fragments, "###")


def release_body(title: str | None, fragments: list[Fragment]) -> str:
    """The GitHub Release body: the optional title line, then the sections."""
    head = f"{title}\n\n" if title else ""
    return head + render_sections(fragments, "###")


def insert_section(changelog: str, section: str) -> str:
    """Put ``section`` below the ``## Unreleased`` section (or above the first ``## `` heading
    when there is none), keeping one blank line around it."""
    lines = changelog.split("\n")
    headings = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not headings:
        raise ReleaseError("CHANGELOG.md has no '## ' heading to insert the release before")
    at = headings[0]
    if lines[at].strip().lower() in ("## unreleased", "## [unreleased]"):
        at = headings[1] if len(headings) > 1 else len(lines)
    before = "\n".join(lines[:at]).rstrip("\n") + "\n\n"
    after = "\n".join(lines[at:])
    return before + section.rstrip("\n") + "\n" + ("\n" + after if after else "")


def _git_status(repo: Path, paths: list[str]) -> dict[str, str]:
    """path -> two-letter ``git status --porcelain`` code for the paths that are not clean."""
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "-z", "--",
                          *paths], cwd=repo, capture_output=True, text=True)
    if out.returncode != 0:
        raise ReleaseError(f"git status failed: {out.stderr.strip()}")
    codes = {}
    entries = out.stdout.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        if len(entry) > 3:
            codes[entry[3:]] = entry[:2]
            if entry[0] in "RC":  # a rename lists its source as the next entry
                i += 1
        i += 1
    return codes


def clean_fragments(repo: Path, paths: list[str]) -> None:
    """Refuse unless every fragment is tracked and equal to HEAD in the index and the tree, so
    the archive holds exactly the committed text that the notes were built from."""
    codes = _git_status(repo, paths)
    untracked = sorted(p for p, c in codes.items() if c == "??")
    if untracked:
        raise ReleaseError("commit these fragments first (git mv needs tracked files): "
                           + ", ".join(untracked))
    if codes:
        raise ReleaseError("these fragments have staged or unstaged changes; commit or discard "
                           "them first: " + ", ".join(sorted(codes)))
    listed = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=repo,
                            capture_output=True, text=True).stdout.split("\0")
    missing = sorted(set(paths) - set(listed))
    if missing:
        raise ReleaseError("commit these fragments first (git mv needs tracked files): "
                           + ", ".join(missing))


def plan(repo: Path, version: str, date: str, title: str | None) -> dict:
    if not VERSION_RE.match(version):
        raise ReleaseError(f"--version {version!r}: use MAJOR.MINOR.PATCH, for example 0.1.0")
    try:
        if not DATE_RE.match(date):
            raise ValueError(date)
        datetime.date.fromisoformat(date)
    except ValueError:
        raise ReleaseError(f"--date {date!r}: use YYYY-MM-DD") from None
    if title is not None and ("\n" in title or not title.strip()):
        raise ReleaseError("--title is one line of text")
    changelog_path = repo / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    if re.search(rf"^## \[?{re.escape(version)}\]?(?:\s|$)", changelog, re.MULTILINE):
        raise ReleaseError(f"CHANGELOG.md already has a section for {version}; nothing written")
    archive = repo / "changes" / "archive" / version
    if archive.exists():
        raise ReleaseError(f"changes/archive/{version} already exists; nothing written")
    fragments = collect(repo)
    if not fragments:
        raise ReleaseError("no fragments in changes/; nothing to release")
    new_changelog = insert_section(changelog,
                                   changelog_section(version, date, title.strip() if title else
                                                     None, fragments))
    body = release_body(title.strip() if title else None, fragments)
    return {"fragments": fragments, "changelog": new_changelog, "body": body,
            "archive": f"changes/archive/{version}"}


def safety_problems(repo: Path, planned: dict, notes_name: str) -> list[str]:
    """Public-safety hits in the fragments, the new CHANGELOG.md and the generated notes."""
    import check_release_notes  # local import: the checker imports this module for names
    problems = []
    for f in planned["fragments"]:
        problems += check_release_notes.scan_text(f.text, f.path)
        problems += check_release_notes.scan_name(f.path)
    problems += check_release_notes.scan_text(planned["changelog"], "CHANGELOG.md")
    problems += check_release_notes.scan_text(planned["body"], notes_name)
    return sorted(set(problems))


def archive_fragments(repo: Path, moves: list[tuple[str, str]], folder: Path) -> None:
    """Move every fragment with ``git mv`` or none: on a failure the moves already made are
    reversed and the archive directory (empty again) is removed."""
    folder.mkdir(parents=True)
    done: list[tuple[str, str]] = []
    try:
        for src, dst in moves:
            result = subprocess.run(["git", "mv", src, dst], cwd=repo, capture_output=True,
                                    text=True)
            if result.returncode != 0:
                raise ReleaseError(f"git mv {src} failed: {result.stderr.strip()}")
            done.append((src, dst))
    except ReleaseError:
        undo_archive(repo, done, folder)
        raise


def undo_archive(repo: Path, done: list[tuple[str, str]], folder: Path) -> None:
    for src, dst in reversed(done):
        subprocess.run(["git", "mv", dst, src], cwd=repo, capture_output=True)
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()  # rmdir refuses a directory that still holds anything
        parent = folder.parent
        if parent.name == "archive" and not any(parent.iterdir()):
            parent.rmdir()


def preflight(repo: Path, planned: dict, moves: list[tuple[str, str]], notes: Path) -> None:
    """Every refusal that can be known before the first change is made."""
    clean_fragments(repo, [src for src, _ in moves])
    for _, dst in moves:
        if (repo / dst).exists():
            raise ReleaseError(f"{dst} already exists; nothing written")
    changelog = repo / "CHANGELOG.md"
    if not os.access(changelog, os.W_OK):
        raise ReleaseError("CHANGELOG.md is not writable; nothing written")
    if not os.access(repo / "changes", os.W_OK):
        raise ReleaseError("changes/ is not writable; nothing written")
    if notes.is_dir():
        raise ReleaseError(f"{notes} is a directory; nothing written")
    if notes.exists():
        if not os.access(notes, os.W_OK):
            raise ReleaseError(f"{notes} is not writable; nothing written")
        return
    ancestor = notes.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not ancestor.is_dir() or not os.access(ancestor, os.W_OK | os.X_OK):
        raise ReleaseError(f"cannot create {notes}: {ancestor} is not a writable directory; "
                           "nothing written")


def apply(repo: Path, planned: dict, moves: list[tuple[str, str]], notes: Path) -> None:
    """Make the changes in an order that can be reversed: the moves, then CHANGELOG.md, then the
    notes. Any failure undoes what was done before it."""
    folder = repo / planned["archive"]
    changelog = repo / "CHANGELOG.md"
    original = changelog.read_bytes()
    archive_fragments(repo, moves, folder)
    changelog_written = False
    created: list[Path] = []
    notes_backup = notes.read_bytes() if notes.is_file() else None
    try:
        changelog.write_text(planned["changelog"], encoding="utf-8", newline="\n")
        changelog_written = True
        parent = notes.parent
        while not parent.exists():
            created.append(parent)
            parent = parent.parent
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text(planned["body"], encoding="utf-8", newline="\n")
    except OSError as error:
        if notes_backup is not None:
            notes.write_bytes(notes_backup)
        elif notes.is_file():
            notes.unlink()  # our own partial output
        for path in created:  # directories made for the notes, innermost first
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        if changelog_written or changelog.read_bytes() != original:
            changelog.write_bytes(original)
        undo_archive(repo, moves, folder)
        raise ReleaseError(f"could not write the release files ({error}); "
                           "everything was put back") from error


def out_path(repo: Path, out: Path | None, version: str) -> Path:
    name = f"RELEASE_NOTES_{version}.md"
    if out is None:
        return repo / "dist" / name
    return out / name if out.is_dir() or str(out).endswith(("/", "\\")) else out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", required=True, help="MAJOR.MINOR.PATCH, no leading v")
    parser.add_argument("--date", required=True, help="release date, YYYY-MM-DD")
    parser.add_argument("--title",
                        help="one-line release title, for example 'Public testnet release'")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the notes and the planned moves; write nothing")
    parser.add_argument("--out", type=Path,
                        help="file or directory for the release body (default dist/)")
    parser.add_argument("--repo", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    notes = out_path(repo, args.out, args.version)
    try:
        planned = plan(repo, args.version, args.date, args.title)
        problems = safety_problems(repo, planned, notes.name)
        if problems:
            raise ReleaseError("public-safety check failed:\n  " + "\n  ".join(problems))
        moves = [(f.path, f"{planned['archive']}/{Path(f.path).name}")
                 for f in planned["fragments"]]
        if args.dry_run:
            print(f"DRY RUN for {args.version} ({args.date}); nothing is written")
            try:
                clean_fragments(repo, [src for src, _ in moves])
            except ReleaseError as error:
                print(f"WARNING: a real run would refuse: {error}")
            print()
            print(f"--- {notes.name} ---")
            print(planned["body"], end="")
            print("--- planned moves (git mv) ---")
            for src, dst in moves:
                print(f"{src} -> {dst}")
            print(f"--- CHANGELOG.md: new section for {args.version} below Unreleased ---")
            print(f"tag name for the maintainer: v{args.version}")
            return 0
        preflight(repo, planned, moves, notes)
        apply(repo, planned, moves, notes)
    except (OSError, ReleaseError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    print(f"released {args.version}: CHANGELOG.md updated, {len(moves)} fragments moved to "
          f"{planned['archive']}/, notes written to {notes}")
    print(f"tag name for the maintainer: v{args.version} (this script creates no tag or release)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
