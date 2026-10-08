"""The status document marks private-suite references; the serialised matrix is unchanged."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("render_status_matrix",
                                                  ROOT / "scripts/render_status_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rsm = _load()


def test_document_equals_the_rendered_matrix():
    assert rsm.main(["--check"]) == 0


def test_every_private_reference_is_marked_and_every_marked_one_is_private():
    from sn87_provenonce.bundle import STATUS_MATRIX

    table = rsm.render()
    for item, implemented, _enabled, tested, _deployed in STATUS_MATRIX:
        for ref in (implemented, tested):
            if not ref or ref == "NOT_TESTED":
                continue
            private = ref.startswith(rsm.PRIVATE_SUITE_PREFIXES)
            assert (f"`{ref}`{rsm.MARK}" in table) == private, item
            path = ref.partition("::")[0].partition(":")[0]
            if not private and "/" in path:
                assert (ROOT / path).exists(), (item, ref)  # an unmarked reference is public


def test_marked_prefixes_are_private_in_the_manifest_and_absent_publicly():
    manifest = json.loads((ROOT / "PUBLIC_MANIFEST.json").read_text())
    private = [g for entry in manifest["private"] for g in entry["globs"]]
    if not private:
        return  # the exported tree: the private class is blanked, and the files are absent
    import fnmatch

    for prefix in rsm.PRIVATE_SUITE_PREFIXES:
        probe = prefix if not prefix.endswith("/") else prefix + "x"
        probe = probe + ("x.py" if prefix.endswith("_") else "")
        assert any(fnmatch.fnmatch(probe, g.replace("**", "*")) for g in private), prefix


def test_marker_is_rendering_only():
    from sn87_provenonce.bundle import STATUS_MATRIX, status_markdown

    assert rsm.MARK not in status_markdown()
    assert all(rsm.MARK not in str(row) for row in STATUS_MATRIX)
    assert rsm.mark_private("| `tests/pilot/a.py` | `tests/test_scoring.py::t` |") == (
        "| `tests/pilot/a.py` (private suite) | `tests/test_scoring.py::t` |")
