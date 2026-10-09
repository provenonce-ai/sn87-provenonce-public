"""The public-safety gate for release notes (check_release_notes.py, public_words.py).

Forbidden words are built from pieces at run time so that this file passes the same scan that it
tests when it is exported."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


crn = _load("check_release_notes")
pw = sys.modules["public_words"]


def j(*parts: str) -> str:
    return "".join(parts)


def classes(text: str) -> set[str]:
    return {line.split("[", 1)[1].split("]", 1)[0] for line in crn.scan_text(text, "x.md")}


CLEAN = [
    "The demo now scores three public fixtures and prints one row per case.",
    "The sequence of checks is unchanged; a consequence is a clearer error message.",
    "Added `scripts/check_doc_paths.py`, which fails on a dangling link in a document.",
    "A stale authority record is now rejected with a clear reason.",  # lower-case, a protocol term
    "Reports from ops@provenonce.co and a link to https://github.com/example/repo are fine.",
    "Supports Python 3.12 and 3.13 on Linux and macOS; Windows through WSL2.",
    "The docs say mainnet is not supported; this is a testnet release.",
]


@pytest.mark.parametrize("text", CLEAN)
def test_clean_text_passes(text):
    assert crn.scan_text(text, "x.md") == []


BAD = {
    "internal label": [j("the quo", "rum agreed"), j("approval ", "seq", " is recorded"),
                       j("SE", "Q", " 7"), j("Quo", "RUM")],
    "Q7x": [j("see Q", " 7", "3"), j("Q", "-7", "3"), j("see Q", "7", "4"),
            j("Q", "7", "x notes"), j("q", "73")],
    "W-number": [j("W", "-12 lane"), j("W", " 34 work")],
    "W<number>": [j("W", "07 work"), j("fixed in w", "34")],
    "card <number> (any form)": [j("card ", "eight"), j("Card ", "Eleven stays"),
                                 j("card", "-11"), j("Card ", "#4")],
    "card <number>": [j("card ", "11 stays off")],
    j("ste", "ward"): [j("the ste", "ward will tag"), j("STE", "WARD")],
    j("Co", "dex"): [j("a Co", "dex run"), j("co", "dex")],
    j("spr", "int"): [j("a spr", "int goal")],
    "local path": [j("/Us", "ers/someone/x"), j("/ho", "me/someone/x"), j("see ~", "/Code/x"),
                   j("/tm", "p/run.json"), j("C:", "\\Us", "ers\\x")],
    "email": [j("write to someone", "@gmail.com"), j("a.b", "@example.org")],
    "host": [j("see https://", "example.com/x")],
    "ip": [j("at 10.", "1.2.3")],
    "token/market words": [j("a to", "ken was set"), j("the emis", "sions fall"),
                           j("the yie", "ld rises"), j("the pri", "ce of it"),
                           j("TA", "O on testnet"), j("PRI", "CING"), j("sta", "ked funds")],
    "economics": [j("the trea", "sury holds"), j("the rewa", "rds"), j("the reve", "nue")],
    "customer": [j("a cust", "omer asked"), j("Cust", "omers")],
    "mainnet date": [j("Main", "net goes live in November"), j("main", "net is going live soon"),
                     j("main", "net will go live"), j("main", "net went live"),
                     j("main", "net launches in October"), j("main", "net on 12 Oct"),
                     j("main", "net in 2027"), j("by Q", "3, mainnet"),
                     j("go-live of main", "net")],
    "em dash": [j("one ", chr(0x2014), " two")],
    j("robu", "st"): [j("a robu", "st design")],
    "slop": [j("unl", "ock the value"), j("a jour", "ney")],
}


@pytest.mark.parametrize("name,text", [(n, t) for n, ts in BAD.items() for t in ts])
def test_each_class_of_forbidden_text_is_caught_case_insensitively(name, text):
    found = classes(text)
    assert name in found, (text, found)
    assert name in classes(text.upper()) or name in ("email", "host", "ip", "local path")
    assert name in classes(text.lower()) or name in ("email", "host", "ip", "local path",
                                                      "token/market words")


def test_mainnet_without_a_date_or_launch_word_is_not_a_hit():
    assert classes("Mainnet is not supported by this release.") == set()
    assert classes("mainnet may be added later, on no schedule") == set()
    assert classes("Do not claim mainnet use without evidence.") == set()


@pytest.mark.parametrize("slug", [j("quo", "rum-fix"), j("w", "34-thing"), j("ste", "ward-note"),
                                  j("q", "73-sync"), j("quo", "rum_fix"), j("se", "q-12"),
                                  j("card", "-11"), j("co", "dex-run"), j("main", "net-june")])
def test_file_names_are_scanned_with_the_same_list(tmp_path, slug):
    root = write(tmp_path, {f"changes/{slug}.fixed.md": "A plain sentence.\n"})
    problems = crn.check_tree(root)
    assert any(p.startswith(f"changes/{slug}.fixed.md:") and "file name" in p
               for p in problems), problems


def test_archive_paths_and_other_suffixes_are_scanned_too(tmp_path):
    bad = j("quo", "rum")
    root = write(tmp_path, {f"changes/archive/0.1.0/{bad}-x.docs.md": "Fine.\n",
                            f"changes/{bad}.txt": "Fine.\n"})
    names = sorted(p.split(":")[0] for p in crn.check_tree(root) if "file name" in p)
    assert names == [f"changes/archive/0.1.0/{bad}-x.docs.md", f"changes/{bad}.txt"]


def test_ordinary_file_names_pass(tmp_path):
    root = write(tmp_path, {"changes/sequence-check.fixed.md": "Fine.\n",
                            "changes/archive/0.1.0/uid-table.added.md": "Fine.\n",
                            "changes/pr-142.docs.md": "Fine.\n"})
    assert crn.check_tree(root) == []


def test_word_boundaries_avoid_false_positives():
    assert classes("sequence sequential consequences bronx marketing card-board discard") == set()
    assert classes("seqtool and subsequent") == set()


def test_tao_is_matched_only_in_capitals():
    assert "token/market words" in classes(j("test TA", "O"))
    assert classes("the tao of things") == set()


def test_nothing_is_allow_listed_in_release_notes():
    """Digest-bound identifiers that the tree scan accepts are still hits here."""
    assert "W<number>" in classes(j("the profile GRA-W", "03-3 is unchanged"))


def test_hits_report_file_line_class_and_excerpt():
    found = crn.scan_text("fine line\nthe " + j("quo", "rum") + " said\n", "CHANGELOG.md")
    assert found == [f"CHANGELOG.md:2: [internal label] the {j('quo', 'rum')} said"]


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


def test_tree_scan_covers_changelog_fragments_archive_readme_and_notes(tmp_path):
    bad = j("the quo", "rum")
    root = write(tmp_path, {
        "CHANGELOG.md": f"# Changelog\n\n- {bad}\n",
        "changes/a.added.md": f"{bad}.\n",
        "changes/README.md": f"{bad}\n",
        "changes/archive/0.1.0/old.fixed.md": f"{bad}\n",
        "other.md": f"{bad}\n",
    })
    notes = write(tmp_path / "gen", {"RELEASE_NOTES_0.1.0.md": f"{bad}\n"})
    problems = crn.check_tree(root, [notes / "RELEASE_NOTES_0.1.0.md"])
    assert sorted(p.split(":")[0] for p in problems) == [
        "CHANGELOG.md", "RELEASE_NOTES_0.1.0.md", "changes/README.md",
        "changes/a.added.md", "changes/archive/0.1.0/old.fixed.md"]


def test_fragment_names_and_shape_are_checked(tmp_path):
    root = write(tmp_path, {
        "changes/good.added.md": "A plain sentence.\n",
        "changes/wrongtype.feature.md": "A plain sentence.\n",
        "changes/notype.md": "A plain sentence.\n",
        "changes/Upper.fixed.md": "A plain sentence.\n",
        "changes/bullet.docs.md": "- a list item\n",
        "changes/empty.docs.md": "\n",
        "changes/long.docs.md": "word " * 200,
    })
    problems = crn.check_fragments(root)
    assert sorted(p.split(":")[0] for p in problems) == [
        "changes/Upper.fixed.md", "changes/bullet.docs.md", "changes/empty.docs.md",
        "changes/long.docs.md", "changes/notype.md", "changes/wrongtype.feature.md"]


def test_cli_exit_codes(tmp_path, capsys):
    clean = write(tmp_path / "clean", {"CHANGELOG.md": "# Changelog\n",
                                       "changes/a.added.md": "A plain sentence.\n"})
    assert crn.main(["--root", str(clean)]) == 0
    assert "OK" in capsys.readouterr().out
    dirty = write(tmp_path / "dirty", {"changes/a.added.md": j("the quo", "rum"), })
    assert crn.main(["--root", str(dirty)]) == 1
    out = capsys.readouterr().out
    assert "changes/a.added.md:1: [internal label]" in out and "FAIL" in out


def test_this_repository_is_clean():
    assert crn.check_tree(ROOT) == []


def test_the_list_is_shared_with_the_export_builder():
    """One list: the release gate's patterns contain every tree-wide pattern, by identity."""
    release = pw.release_patterns()
    for name, rx in pw.tree_wide().items():
        assert release[name] == rx
    spec = ROOT / "scripts/export_public.py"
    if spec.is_file():  # absent in the exported tree
        ep = _load("export_public")
        assert pw.tree_wide() == ep.FORBIDDEN
