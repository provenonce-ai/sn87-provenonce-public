"""The README uid table is generated from attestation data and cannot drift from it."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("render_uid_table",
                                                  ROOT / "scripts/render_uid_table.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rut = _load()


def _data():
    return json.loads(rut.PARTICIPANTS.read_text(encoding="utf-8"))


def test_readme_tables_equal_the_generated_table():
    table = rut.render()
    for path in rut.TARGETS:
        text = path.read_text(encoding="utf-8")
        block = text.split(rut.BEGIN + "\n")[1].split(rut.END)[0]
        assert block == table, path.name
    assert rut.main(["--check"]) == 0


def test_from_block_comes_from_the_attestation():
    rows, first = rut.attested_rows()
    attested = [r for r in rut.resolve(_data(), first) if r["period"] == "attested_runs"]
    assert {r["from_block"] for r in attested} == {first}
    assert {tuple(r["dests"]) for r in rows} == {(1, 2)}


def test_every_attested_uid_has_a_row_and_one_hotkey():
    uids = {r["uid"] for r in _data()["rows"] if r["period"] == "attested_runs"}
    assert uids == {1, 2}
    assert len({r["hotkey"] for r in _data()["rows"] if r["uid"] in uids}) == 2


def test_unrecorded_values_are_labelled_not_guessed():
    assert "not recorded" in rut.render()  # the validator row has no recorded from block


def test_drift_is_detected(tmp_path, monkeypatch, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(f"x\n{rut.BEGIN}\nold table\n{rut.END}\ny\n", encoding="utf-8")
    monkeypatch.setattr(rut, "TARGETS", [readme])
    assert rut.main(["--check"]) == 1
    assert rut.main(["--write"]) == 0
    assert rut.main(["--check"]) == 0
    assert readme.read_text(encoding="utf-8").startswith(f"x\n{rut.BEGIN}\nTestnet netuid 582")


def test_attestation_disagreement_is_refused():
    data = copy.deepcopy(_data())
    data["rows"] = [r for r in data["rows"]
                    if not (r["uid"] == 2 and r["period"] == "attested_runs")]
    with pytest.raises(rut.TableError):
        rut.render(data)


def test_missing_markers_are_refused():
    with pytest.raises(rut.TableError):
        rut.splice("no markers", "t\n")


@pytest.mark.parametrize("field", ["netuid", "mecid", "validator_uid"])
def test_target_fields_must_match_every_attestation(field):
    data = copy.deepcopy(_data())
    data[field] += 1
    with pytest.raises(rut.TableError, match=field):
        rut.render(data)
