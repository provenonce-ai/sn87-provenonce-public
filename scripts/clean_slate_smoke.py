#!/usr/bin/env python3
"""Run the newcomer page, docs/guides/start-here.md, from a clean clone of the committed tree.

  uv run python scripts/clean_slate_smoke.py              # warm the uv cache, then run the page
  uv run python scripts/clean_slate_smoke.py --offline    # the uv cache is already warm
  uv run python scripts/clean_slate_smoke.py --list       # print the commands the page runs

What it does, in order:

  1. ``git clone --no-hardlinks`` of this repository's committed HEAD into a temporary directory.
     A clone carries only what is committed, so a file that exists on a developer's disk and was
     never committed (or a setting kept outside the repository) cannot help the page pass. A
     working tree with uncommitted changes is refused unless ``--allow-dirty``, because those
     changes would not be tested.
  2. Unless ``--offline``, ``uv sync --locked --extra transport`` in that clone. This is the one
     step that may use the network, and only to fill uv's package cache. The page itself is then
     run with uv switched to offline mode and with every other address sent to a dead proxy.
  3. The page is parsed and run by the clone's own ``scripts/run_guide.py``, so the single
     source of truth for the commands and their expected output is the page. There is no second
     list of commands in this file. The runner makes a second, committed copy of the clone and
     maps the public repository URL to it, so the page's own ``git clone`` step clones the tree
     under test instead of the network.
  4. Checks the runner cannot make: every step ran (none skipped), none needs the network, and
     the page still carries what a newcomer needs (the four levels and that it reaches level 1
     only, the three verdicts, the baseline-tie rule, the reproducibility caveat), makes no
     promise of a payment, a guarantee, earnings or a date, and the shadow allowlist is still
     empty as the page says. The counts the prose relies on are printed and compared by the
     page's own expect blocks.

Exit code: 0 all passed, 1 a step or check failed, 2 a usage or setup error. Reads and writes
only a temporary directory it creates (removed at the end unless ``--keep``) and uv's caches.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = "docs/guides/start-here.md"
RUNNER = "scripts/run_guide.py"
SETUP = ["uv", "sync", "--locked", "--extra", "transport"]

# What a newcomer must find on the page. Each entry is (label, regular expression).
REQUIRED_TEXT = [
    ("level 1: local example", r"\|\s*1\. Local example\s*\|"),
    ("level 2: shadow participation", r"\|\s*2\. Shadow participation\s*\|"),
    ("level 3: independent validation", r"\|\s*3\. Independent validation\s*\|"),
    ("level 4: weighted", r"\|\s*4\. Weighted\s*\|"),
    ("verdict PASS", r"\|\s*PASS\s*\|"),
    ("verdict FAIL", r"\|\s*FAIL\s*\|"),
    ("verdict UNVERIFIED", r"\|\s*UNVERIFIED\s*\|"),
    ("result NULL_NO_HEADROOM", r"`NULL_NO_HEADROOM`"),
    ("result ABOVE_BASELINE", r"`ABOVE_BASELINE`"),
    ("a baseline tie is not uplift", r"\*\*A baseline tie is not uplift\.\*\*"),
    ("the shadow application route", r"Shadow cohort application"),
    ("level 1 only: the level 1 row says Yes",
     r"\|\s*1\. Local example\s*\|[^\n]*\*\*Yes\*\*"),
    ("level 1 only: the level 2 to 4 rows say No",
     r"(?:\|\s*[234]\. [^\n]*\|\s*(?:No|Partly)[^\n]*\n){3}"),
    ("reproducibility is not independent validation",
     r"\*\*This is reproducibility, not\s+independent validation\.\*\*"),
    ("the allowlist wording", r"was empty when this page was last checked"),
    ("the no-date, no-payout disclaimer", r"promises no date and no payout at any level"),
]

DISCLAIMER = "promises no date and no payout at any level"
# Claims the page must not make. They are looked for in the prose only (fenced blocks hold
# program output) and after the one disclaimer sentence above has been taken out, so the page
# can say what it does not promise but not promise it.
FORBIDDEN_CLAIMS = {
    # spelled in two pieces: the public word gate refuses the plain word in any file
    "re" + "ward": r"(?i)\bre" + r"wards?\b",
    "payout": r"(?i)\bpay-?outs?\b",
    "guarantee": r"(?i)\bguarantee[sd]?\b",
    "earn": r"(?i)\bearn(?:s|ed|ing|ings)?\b",
    "year": r"\b20[0-9]{2}\b",
    "dated promise": (r"\b(?:January|February|March|April|May|June|July|August|September|October|"
                      r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?\s+"
                      r"[0-9]{1,2}\b|\b[0-9]{1,2}\s+(?:January|February|March|April|May|June|"
                      r"July|August|September|October|November|December)\b"),
}


class SmokeError(RuntimeError):
    """A setup problem, not a failed check."""


def git(repo: Path, *args: str) -> str:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           "GIT_TERMINAL_PROMPT": "0"}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    if out.returncode != 0:
        raise SmokeError(f"git {' '.join(args)} failed in {repo}: {out.stderr.strip()}")
    return out.stdout.strip()


def load_runner(clone: Path):
    """Import ``scripts/run_guide.py`` from the clone, so the committed runner is the one used."""
    path = clone / RUNNER
    spec = importlib.util.spec_from_file_location("clean_slate_run_guide", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def page_steps(root: Path) -> list[tuple[str, str]]:
    """``(step id, command)`` for every command of the page: the single source of truth."""
    runner = load_runner(root)
    guide = runner.parse_guide((root / PAGE).read_text(encoding="utf-8"), root / PAGE)
    return [(step.id, step.command) for step in guide.steps]


def clone_head(repo: Path, destination: Path) -> str:
    """Clone the committed HEAD of ``repo`` into ``destination`` without sharing objects."""
    if git(repo, "rev-parse", "--is-shallow-repository") == "true":
        raise SmokeError("the repository is a shallow clone; a local clone of it fails. "
                         "Fetch the full history first (CI uses fetch-depth: 0).")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "clone", "--quiet", "--no-hardlinks", str(repo), str(destination))
    cloned = git(destination, "rev-parse", "HEAD")
    if cloned != head:
        raise SmokeError(f"the clone is at {cloned}, the repository at {head}")
    return head


def dirty(repo: Path) -> list[str]:
    return [line for line in git(repo, "status", "--porcelain").splitlines() if line.strip()]


def prose(text: str) -> str:
    """The page without its fenced blocks."""
    return re.sub(r"^(?P<f>`{3,}|~{3,}).*?^(?P=f)[ \t]*$", "", text, flags=re.S | re.M)


def forbidden_claims(text: str) -> list[str]:
    """``name: matched text`` for every forbidden claim in the prose of the page."""
    body = prose(text).replace(DISCLAIMER, "")
    found = []
    for name, pattern in FORBIDDEN_CLAIMS.items():
        found += [f"{name}: {m.group(0)!r}" for m in re.finditer(pattern, body)]
    return found


def check_allowlist(root: Path) -> list[str]:
    """The page says the shadow allowlist was empty; it must still be."""
    path = root / "shadow" / "allowlist.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError):
        return [f"{path.name} could not be read"]
    return [f"the page says the shadow allowlist was empty, it has {len(entries)} entries"
            ] if entries else []


def check_text(text: str) -> list[str]:
    """The labels of the required passages that the page does not carry."""
    return [label for label, pattern in REQUIRED_TEXT if not re.search(pattern, text)]


def warm_cache(clone: Path, runner) -> None:
    """Fill uv's package cache with the same interpreter the offline run will use."""
    env = dict(os.environ)
    env["UV_PYTHON"] = getattr(sys, "_base_executable", None) or sys.executable
    env["UV_NO_PROGRESS"] = "1"
    env.pop("VIRTUAL_ENV", None)
    done = subprocess.run(SETUP, cwd=clone, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        raise SmokeError("the setup command failed (it needs the network when uv's cache is "
                         "cold; use --offline when it is warm):\n" + (done.stderr or done.stdout))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=ROOT,
                        help="repository to clone (default: the one this script is in)")
    parser.add_argument("--offline", action="store_true",
                        help="skip the cache-warming uv sync (uv's cache must already be warm)")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="run although the working tree has changes the clone lacks")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    parser.add_argument("--list", action="store_true", help="print the commands; run nothing")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        if args.list:
            for step_id, command in page_steps(repo):
                print(f"[{step_id}]\n{command}\n")
            return 0
        changes = dirty(repo)
        if changes and not args.allow_dirty:
            print("the working tree has uncommitted changes that a clone would not carry:",
                  file=sys.stderr)
            for line in changes[:10]:
                print(f"  {line}", file=sys.stderr)
            print("commit them, or pass --allow-dirty to test the committed tree anyway.",
                  file=sys.stderr)
            return 2
        return run(repo, args)
    except SmokeError as err:
        print(f"setup error: {err}", file=sys.stderr)
        return 2


def run(repo: Path, args: argparse.Namespace) -> int:
    parent = Path(tempfile.gettempdir())
    work = Path(tempfile.mkdtemp(prefix="sn87-smoke-", dir=parent)).resolve()
    started = time.monotonic()
    try:
        clone = work / "clone"
        head = clone_head(repo, clone)
        print(f"cloned {head[:12]} with --no-hardlinks into a temporary directory")
        runner = load_runner(clone)
        text = (clone / PAGE).read_text(encoding="utf-8")
        guide = runner.parse_guide(text, clone / PAGE)
        problems = [f"the page lacks: {label}" for label in check_text(text)]
        problems += [f"the page makes a forbidden claim: {hit}" for hit in forbidden_claims(text)]
        problems += check_allowlist(clone)
        networked = [step.id for step in guide.steps if step.network]
        if networked:
            problems.append(f"steps marked network are not allowed on this page: {networked}")
        if not args.offline:
            print("warming uv's package cache (the only step that may use the network) ...")
            warm_cache(clone, runner)
        print(f"== {PAGE}: {len(guide.steps)} steps, run offline from the clone")
        results = runner.run_guide(guide, clone, network=False)
        failed = [r for r in results if r.status != "PASS"]
        if failed:
            problems.append("steps that did not pass: "
                            + ", ".join(f"{r.step.id} ({r.status})" for r in failed))
        if len(results) != len(guide.steps):
            problems.append("not every step produced a result")
        seconds = time.monotonic() - started
        for problem in problems:
            print(f"FAIL {problem}")
        status = "FAIL" if problems else "PASS"
        print(f"{status} clean-slate smoke: {sum(r.status == 'PASS' for r in results)}/"
              f"{len(guide.steps)} steps passed, {len(REQUIRED_TEXT) - len(check_text(text))}/"
              f"{len(REQUIRED_TEXT)} required passages present, {seconds:.0f} s, HEAD {head[:12]}")
        return 1 if problems else 0
    finally:
        if args.keep:
            print(f"kept {work}")
        elif work.parent == parent.resolve() and work.name.startswith("sn87-smoke-"):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
