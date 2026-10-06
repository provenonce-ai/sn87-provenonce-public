"""PUBLIC_MANIFEST.json classifies every tracked file exactly once (scripts/check_manifest.py)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("check_manifest",
                                                  ROOT / "scripts/check_manifest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def _manifest() -> dict:
    return json.loads((ROOT / "PUBLIC_MANIFEST.json").read_text())


def test_every_tracked_file_is_classified_exactly_once():
    result = _load().check_repo()
    assert result.files
    assert result.unmatched == [], "classify these files in PUBLIC_MANIFEST.json"
    assert result.overlaps == [], "these files match more than one manifest class"
    assert result.ok


def test_manifest_has_no_static_unclassified_list():
    """Coverage is computed by the check, not asserted by a hand-kept list."""
    assert "unclassified" not in _manifest()


def test_an_unlisted_file_fails():
    cm = _load()
    files = [*cm.tracked_files(), "scripts/not_in_the_manifest.py"]
    result = cm.check(_manifest(), files)
    assert result.unmatched == ["scripts/not_in_the_manifest.py"]
    assert result.overlaps == []
    assert not result.ok


def test_an_overlapping_file_fails():
    cm = _load()
    files = cm.tracked_files()
    # any tracked file that the manifest classifies allow (present in the private repository
    # and in the exported tree alike)
    victim = next(f for f, c in cm.check(_manifest(), files).classified.items() if c == "allow")
    manifest = _manifest()
    manifest["deny"].append({"globs": [victim], "why": "test overlap"})
    result = cm.check(manifest, files)
    assert result.overlaps == [(victim, ["deny", "allow"])]
    assert result.classified[victim] == "deny"  # precedence
    assert result.unmatched == []
    assert not result.ok


def test_precedence_is_deny_then_private_then_review_required_then_allow():
    assert _load().CLASSES == ("deny", "private", "review_required", "allow")
    assert _manifest()["precedence"] == list(_load().CLASSES)


def test_private_beats_allow_and_review_required_must_stay_empty():
    cm = _load()
    files = ["a.py", "b.py"]
    manifest = {"allow": [{"globs": ["a.py", "b.py"], "why": "x"}],
                "private": [{"globs": ["b.py"], "why": "x"}]}
    result = cm.check(manifest, files)
    assert result.classified == {"a.py": "allow", "b.py": "private"}
    assert result.overlaps == [("b.py", ["private", "allow"])]
    manifest = {"review_required": [{"globs": ["a.py"], "why": "x"}],
                "allow": [{"globs": ["b.py"], "why": "x"}]}
    result = cm.check(manifest, files)
    assert result.undecided == ["a.py"] and not result.ok
    assert _manifest()["review_required"] == []


def test_glob_semantics():
    rx = _load().glob_regex
    assert rx("**/.env*").match(".env") and rx("**/.env*").match("a/b/.env.local")
    assert rx("tests/*.py").match("tests/x.py") and not rx("tests/*.py").match("tests/a/x.py")
    assert rx("tests/**").match("tests/a/b/x.py")


def test_walk_fallback_without_git(tmp_path, monkeypatch):
    cm = _load()
    for path in ("README.md", "src/a.py", ".git/HEAD", ".venv/lib/x.py",
                 "src/__pycache__/a.pyc", ".pytest_cache/v"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("x")

    def no_git(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(cm.subprocess, "run", no_git)
    assert sorted(cm.tracked_files(tmp_path)) == ["README.md", "src/a.py"]


def test_cli_exits_zero_at_head():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/check_manifest.py")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip().endswith("OK")
