"""The default `demo` runs the institution/0.2 path end to end on the public fixtures.

Reads only the committed public truth file, so it passes with the private reference executors
absent (the subprocess blocks them to prove it) as well as in the full tree.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sn87_provenonce import quickstart
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as BINDING
from sn87_provenonce.cli import main
from sn87_provenonce.institutional_v02.fixtures import build_case

ROOT = Path(__file__).parents[1]
BLOCK = """
import sys
for name in ("sn87_provenonce.institutional_v02.references", "sn87_provenonce.pilot.reference",
             "sn87_provenonce.simulation.type_c_reference"):
    sys.modules[name] = None
from sn87_provenonce.cli import main
raise SystemExit(main(sys.argv[1:]))
"""


def test_truth_file_covers_each_family_and_binds_the_default_capsule():
    document = quickstart.load_public_truth()
    assert set(document["cases"]) == set(quickstart.FAMILIES)
    for family, entry in document["cases"].items():
        assert entry["capsule_commitment"] == build_case(family)["evidence_commitment"]
        assert entry["truth"]["state"] in {
            "FINDINGS", "NO_MATERIAL_DEVIATION", "INSUFFICIENT_EVIDENCE_ABSTAIN"}


def test_quickstart_scores_each_family_against_published_truth():
    result = quickstart.run_quickstart()
    cases = {c["family"]: c for c in result["cases"]}
    assert result["class_id"] == BINDING.class_id == "IC-APPROVAL-APPLICABILITY"
    assert result["profile_id"] == BINDING.profile.profile_id
    for case in cases.values():
        assert case["miner_state"] == case["truth_state"]
        assert case["row"]["valid"] is True
    assert cases["stale_authority"]["row"]["score"] == "1"
    assert cases["stale_authority"]["row"]["matched"] == ["STALE_APPROVAL"]
    assert cases["fresh_review"]["row"]["score"] == "1"
    assert float(cases["incomplete"]["row"]["score"]) < 0.000002


def test_a_capsule_that_does_not_match_the_committed_truth_is_refused():
    document = quickstart.load_public_truth()
    document["cases"]["stale_authority"]["capsule_commitment"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="does not match"):
        quickstart.run_case("stale_authority", document)


def test_wrong_truth_lowers_the_row():
    document = quickstart.load_public_truth()
    document["cases"]["stale_authority"]["truth"] = document["cases"]["fresh_review"]["truth"]
    row = quickstart.run_case("stale_authority", document)["row"]
    assert row["score"] != "1"


def test_default_demo_prints_the_new_path_and_legacy_is_labelled(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "institution/0.2" in out and "no chain" in out and "stale_authority" in out
    assert main(["demo", "--legacy-v0alpha1"]) == 0
    captured = capsys.readouterr()
    assert "LEGACY v0alpha1 DEMO" in captured.err and "no weight path" in captured.err
    assert json.loads(captured.out)["mode"] == "synthetic_local_conformance"


def test_demo_json_and_run_with_executors_blocked():
    done = subprocess.run([sys.executable, "-c", BLOCK, "demo", "--json"], capture_output=True,
                          text=True, cwd=ROOT, timeout=300)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert [c["family"] for c in result["cases"]] == list(quickstart.FAMILIES)


def test_vectors_option_is_legacy_only(capsys, tmp_path):
    with pytest.raises(SystemExit) as raised:
        main(["demo", "--vectors", str(tmp_path)])
    assert raised.value.code == 2
    assert "--vectors applies only to --legacy-v0alpha1" in capsys.readouterr().err
    assert main(["demo", "--legacy-v0alpha1", "--vectors", str(quickstart_vectors())]) == 0


def quickstart_vectors():
    from sn87_provenonce.cli import DEFAULT_VECTORS

    return Path(str(DEFAULT_VECTORS))
