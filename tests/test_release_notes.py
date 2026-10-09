"""Assembling change fragments into release notes (scripts/release_notes.py), on throwaway git
repositories. Forbidden words are built from pieces so this file passes the scan it tests."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts/release_notes.py")
rn = importlib.util.module_from_spec(spec)
sys.modules["release_notes"] = rn
spec.loader.exec_module(rn)

GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@users.noreply.github.com"]
CHANGELOG = """# Changelog

Intro text.

## Unreleased

Pending notes live in `changes/`.

## Before the first release

- Older entry.
"""
FRAGMENTS = {
    "changes/README.md": "# Change notes\n",
    "changes/10.fixed.md": "Fixed ten.\n",
    "changes/2.fixed.md": "Fixed two.\n",
    "changes/zeta.added.md": "Added zeta,\nwrapped over two lines.\n",
    "changes/alpha.added.md": "Added alpha.\n",
    "changes/Beta-not.docs.md.txt": "ignored: not a fragment\n",
    "changes/policy.changed.md": "Changed policy.\n",
    "changes/hole.security.md": "Closed a hole.\n",
    "changes/guide.docs.md": "Wrote a guide.\n",
}


def make_repo(path: Path, fragments=FRAGMENTS, changelog=CHANGELOG, commit=True) -> Path:
    path.mkdir(parents=True)
    (path / "CHANGELOG.md").write_text(changelog)
    for rel, text in fragments.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    (path / ".gitignore").write_text("dist/\n")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if commit:
        subprocess.run(["git", "add", "-A"], cwd=path, check=True)
        subprocess.run([*GIT, "commit", "-qm", "base"], cwd=path, check=True)
    return path


def run(repo: Path, *extra: str, version="0.1.0", date="2026-10-08"):
    return rn.main(["--repo", str(repo), "--version", version, "--date", date, *extra])


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout


EXPECTED_BODY = """### Added

- Added alpha.
- Added zeta, wrapped over two lines.

### Changed

- Changed policy.

### Fixed

- Fixed two.
- Fixed ten.

### Security

- Closed a hole.

### Docs

- Wrote a guide.
"""


def test_release_assembles_changelog_notes_and_archive(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    assert run(repo) == 0
    out = capsys.readouterr().out
    assert "tag name for the maintainer: v0.1.0" in out
    assert (repo / "dist/RELEASE_NOTES_0.1.0.md").read_text() == EXPECTED_BODY
    changelog = (repo / "CHANGELOG.md").read_text()
    assert changelog == (
        "# Changelog\n\nIntro text.\n\n## Unreleased\n\nPending notes live in `changes/`.\n\n"
        "## [0.1.0] - 2026-10-08\n\n" + EXPECTED_BODY
        + "\n## Before the first release\n\n- Older entry.\n")
    archived = git(repo, "ls-files", "changes/archive/0.1.0").split()
    assert archived == [f"changes/archive/0.1.0/{n}" for n in (
        "10.fixed.md", "2.fixed.md", "alpha.added.md", "guide.docs.md", "hole.security.md",
        "policy.changed.md", "zeta.added.md")]
    remaining = sorted(p.name for p in (repo / "changes").iterdir() if p.is_file())
    assert remaining == ["Beta-not.docs.md.txt", "README.md"]
    status = git(repo, "status", "--porcelain")
    assert status.count("R  changes/") == 7  # moved with git mv, not copied and removed
    assert git(repo, "tag", "--list") == ""  # never creates a tag
    assert "dist" not in status  # generated notes are ignored


def test_dry_run_prints_the_notes_and_writes_nothing(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    assert run(repo, "--dry-run") == 0
    out = capsys.readouterr().out
    assert EXPECTED_BODY in out and "changes/alpha.added.md -> changes/archive/0.1.0/" in out
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "dist").exists()


def test_title_goes_into_the_changelog_section_and_the_notes(tmp_path):
    repo = make_repo(tmp_path / "r")
    assert run(repo, "--title", "Public testnet release") == 0
    body = (repo / "dist/RELEASE_NOTES_0.1.0.md").read_text()
    assert body.startswith("Public testnet release\n\n### Added\n")
    assert "## [0.1.0] - 2026-10-08\n\nPublic testnet release\n\n### Added" in (
        repo / "CHANGELOG.md").read_text()


def test_same_input_gives_the_same_bytes(tmp_path):
    a, b = make_repo(tmp_path / "a"), make_repo(tmp_path / "b")
    assert run(a, "--title", "T") == 0 and run(b, "--title", "T") == 0
    for rel in ("CHANGELOG.md", "dist/RELEASE_NOTES_0.1.0.md"):
        assert (a / rel).read_bytes() == (b / rel).read_bytes()
    assert git(a, "ls-files") == git(b, "ls-files")


def test_fragment_order_does_not_depend_on_file_creation_order(tmp_path):
    forward = make_repo(tmp_path / "f")
    backward = make_repo(tmp_path / "b", dict(reversed(list(FRAGMENTS.items()))))
    assert run(forward) == 0 and run(backward) == 0
    assert (forward / "CHANGELOG.md").read_bytes() == (backward / "CHANGELOG.md").read_bytes()


def test_out_names_a_file_or_a_directory(tmp_path):
    repo = make_repo(tmp_path / "r")
    assert run(repo, "--out", str(tmp_path / "elsewhere/notes.md")) == 0
    assert (tmp_path / "elsewhere/notes.md").read_text() == EXPECTED_BODY
    assert not (repo / "dist").exists()
    repo2 = make_repo(tmp_path / "r2")
    (tmp_path / "outdir").mkdir()
    assert run(repo2, "--out", str(tmp_path / "outdir")) == 0
    assert (tmp_path / "outdir/RELEASE_NOTES_0.1.0.md").read_text() == EXPECTED_BODY


def test_a_second_release_of_the_same_version_is_refused(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    assert run(repo) == 0
    before = (repo / "CHANGELOG.md").read_bytes()
    (repo / "changes/new.fixed.md").write_text("Another fix.\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    capsys.readouterr()
    assert run(repo) == 1
    assert "already has a section for 0.1.0" in capsys.readouterr().err
    assert (repo / "CHANGELOG.md").read_bytes() == before
    assert (repo / "changes/new.fixed.md").exists()


def test_an_existing_archive_directory_is_refused(tmp_path, capsys):
    repo = make_repo(tmp_path / "r", {**FRAGMENTS, "changes/archive/0.2.0/x.added.md": "Old.\n"})
    assert run(repo, version="0.2.0") == 1
    assert "changes/archive/0.2.0 already exists" in capsys.readouterr().err
    assert "0.2.0" not in (repo / "CHANGELOG.md").read_text()


def test_no_fragments_is_refused(tmp_path, capsys):
    repo = make_repo(tmp_path / "r", {"changes/README.md": "# Change notes\n"})
    assert run(repo) == 1
    assert "nothing to release" in capsys.readouterr().err


@pytest.mark.parametrize("version,date,message", [
    ("v0.1.0", "2026-10-08", "--version"), ("0.1", "2026-10-08", "--version"),
    ("01.2.3", "2026-10-08", "--version"), ("0.1.0", "08/10/2026", "--date"),
    ("0.1.0", "2026-13-01", "--date"), ("0.1.0", "2026-1-1", "--date")])
def test_bad_version_or_date_is_refused(tmp_path, capsys, version, date, message):
    repo = make_repo(tmp_path / "r")
    assert run(repo, version=version, date=date) == 1
    assert message in capsys.readouterr().err
    assert git(repo, "status", "--porcelain") == ""


def test_unsafe_text_is_refused_and_nothing_is_written(tmp_path, capsys):
    bad = {**FRAGMENTS, "changes/leak.added.md": "Agreed by the " + "quo" + "rum.\n"}
    repo = make_repo(tmp_path / "r", bad)
    assert run(repo) == 1
    err = capsys.readouterr().err
    assert "public-safety check failed" in err and "changes/leak.added.md" in err
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "changes/archive").exists() and not (repo / "dist").exists()


def test_unsafe_text_already_in_the_changelog_is_refused(tmp_path, capsys):
    repo = make_repo(tmp_path / "r", changelog=CHANGELOG + "- see /Us" + "ers/x\n")
    assert run(repo) == 1
    assert "CHANGELOG.md" in capsys.readouterr().err


@pytest.mark.parametrize("name,text", [
    ("x.feature.md", "Text.\n"), ("noext.md", "Text.\n"), ("Up.added.md", "Text.\n"),
    ("empty.added.md", "  \n"), ("bullet.added.md", "- item\n"), ("heading.added.md", "# H\n"),
    ("long.added.md", "word " * 200)])
def test_malformed_fragments_are_refused(tmp_path, capsys, name, text):
    repo = make_repo(tmp_path / "r", {**FRAGMENTS, f"changes/{name}": text})
    assert run(repo) == 1
    assert name in capsys.readouterr().err
    assert git(repo, "status", "--porcelain") == ""


def test_untracked_fragments_are_refused_with_a_clear_message(tmp_path, capsys):
    repo = make_repo(tmp_path / "r", commit=False)
    assert run(repo) == 1
    assert "commit these fragments first" in capsys.readouterr().err
    assert not (repo / "changes/archive").exists()
    assert "0.1.0" not in (repo / "CHANGELOG.md").read_text()


def test_insert_section_positions():
    section = "## [1.0.0] - 2026-01-01\n\n### Added\n\n- X.\n"
    assert rn.insert_section("# C\n\n## Unreleased\n\ntext\n\n## Old\n\n- o\n", section) == (
        "# C\n\n## Unreleased\n\ntext\n\n" + section + "\n## Old\n\n- o\n")
    assert rn.insert_section("# C\n\n## Old\n\n- o\n", section) == (
        "# C\n\n" + section + "\n## Old\n\n- o\n")
    assert rn.insert_section("# C\n\n## Unreleased\n\ntext\n", section) == (
        "# C\n\n## Unreleased\n\ntext\n\n" + section)
    with pytest.raises(rn.ReleaseError):
        rn.insert_section("# C\n", section)


def test_natural_sort_compares_digits_as_numbers():
    slugs = ["10", "2", "pr-10", "pr-9", "b", "a1", "a10", "a2"]
    assert sorted(slugs, key=rn._natural) == ["2", "10", "a1", "a2", "a10", "b", "pr-9", "pr-10"]


def test_this_repositorys_fragments_assemble_cleanly(tmp_path, capsys):
    """A dry run on a copy of the real fragments and CHANGELOG.md.

    Uses a version no release has used, so it keeps passing after a release. Right after one the
    fragments are archived, there is nothing to assemble, and the test is skipped.
    """
    if not [p for p in (ROOT / "changes").glob("*.*.md") if p.name != "README.md"]:
        pytest.skip("no unreleased fragments in changes/")
    repo = make_repo(tmp_path / "r", {
        f"changes/{p.name}": p.read_text() for p in (ROOT / "changes").iterdir() if p.is_file()},
        changelog=(ROOT / "CHANGELOG.md").read_text())
    assert run(repo, "--dry-run", "--title", "Public testnet release", version="99.0.0") == 0
    out = capsys.readouterr().out
    assert "### Added" in out and "v99.0.0" in out


def test_a_failing_move_leaves_nothing_behind(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path / "r")
    real_run, calls = subprocess.run, []

    def flaky(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "mv"] and "archive" in cmd[-1]:  # forward moves only
            calls.append(cmd)
            if len(calls) == 4:
                return subprocess.CompletedProcess(cmd, 1, "", "simulated failure")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(rn.subprocess, "run", flaky)
    assert run(repo) == 1
    assert "simulated failure" in capsys.readouterr().err
    assert len(calls) == 4
    assert not (repo / "changes/archive").exists() and not (repo / "dist").exists()
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / "CHANGELOG.md").read_text() == CHANGELOG
    monkeypatch.setattr(rn.subprocess, "run", real_run)
    assert run(repo) == 0  # and the release can be done afterwards


def test_fragment_file_names_are_checked_with_the_word_list(tmp_path, capsys):
    bad = {**FRAGMENTS, "changes/" + "quo" + "rum-fix.fixed.md": "A plain sentence.\n"}
    repo = make_repo(tmp_path / "r", bad)
    assert run(repo) == 1
    err = capsys.readouterr().err
    assert "file name" in err and "-fix.fixed.md" in err
    assert git(repo, "status", "--porcelain") == ""


def test_a_fragment_with_staged_or_unstaged_changes_is_refused(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    (repo / "changes/alpha.added.md").write_text("Edited after the commit.\n")  # unstaged
    assert run(repo) == 1
    assert "staged or unstaged changes" in capsys.readouterr().err
    (repo / "changes/alpha.added.md").write_text("Added alpha.\n")
    (repo / "changes/guide.docs.md").write_text("Edited and staged.\n")
    subprocess.run(["git", "add", "changes/guide.docs.md"], cwd=repo, check=True)
    assert run(repo) == 1
    assert "changes/guide.docs.md" in capsys.readouterr().err
    assert not (repo / "changes/archive").exists() and not (repo / "dist").exists()
    assert (repo / "CHANGELOG.md").read_text() == CHANGELOG


def test_a_dry_run_warns_about_a_modified_fragment_but_still_prints(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    (repo / "changes/alpha.added.md").write_text("Edited.\n")
    assert run(repo, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "WARNING: a real run would refuse" in out and "Edited." in out


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root ignores directory permissions")
def test_an_unwritable_out_is_refused_before_anything_changes(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert run(repo, "--out", str(locked / "sub/notes.md")) == 1
        assert "not a writable directory" in capsys.readouterr().err
    finally:
        locked.chmod(0o700)
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "changes/archive").exists()


def test_an_out_below_a_file_or_equal_to_a_directory_is_refused(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    assert run(repo, "--out", str(blocker / "notes.md")) == 1
    assert "nothing written" in capsys.readouterr().err
    assert git(repo, "status", "--porcelain") == ""


def test_a_late_write_failure_puts_everything_back(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path / "r")
    out = tmp_path / "newdir/deeper/notes.md"
    real = Path.write_text

    def fail_on_notes(self, *args, **kwargs):
        if self.name == "notes.md":
            raise PermissionError("simulated disk failure")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_notes)
    assert run(repo, "--out", str(out)) == 1
    assert "everything was put back" in capsys.readouterr().err
    monkeypatch.setattr(Path, "write_text", real)
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / "CHANGELOG.md").read_text() == CHANGELOG
    assert not (repo / "changes/archive").exists()
    assert not (tmp_path / "newdir").exists()
    assert run(repo, "--out", str(out)) == 0  # and a retry works


def test_a_changelog_write_failure_puts_the_moves_back(tmp_path, capsys, monkeypatch):
    repo = make_repo(tmp_path / "r")
    real = Path.write_text

    def fail_on_changelog(self, *args, **kwargs):
        if self.name == "CHANGELOG.md":
            raise PermissionError("simulated")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_on_changelog)
    assert run(repo) == 1
    monkeypatch.setattr(Path, "write_text", real)
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "changes/archive").exists() and not (repo / "dist").exists()


def test_a_read_only_changelog_is_refused_up_front(tmp_path, capsys):
    repo = make_repo(tmp_path / "r")
    (repo / "CHANGELOG.md").chmod(0o444)
    if os.access(repo / "CHANGELOG.md", os.W_OK):
        pytest.skip("permissions are not enforced here")
    assert run(repo) == 1
    assert "CHANGELOG.md is not writable" in capsys.readouterr().err
    assert not (repo / "changes/archive").exists()
