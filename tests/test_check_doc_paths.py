"""scripts/check_doc_paths.py: every repository path cited in a document exists in the tree."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("check_doc_paths",
                                                  ROOT / "scripts/check_doc_paths.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cdp = _load()


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_this_tree_has_no_dangling_path():
    assert cdp.check_links(ROOT) == []
    assert cdp.main(["--root", str(ROOT)]) == 0


def test_existing_path_and_glob_pass(tmp_path):
    root = _tree(tmp_path, {"docs/a.md": "See `scripts/x.py` and scripts/y_*.py.\n",
                            "scripts/x.py": "", "scripts/y_1.py": ""})
    assert cdp.check_links(root) == []


def test_missing_path_reports_file_and_line(tmp_path):
    root = _tree(tmp_path, {"docs/a.md": "ok\nSee tests/pilot/test_transport.py here.\n"})
    assert cdp.check_links(root) == ["docs/a.md:2: path missing: tests/pilot/test_transport.py"]
    assert cdp.main(["--root", str(root)]) == 1


def test_glob_matching_nothing_fails(tmp_path):
    root = _tree(tmp_path, {"docs/a.md": "scripts/pilot_chain_*.py\n"})
    assert len(cdp.check_links(root)) == 1


def test_dangling_markdown_link_fails_and_urls_and_anchors_pass(tmp_path):
    root = _tree(tmp_path, {"docs/a.md": "[gone](missing.md) [web](https://example.invalid/x) "
                                         "[here](#top) [ok](b.md#s)\n", "docs/b.md": ""})
    assert cdp.check_links(root) == ["docs/a.md:1: link target missing: missing.md"]


def test_private_suite_marker_allows_a_private_path_only_when_adjacent(tmp_path):
    root = _tree(tmp_path, {
        "docs/a.md": "`tests/test_golden.py::test_x` (private suite)\n"
                     "`tests/test_golden.py::test_x`\n"})
    assert cdp.check_links(root) == ["docs/a.md:2: path missing: tests/test_golden.py"]


def test_marker_does_not_carry_across_lines(tmp_path):
    root = _tree(tmp_path, {"docs/a.md": "tests/a.py\n(private suite)\n"})
    assert len(cdp.check_links(root)) == 1


def test_python_pointers_checked_only_under_src_and_scripts(tmp_path):
    root = _tree(tmp_path, {"scripts/t.py": '"""See docs/absent.md."""\n',
                            "tests/t.py": '"""See docs/absent.md."""\n'})
    assert cdp.check_links(root) == ["scripts/t.py:1: path missing: docs/absent.md"]


def test_overlay_file_counts_as_present(tmp_path):
    root = _tree(tmp_path, {
        "README.md": "[ci](.github/workflows/conformance.yml) .github/x.yml\n"
                     "See export/overlay/.github/workflows/conformance.yml\n",
        "export/overlay/.github/workflows/conformance.yml": ""})
    assert cdp.check_links(root) == []


def test_skips_environment_directories_without_git(tmp_path):
    root = _tree(tmp_path, {".venv/lib/x.md": "docs/absent.md\n", "docs/a.md": "fine\n"})
    assert cdp.check_links(root) == []


def test_empty_git_index_falls_back_to_walking(tmp_path):
    import subprocess

    root = _tree(tmp_path, {"docs/a.md": "docs/absent.md\n"})
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    assert len(cdp.check_links(root)) == 1


def test_marker_excuses_only_the_adjacent_private_path(tmp_path):
    root = _tree(tmp_path, {
        "docs/a.md": "see docs/bogus.md and tests/pilot/x.py (private suite)\n"
                     "`tests/pilot/x.py` (private suite) and"
                     " `scripts/pilot_chain_*` (private suite)\n"
                     "docs/bogus2.md (private suite)\n"})
    assert cdp.check_links(root) == ["docs/a.md:1: path missing: docs/bogus.md",
                                     "docs/a.md:3: path missing: docs/bogus2.md"]
