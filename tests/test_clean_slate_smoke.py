"""The newcomer page and its smoke script share one source of commands.

``docs/guides/start-here.md`` is the only list of commands. ``scripts/clean_slate_smoke.py`` reads
it with the guide parser instead of keeping a copy, so these tests pin what the page must keep
(the setup, the worked example, no network, the four levels, the verdicts) and the mechanics of
the clean clone. The full run (a clone, a uv sync, every command of the page) is slow and is
skipped unless ``SN87_RUN_CLEAN_SLATE_SMOKE`` is set; CI runs it as its own job.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PAGE = ROOT / "docs" / "guides" / "start-here.md"

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None,
                                reason="the smoke script needs git and bash")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load("clean_slate_smoke")
run_guide = _load("run_guide")


def _guide():
    return run_guide.parse_guide(PAGE.read_text(encoding="utf-8"), PAGE)


def test_the_smoke_script_runs_exactly_the_commands_of_the_page():
    steps = smoke.page_steps(ROOT)
    guide = _guide()
    assert steps == [(s.id, s.command) for s in guide.steps]
    assert len({step_id for step_id, _ in steps}) == len(steps)


def test_the_page_carries_the_setup_and_the_worked_example_as_commands():
    commands = "\n".join(command for _, command in smoke.page_steps(ROOT))
    for needed in ("git clone https://github.com/provenonce-ai/sn87-provenonce-public",
                   "uv sync --locked", "sn87-provenonce demo",
                   "scripts/staging_subnet.py --truth golden",
                   "scripts/verify_attestation.py"):
        assert needed in commands, needed
    # the setup command the smoke script warms the cache with is the one the page runs
    assert " ".join(smoke.SETUP) in commands


def test_no_step_of_the_page_needs_the_network_or_a_key():
    guide = _guide()
    assert guide.steps and not any(step.network or step.requires_valkey for step in guide.steps)
    for step in guide.steps:
        assert "--network" not in step.command
    # the verifier only ever gets a loopback address on this page
    for step in guide.steps:
        if "verify_attestation.py" in step.command:
            assert "--endpoint http://127.0.0.1:" in step.command


def test_the_page_keeps_what_a_newcomer_needs():
    text = PAGE.read_text(encoding="utf-8")
    assert smoke.check_text(text) == []
    assert smoke.check_text("nothing here") != []


def test_the_page_says_it_reaches_level_one_only_and_promises_nothing():
    text = PAGE.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| 1. Local example"))
    assert "**Yes**" in row
    for level in ("2. Shadow participation", "3. Independent validation", "4. Weighted"):
        line = next(ln for ln in text.splitlines() if ln.startswith(f"| {level}"))
        assert "**Yes**" not in line, level
    assert "promises no date and no payout" in text


def test_the_page_and_the_script_pass_the_public_word_gate():
    public_words = _load("public_words")
    patterns = public_words.tree_wide()
    for path in (PAGE, ROOT / "scripts" / "clean_slate_smoke.py", Path(__file__)):
        hits = public_words.new_hits(patterns)
        public_words.scan_text(path.read_text(encoding="utf-8"), path.name, patterns, hits)
        assert {name: found for name, found in hits.items() if found} == {}, path.name


def test_the_page_makes_no_forbidden_claim_and_the_checker_sees_one():
    assert smoke.forbidden_claims(PAGE.read_text(encoding="utf-8")) == []
    # the disclaimer is allowed, the same words as a claim are not, and program output is skipped
    ok = f"We say it {smoke.DISCLAIMER}.\n```text expect\nearns a floor\n```\n"
    assert smoke.forbidden_claims(ok) == []
    for bad in ("You will earn more.", "A guarantee of weight.", "Pay" + "out soon.",
                "Opens on March 3.", "Starts in 2027."):
        assert smoke.forbidden_claims(bad), bad
    assert smoke.forbidden_claims("Re" + "wards follow.")


def test_the_prose_numbers_are_guarded_by_expect_blocks():
    text = PAGE.read_text(encoding="utf-8")
    for line in ("attested runs read: 21", "instances, scored: 12", "instances, diagnostic: 4",
                 "integrity predicates: 6", "shadow allowlist entries: 0"):
        assert f"\n{line}\n" in text, line
    assert "75 cases in 2 files" in text
    assert "the other 4, `incomplete`, are\ndiagnostic" in text
    assert smoke.check_allowlist(ROOT) == []


def _repo(path: Path) -> Path:
    path.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(path.parent), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    for args in (["init", "-q", "-b", "main"],
                 ["-c", "user.name=t", "-c", "user.email=t@users.noreply.github.com",
                  "commit", "-q", "--allow-empty", "-m", "first"]):
        subprocess.run(["git", "-C", str(path), *args], env=env, check=True)
    (path / "kept.txt").write_text("committed\n")
    for args in (["add", "kept.txt"],
                 ["-c", "user.name=t", "-c", "user.email=t@users.noreply.github.com",
                  "commit", "-q", "-m", "second"]):
        subprocess.run(["git", "-C", str(path), *args], env=env, check=True)
    return path


def test_the_clone_is_the_committed_head_and_shares_no_objects(tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / "uncommitted.txt").write_text("not in the clone\n")
    clone = tmp_path / "clone"
    head = smoke.clone_head(repo, clone)
    assert head == smoke.git(repo, "rev-parse", "HEAD") == smoke.git(clone, "rev-parse", "HEAD")
    assert (clone / "kept.txt").read_text() == "committed\n"
    assert not (clone / "uncommitted.txt").exists()
    objects = [p for p in (clone / ".git" / "objects").rglob("*") if p.is_file()]
    assert objects and all(p.stat().st_nlink == 1 for p in objects)


def test_uncommitted_changes_are_reported_and_refused(tmp_path, capsys):
    repo = _repo(tmp_path / "repo")
    assert smoke.dirty(repo) == []
    (repo / "kept.txt").write_text("changed\n")
    assert [line.split()[-1] for line in smoke.dirty(repo)] == ["kept.txt"]
    assert smoke.main(["--repo", str(repo)]) == 2
    assert "uncommitted changes" in capsys.readouterr().err


def test_list_prints_the_commands_of_the_page(capsys):
    assert smoke.main(["--list"]) == 0
    printed = capsys.readouterr().out
    assert "[demo]" in printed and "sn87-provenonce demo" in printed


@pytest.mark.skipif(not os.environ.get("SN87_RUN_CLEAN_SLATE_SMOKE"),
                    reason="slow: clones the repository and installs the packages; "
                           "set SN87_RUN_CLEAN_SLATE_SMOKE=1 (CI runs it as the clean-slate job)")
def test_the_full_clean_slate_smoke_run(capsys):
    code = smoke.main(["--allow-dirty"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "PASS clean-slate smoke" in out
