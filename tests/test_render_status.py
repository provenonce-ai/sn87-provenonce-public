"""Status figures in the documents are generated from the attestation files and cannot drift."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("render_status",
                                                  ROOT / "scripts/render_status.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rs = _load()


def test_documents_equal_the_rendered_blocks():
    assert rs.main(["--check"]) == 0


def test_figures_come_from_the_attestation():
    f = rs.facts()
    data = json.loads(rs.ATTESTATION_02.read_text())
    assert f["count"] == data["run_count"] == len(data["runs"])
    text = rs.work_in_public(f)
    assert f"{data['runs'][0]['included_block']:,}" in text
    assert f"{data['runs'][-1]['included_block']:,}" in text
    assert data["runs"][-1]["run_id"] in text
    assert str(f["count"]) in text
    assert not re.search(r"\b(January|February|March|April|May|June|July|August|September|October"
                         r"|November|December)\b", text), "the attestation holds no dates"


def test_missing_run_ids():
    runs = [{"run_id": f"r5-20261005-{c}"} for c in "abdf"] + [{"run_id": "r5-20261006-a"}]
    assert rs.missing_run_ids(runs) == ["r5-20261005-c", "r5-20261005-e"]


def test_inconsistent_data_is_refused(tmp_path, monkeypatch):
    data = json.loads(rs.ATTESTATION_02.read_text())
    data["run_count"] += 1
    bad = tmp_path / "a02.json"
    bad.write_text(json.dumps(data))
    monkeypatch.setattr(rs, "ATTESTATION_02", bad)
    with pytest.raises(rs.StatusError, match="run_count"):
        rs.facts()


def test_drift_is_detected(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text("<!-- BEGIN STATUS:work_in_public -->\nstale 17 runs\n"
                      "<!-- END STATUS:work_in_public -->\n")
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    monkeypatch.setattr(rs, "REQUIRED", {"README.md": ("work_in_public",)})
    monkeypatch.setattr(rs, "GUIDE_DIR", tmp_path / "none")
    assert rs.main(["--check"]) == 1
    assert rs.main(["--write"]) == 0
    assert rs.main(["--check"]) == 0
    assert "stale" not in readme.read_text()


# Any integer of seven or more digits, with or without thousands separators, that is not part of
# a hex digest, identifier or longer number; or any number right after the word block(s).
_BIG = re.compile(r"(?<![\w.,-])(\d{1,3}(?:,\d{3}){2,}|\d{7,})(?![\w]|,\d)")
_AFTER_BLOCK = re.compile(r"\bblocks?\s+(\d[\d,]*)", re.I)


def block_like_numbers(text: str) -> list[int]:
    found = [m.group(1) for m in _BIG.finditer(text)] + \
            [m.group(1).rstrip(",") for m in _AFTER_BLOCK.finditer(text)]
    return sorted({int(x.replace(",", "")) for x in found if x.replace(",", "").isdigit()})


def test_the_stray_figure_detector_sees_every_formatting():
    assert block_like_numbers("at block 8,102,381.") == [8102381]
    assert block_like_numbers("at block 8102381 and 9,876,543 or 9876543") == [8102381, 9876543]
    assert block_like_numbers("blocks 12 and sha256:1234567abc") == [12]
    assert block_like_numbers("version 1.2.3 and 4 runs") == []


def test_no_stray_hand_copied_figures_in_the_documents():
    """Block numbers and run counts in prose must equal a number the data holds.

    The First Light block (8,102,381) is typed by hand in PROVENANCE.md, LIMITATIONS.md,
    docs/protocol/evidence-bundle.md and ADR-0005: those documents are the provenance record of
    that row, written before the participants file existed. They are allowed to carry it, and
    this test fails if any of them differs from ``periods.first_light.from_block``.
    """
    f = rs.facts()
    known_blocks = {f["light_block"]} | {r["included_block"] for r in f["runs"]}
    known_counts = {f["count"], f["count_01"]}
    docs = [ROOT / "README.md", ROOT / "LIMITATIONS.md", ROOT / "PROVENANCE.md",
            *(ROOT / "docs" / "protocol").glob("*.md"), *(ROOT / "docs" / "guides").glob("*.md"),
            *(ROOT / "docs" / "quickstart").glob("*.md"),
            *(ROOT / "docs" / "architecture").glob("ADR-*.md"),
            ROOT / "attestation" / "README.md"]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        # generated blocks are compared with the data by render_status --check and by the
        # verifier-output check, so only hand-written text is scanned here
        text = re.sub(r"<!-- BEGIN (STATUS:\w+|VERIFIER_OUTPUT|UID_TABLE) -->.*?<!-- END .*? -->",
                      "", text, flags=re.S)
        for value in block_like_numbers(text):
            assert value in known_blocks, (path.name, value)
        for match in re.finditer(r"\b(\d+) (?:attested |completed )?runs\b", text):
            assert int(match.group(1)) in known_counts, (path.name, match.group())
