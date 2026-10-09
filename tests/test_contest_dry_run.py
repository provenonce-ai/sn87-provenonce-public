"""The local dry run: commit, open, two public miners, truth, results, reveal, verify.

The public replay (committed truth, reference executors blocked in a subprocess) must produce the
committed pages byte for byte; with the executors present, their truth must equal the committed one.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contest_dry_run as dr  # noqa: E402
from conftest import executors_available  # noqa: E402

DEMO = ROOT / "examples" / "contest-window-demo"
BLOCK = """
import sys
for name in ("sn87_provenonce.institutional_v02.references", "sn87_provenonce.pilot.reference",
             "sn87_provenonce.simulation.type_c_reference"):
    sys.modules[name] = None
sys.path.insert(0, sys.argv[1])
import contest_dry_run
raise SystemExit(contest_dry_run.main(sys.argv[2:]))
"""


def read(path):
    return path.read_text()


def test_dry_run_reproduces_the_committed_demo_files(tmp_path):
    out = tmp_path / "run"
    dr.dry_run(out, sizing_profile="IC-FIRST-LIGHT-MIN-3", scoring_profile="IC-FIRST-LIGHT-MIN-3",
               preset="messy", truth_source="committed", timing=False)
    for name in ("schedule.json", "commitments.json", "window_demo-0001.reveal.json"):
        assert read(out / name) == read(DEMO / name), name
    assert read(out / "window_demo-0001.truth.private.json") == read(
        DEMO / "window_demo-0001.truth.json")
    for folder in ("results", "results-full"):
        for name in ("window_demo-0001.json", "window_demo-0001.md"):
            assert read(out / folder / name) == read(DEMO / folder / name), (folder, name)


def test_dry_run_runs_with_the_reference_executors_blocked(tmp_path):
    out = tmp_path / "blocked"
    done = subprocess.run([sys.executable, "-c", BLOCK, str(ROOT / "scripts"),
                           "--out-dir", str(out)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert read(out / "results-full" / "window_demo-0001.json") == read(
        DEMO / "results-full" / "window_demo-0001.json")


def test_dry_run_phases_ran_in_order_and_hid_truth_until_close(tmp_path):
    out = tmp_path / "run"
    dr.dry_run(out, sizing_profile="IC-FIRST-LIGHT-MIN-3", scoring_profile="IC-FIRST-LIGHT-MIN-3",
               preset="messy", truth_source="committed", timing=False)
    capsules = read(out / "window_demo-0001.capsules.json")
    assert "truth" not in capsules and "family" not in capsules
    assert json.loads(read(out / "results-detail" / "window_demo-0001.json"))["cases"]
    scores = json.loads(read(out / "results" / "window_demo-0001.json"))
    assert scores["disclosure"] == "SCORES_ONLY" and "cases" not in scores
    assert "confusion" not in json.dumps(scores)


def test_dry_run_into_an_existing_directory_is_refused(tmp_path):
    with pytest.raises(FileExistsError):
        dr.dry_run(tmp_path, sizing_profile="IC-FIRST-LIGHT-MIN-3",
                   scoring_profile="IC-FIRST-LIGHT-MIN-3", preset="messy",
                   truth_source="committed", timing=False)


def test_timing_is_opt_in_and_changes_only_the_cost_record(tmp_path):
    out = tmp_path / "timed"
    dr.dry_run(out, sizing_profile="IC-FIRST-LIGHT-MIN-3", scoring_profile="IC-FIRST-LIGHT-MIN-3",
               preset="messy", truth_source="committed", timing=True)
    timed = json.loads(read(out / "results-full" / "window_demo-0001.json"))
    committed = json.loads(read(DEMO / "results-full" / "window_demo-0001.json"))
    for m in timed["methods"]:
        assert m["cost"]["wall_time"]["source"] == "reported_with_responses"
        m["cost"] = None
    for m in committed["methods"]:
        m["cost"] = None
    assert timed == committed


def test_scoring_the_same_window_under_the_current_profile(tmp_path):
    out = tmp_path / "min1"
    dr.dry_run(out, sizing_profile="IC-FIRST-LIGHT-MIN-3", scoring_profile="IC-FIRST-LIGHT-MIN-1",
               preset="messy", truth_source="committed", timing=False)
    page = json.loads(read(out / "results-full" / "window_demo-0001.json"))
    assert page["profile"]["profile_id"] == "IC-FIRST-LIGHT-MIN-1"
    cand, base = (next(m for m in page["methods"] if m["role"] == r)
                  for r in ("candidate", "baseline"))
    assert cand["score"]["estimate"] == base["score"]["estimate"]
    assert cand["agreement"]["state_all"]["fraction"] != base["agreement"]["state_all"]["fraction"]


@pytest.mark.skipif(not executors_available(), reason="needs the private reference executors")
def test_reference_truth_replaces_the_committed_truth_without_a_difference(tmp_path):
    out = tmp_path / "reference"
    dr.dry_run(out, sizing_profile="IC-FIRST-LIGHT-MIN-3", scoring_profile="IC-FIRST-LIGHT-MIN-3",
               preset="messy", truth_source="reference", timing=False)
    assert read(out / "results-full" / "window_demo-0001.md") == read(
        DEMO / "results-full" / "window_demo-0001.md")
