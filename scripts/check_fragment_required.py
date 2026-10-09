#!/usr/bin/env python3
"""Decide whether a pull request needs a change note in ``changes/``.

  uv run python scripts/check_fragment_required.py --files FILE --labels a,b

``FILE`` lists the changed files, one per line: either ``path`` or ``status<TAB>path`` (the
GitHub API statuses added, modified, removed, renamed ...). A pull request needs a note when it
touches ``src/``, ``scripts/`` or a public document (``docs/``, README, CONTRIBUTING,
LIMITATIONS, SECURITY, PROVENANCE) and adds, or renames into place, no
``changes/<name>.<type>.md`` file with a lower-case name, unless it carries the label
``no-changelog``. A modified or removed note does not count. Paths the manifest classes as
private or deny are not
counted: a change to them is not visible to a reader of the public repository. Exit 0 when the
pull request is fine (the reason is printed), 1 when a note is missing.

The ``changelog`` workflow supplies the file list and the labels from the GitHub API; this
script reads no network and no repository state beyond ``PUBLIC_MANIFEST.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_manifest  # noqa: E402

OPT_OUT_LABEL = "no-changelog"
TYPES = ("added", "changed", "fixed", "security", "docs")
NEEDS_NOTE = ("src/", "scripts/", "docs/")
NEEDS_NOTE_FILES = {"README.md", "CONTRIBUTING.md", "LIMITATIONS.md", "SECURITY.md",
                    "PROVENANCE.md"}
# The name the release script accepts (release_notes.parse_name): a lower-case slug.
FRAGMENT = re.compile(r"changes/[a-z0-9][a-z0-9_-]*\.(?:" + "|".join(TYPES) + r")\.md\Z")
# Only a note this pull request brings in counts: an edit to an old note, a removal, or a copy
# of one is not a note for this change.
NEW = {"added", "renamed"}


@dataclass
class Decision:
    ok: bool
    reason: str
    triggers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_files(text: str) -> list[tuple[str, str]]:
    """Lines of ``path`` or ``status<TAB>path`` -> [(status, path)]; a bare path is 'modified'."""
    found = []
    for line in text.splitlines():
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        status, sep, path = line.partition("\t")
        found.append((status.strip().lower(), path.strip()) if sep else ("modified", line.strip()))
    return found


def parse_labels(text: str) -> set[str]:
    return {part.strip().lower() for part in re.split(r"[,\n]", text) if part.strip()}


def is_note(status: str, path: str) -> bool:
    return bool(FRAGMENT.match(path)) and status in NEW


def needs_note(path: str) -> bool:
    return path in NEEDS_NOTE_FILES or path.startswith(NEEDS_NOTE)


def decide(files: list[tuple[str, str]], labels: set[str],
           manifest: dict | None = None) -> Decision:
    """The rule. ``manifest`` (when given) removes paths it classes private or deny."""
    if OPT_OUT_LABEL in {label.lower() for label in labels}:
        return Decision(True, f"label {OPT_OUT_LABEL} is set")
    notes = sorted(p for s, p in files if is_note(s, p))
    candidates = sorted({p for _, p in files if needs_note(p)})
    if manifest is not None and candidates:
        classes = check_manifest.check(manifest, candidates).classified
        candidates = [p for p in candidates if classes.get(p) not in ("private", "deny")]
    if not candidates:
        return Decision(True, "no change to src/, scripts/ or public documents")
    if notes:
        return Decision(True, f"{len(notes)} change note(s) added", candidates, notes)
    return Decision(False, (f"this pull request changes {len(candidates)} file(s) in src/, "
                            "scripts/ or the public documents but adds no change note. Add "
                            "changes/<name>.<type>.md (type: " + ", ".join(TYPES) + ") or, "
                            f"when nothing a reader can see has changed, the label "
                            f"{OPT_OUT_LABEL}. See CONTRIBUTING.md, 'Writing a change note'."),
                    candidates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--files", required=True, help="file listing the changed files, or -")
    parser.add_argument("--labels", default="", help="comma-separated pull request labels")
    parser.add_argument("--manifest", type=Path, default=ROOT / "PUBLIC_MANIFEST.json")
    args = parser.parse_args(argv)
    text = sys.stdin.read() if args.files == "-" else Path(args.files).read_text(encoding="utf-8")
    manifest = json.loads(args.manifest.read_text()) if args.manifest.is_file() else None
    decision = decide(parse_files(text), parse_labels(args.labels), manifest)
    print(("OK: " if decision.ok else "MISSING: ") + decision.reason)
    for path in decision.triggers[:20]:
        print(f"  changed: {path}")
    return 0 if decision.ok else 1


if __name__ == "__main__":
    sys.exit(main())
