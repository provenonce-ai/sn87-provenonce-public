"""Words, paths and identifiers that must not appear in public text, and the scanner for them.

One list for every public-safety check: the export builder (``export_public.py``, private) scans
the whole exported tree with it, and ``check_release_notes.py`` scans the change notes with it in
both repositories. This module carries the rules that are safe to publish. The patterns that
name people, organisations and internal agents are not published: they live in a private
companion module (not exported) that this module loads when it is present, so the private
repository and the export self-check apply them and the public CI applies the rest.

This file is exempt from the tree scan (see ``SELF_EXEMPT``) because its patterns match
themselves; it is small and reviewed by hand.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELF_EXEMPT = {"scripts/public_words.py"}

ALLOWED_EMAILS = {"ops@provenonce.co"}
ALLOWED_EMAIL_SUFFIX = "@users.noreply.github.com"
ALLOWED_IPS = {"127.0.0.1"}
ALLOWED_HOSTS = {"github.com", "docs.astral.sh", "provenonce.ai", "img.shields.io",
                 "127.0.0.1", "example.invalid", "test.chain.opentensor.ai",
                 "www.w3.org"}  # w3.org: the SVG namespace identifier, not a link

# name -> regex. Zero hits are required in every file of the export tree (case-sensitive there).
TREE_WIDE = {
    "W<number>": r"\bW[0-9]+\b",
    "sprint": r"[Ss]print",
    "card <number>": r"[Cc]ard [0-9]",
    "Codex": r"Codex",
    "steward": r"steward",
    "Q72/Q73": r"Q7[23]",
    "/Users/": r"/Users/",
    "Dropbox": r"Dropbox",
    "robust": r"robust",
    "economics": r"(?i)\b(revenue|rewards?|staking|tokenomics|dTAO|apy|treasury|profit\w*)\b",
    "em dash": "—",
    "private-run-state": r"private-run-state",
    "slop": (r"delve|tapestry|leverag|seamless|cutting-edge|game-changing|revolutionary|"
             r"state-of-the-art|unlock|journey|elevate|supercharge"),
}

_MONTH_FULL = (r"(?:january|february|march|april|june|july|august|september|october|november|"
               r"december)\b")
_MONTH_DAY = (r"(?:january|february|march|april|may|june|july|august|september|october|november|"
              r"december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b")  # needs a day number
_LIVE = r"\bgo(?:es|ing)?[ -]?live\b|\bwent live\b|\blive (?:in|on|by)\b|\blaunch"
_DATE = (r"(?:\b20[0-9]{2}\b|\bQ ?[1-4]\b|\b" + _MONTH_FULL + r"|\b" + _MONTH_DAY +
         r"\.?\s+[0-9]{1,2}\b|\b[0-9]{1,2}\s+" + _MONTH_DAY + r"|" + _LIVE + r")")
# the word mainnet and a date or launch word in the same sentence, in either order
MAINNET_DATE = r"mainnet\b[^\n.]{0,80}" + _DATE + r"|" + _DATE + r"[^\n.]{0,80}mainnet\b"

_NUMBER_WORDS = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                 r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)")

# Additions that apply to release and change notes only (CHANGELOG.md, changes/**, generated
# notes), which are scanned case-insensitively. They are too broad for the whole tree: the
# protocol documents use some of these words in their technical sense.
RELEASE_EXTRA = {
    "internal label": r"\b(quorum|seq)\b",
    "Q7x": r"\bQ[- ]?7[0-9x]\b",
    "W-number": r"\bW[- ][0-9]+\b",
    "card <number> (any form)": (r"\bcards?[ -]?#?(?:[0-9]+|" + _NUMBER_WORDS + r")\b"),
    "local path": (r"(?:/Users/|/home/[A-Za-z0-9._-]+|/private/(?:tmp|var)|/var/folders|"
                   r"/tmp/|~/|[A-Za-z]:\\+Users)"),
    "token/market words": (r"\b(tokens?|emissions?|yields?|prices?|pricing|stak(?:e|es|ed)|"
                           r"airdrops?|(?-i:TAO))\b"),
    "customer": r"\bcustomers?\b",
    "mainnet date": MAINNET_DATE,
}


def _load_named() -> dict[str, str]:
    path = HERE / "public_words_private.py"
    if not path.is_file():
        return {}
    spec = importlib.util.spec_from_file_location("public_words_private", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.NAMED)


NAMED = _load_named()


def tree_wide() -> dict[str, str]:
    """Every tree-wide pattern, including the unpublished named ones when this checkout has them."""
    return {**TREE_WIDE, **NAMED}


def release_patterns() -> dict[str, str]:
    """Patterns for release notes: everything tree-wide plus the release additions."""
    return {**tree_wide(), **RELEASE_EXTRA}


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
HOST = re.compile(r"(?:https?|wss?)://([A-Za-z0-9.-]+)")


def new_hits(patterns: dict[str, str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {name: [] for name in patterns}
    hits["email"], hits["ip"], hits["host"] = [], [], []
    return hits


def scan_text(text: str, rel: str, patterns: dict[str, str], hits: dict[str, list[str]],
              accepted_tokens: dict[str, tuple[str, ...]] | None = None,
              accepted: dict[str, list[str]] | None = None,
              ignore_case: bool = False) -> None:
    """Add the ``rel:line`` of every hit in ``text`` to ``hits`` (made by ``new_hits``).

    A line whose only hits of a pattern are ``accepted_tokens`` is not a hit; it is appended to
    ``accepted`` (when given). Release scans pass no accepted tokens: nothing is allow-listed."""
    flags = re.IGNORECASE if ignore_case else 0
    compiled = {name: re.compile(rx, flags) for name, rx in patterns.items()}
    for number, line in enumerate(text.splitlines(), 1):
        where = f"{rel}:{number}"
        for name, rx in compiled.items():
            if not rx.search(line):
                continue
            stripped = line
            for token in (accepted_tokens or {}).get(name, ()):
                stripped = stripped.replace(token, " ")
            if rx.search(stripped):
                hits[name].append(where)
            elif accepted is not None:
                accepted.setdefault(name, []).append(where)
        for found in EMAIL.findall(line):
            if found not in ALLOWED_EMAILS and not found.endswith(ALLOWED_EMAIL_SUFFIX):
                hits["email"].append(f"{where} {found}")
        for found in HOST.findall(line):
            if found not in ALLOWED_HOSTS:
                hits["host"].append(f"{where} {found}")
        for found in IP.findall(line):
            if found not in ALLOWED_IPS and all(int(p) <= 255 for p in found.split(".")):
                hits["ip"].append(f"{where} {found}")
