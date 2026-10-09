"""When a pull request needs a change note (scripts/check_fragment_required.py)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("check_fragment_required",
                                              ROOT / "scripts/check_fragment_required.py")
cfr = importlib.util.module_from_spec(spec)
sys.modules["check_fragment_required"] = cfr
spec.loader.exec_module(cfr)


def files(*paths, status="modified"):
    return [(status, p) for p in paths]


@pytest.mark.parametrize("path", [
    "src/sn87_provenonce/scoring.py", "scripts/miner_serve.py", "docs/quickstart/miner.md",
    "README.md", "CONTRIBUTING.md", "LIMITATIONS.md", "SECURITY.md", "PROVENANCE.md"])
def test_a_change_to_code_or_public_documents_needs_a_note(path):
    decision = cfr.decide(files(path), set())
    assert not decision.ok and decision.triggers == [path]
    assert "no-changelog" in decision.reason and "changes/<name>.<type>.md" in decision.reason


@pytest.mark.parametrize("path", [
    "tests/test_scoring.py", "uv.lock", "pyproject.toml", ".github/workflows/ci.yml",
    "PUBLIC_MANIFEST.json", "attestation/README.md", "AGENTS.md", "changes/README.md"])
def test_other_paths_need_no_note(path):
    assert cfr.decide(files(path), set()).ok


@pytest.mark.parametrize("path", ["changes/42.fixed.md", "changes/new-thing.added.md",
                                  "changes/x.security.md",
                                  "changes/x.changed.md"])
def test_an_added_note_satisfies_the_rule(path):
    decision = cfr.decide([("modified", "src/a.py"), ("added", path)], set())
    assert decision.ok and decision.notes == [path]


@pytest.mark.parametrize("path", ["changes/x.feature.md", "changes/x.md", "changes/README.md",
                                  "changes/archive/0.1.0/x.added.md", "docs/x.added.md",
                                  "changes/x.added.txt"])
def test_files_that_are_not_notes_do_not_satisfy_it(path):
    assert not cfr.decide([("modified", "src/a.py"), ("added", path)], set()).ok


@pytest.mark.parametrize("status", ["modified", "removed", "copied", "changed", "unchanged"])
def test_only_an_added_or_renamed_note_counts(status):
    assert not cfr.decide([("modified", "src/a.py"), (status, "changes/x.added.md")], set()).ok


def test_a_rename_out_of_a_covered_path_needs_a_note():
    """The workflow lists a renamed file under both names; the old name is a removal."""
    listing = cfr.parse_files("renamed\ttests/moved.py\nremoved\tsrc/sn87_provenonce/old.py\n")
    assert not cfr.decide(listing, set()).ok
    assert cfr.decide(listing + [("added", "changes/x.changed.md")], set()).ok
    assert cfr.decide(listing, {"no-changelog"}).ok
    # a rename inside tests/ touches nothing covered
    assert cfr.decide(cfr.parse_files("renamed\ttests/b.py\nremoved\ttests/a.py\n"), set()).ok


def test_the_workflow_lists_the_previous_name_of_a_renamed_file():
    text = (ROOT / ".github/workflows/changelog.yml").read_text()
    assert "previous_filename" in text and "removed" in text


def test_a_note_renamed_into_place_counts():
    assert cfr.decide([("modified", "src/a.py"), ("renamed", "changes/x.added.md")], set()).ok


@pytest.mark.parametrize("path", ["changes/Upper.added.md", "changes/UPPER.fixed.md",
                                  "changes/a.b.docs.md", "changes/-x.added.md",
                                  "changes/sp ace.added.md", "changes/x.ADDED.md"])
def test_names_the_release_script_rejects_do_not_count(path):
    assert not cfr.decide([("modified", "src/a.py"), ("added", path)], set()).ok


def test_the_accepted_name_pattern_agrees_with_the_release_script():
    spec = importlib.util.spec_from_file_location("release_notes",
                                                  ROOT / "scripts/release_notes.py")
    rn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rn)
    for name in ("a.added.md", "a-b_c.docs.md", "42.fixed.md", "A.added.md", "a.b.docs.md",
                 "a.feature.md", "-a.added.md", "a b.added.md"):
        try:
            rn.parse_name(name)
            accepted = True
        except rn.ReleaseError:
            accepted = False
        assert bool(cfr.FRAGMENT.match(f"changes/{name}")) == accepted, name


def test_the_label_opts_out_whatever_the_files_are():
    assert cfr.decide(files("src/a.py"), {"no-changelog"}).ok
    assert cfr.decide(files("src/a.py"), cfr.parse_labels("bug, No-Changelog")).ok
    assert not cfr.decide(files("src/a.py"), {"bug", "no-changelog-please"}).ok


def test_an_empty_change_list_is_fine():
    assert cfr.decide([], set()).ok


def test_manifest_private_paths_do_not_count():
    manifest = json.loads((ROOT / "PUBLIC_MANIFEST.json").read_text())
    probe = "scripts/flip_gates.py"  # private-class glob in the source repository
    classes = cfr.check_manifest.check(manifest, [probe]).classified
    if classes.get(probe) == "private":  # the shipped manifest empties the private class
        assert cfr.decide(files(probe), set(), manifest).ok
        assert not cfr.decide(files(probe), set(), None).ok
    assert not cfr.decide(files("src/sn87_provenonce/scoring.py"), set(), manifest).ok


def test_parse_files_accepts_paths_and_status_lines():
    assert cfr.parse_files("src/a.py\nadded\tchanges/x.added.md\n\r\n\n") == [
        ("modified", "src/a.py"), ("added", "changes/x.added.md")]
    assert cfr.parse_labels("a,b\nc, ,") == {"a", "b", "c"}


def test_cli(tmp_path, capsys):
    listing = tmp_path / "files.txt"
    listing.write_text("modified\tsrc/a.py\n")
    assert cfr.main(["--files", str(listing), "--labels", "bug"]) == 1
    assert "MISSING" in capsys.readouterr().out
    assert cfr.main(["--files", str(listing), "--labels", "bug,no-changelog"]) == 0
    listing.write_text("modified\tsrc/a.py\nadded\tchanges/a.added.md\n")
    assert cfr.main(["--files", str(listing)]) == 0
    assert "OK" in capsys.readouterr().out


def test_the_workflow_wires_the_script_with_minimal_permissions_and_pinned_actions():
    text = (ROOT / ".github/workflows/changelog.yml").read_text()
    assert "scripts/check_fragment_required.py" in text
    assert "pull_request:" in text and "pull_request_target" not in text
    assert "permissions: {}" in text and "pull-requests: read" in text
    assert "write" not in text.replace("persist-credentials", "")
    uses = [ln.split("uses:")[1].split("#")[0].strip() for ln in text.splitlines() if "uses:" in ln]
    assert uses and all("@" in u and len(u.split("@")[1]) == 40 for u in uses)
    assert "no-changelog" in (ROOT / "scripts/check_fragment_required.py").read_text()
