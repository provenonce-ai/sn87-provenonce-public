"""IC-FIRST-LIGHT-MIN-3: a window sized above the minimum, with the MIN-2 rules, active nowhere."""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from sn87_provenonce import profile
from sn87_provenonce.classes import BINDINGS
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.scoring import epoch_estimate

ROOT = Path(__file__).parents[1]
SRC = Path(profile.__file__).parent
ADR = ROOT / "docs" / "architecture" / "ADR-0020-contest-windows-and-window-sizing-profile.md"
OLD, MID, NEW = "IC-FIRST-LIGHT-MIN-1", "IC-FIRST-LIGHT-MIN-2", "IC-FIRST-LIGHT-MIN-3"


def document(pid):
    return json.loads((SRC / "profiles" / f"{pid}.json").read_text())


def assigned(pid):
    return sum(document(pid)["assignment"].values())


def eligible_after(pid, failures):
    """Eligibility of a window of valid, perfect responses after `failures` reference failures."""
    p = profile.load(pid)
    n = assigned(pid) - failures
    return epoch_estimate([1.0] * n, [True] * n, p)


def test_new_profile_differs_from_min_2_only_in_window_sizing():
    new, mid = document(NEW), document(MID)
    changed = {k for k in new.keys() | mid.keys() if new.get(k) != mid.get(k)}
    assert changed == {"profile_id", "assignment", "diagnostics", "minimum_assignments",
                       "revision", "derived_from"}
    assert new["derived_from"] == MID
    assert new["scoring_rules"] == mid["scoring_rules"]  # inherits the F8 rules unchanged
    p, q = profile.load(NEW), profile.load(MID)
    assert (p.state_payoff, p.wrong_scope, p.evidence_credit) == (
        q.state_payoff, q.wrong_scope, q.evidence_credit)
    assert (p.weights, p.theta, p.gamma, p.epsilon, p.invalid_ceiling) == (
        q.weights, q.theta, q.gamma, q.epsilon, q.invalid_ceiling)
    assert p.commitment != q.commitment != profile.load(OLD).commitment


def test_window_is_larger_than_the_old_minimum_and_the_floor_stays_above_it():
    p = profile.load(NEW)
    assert assigned(NEW) > assigned(OLD) and p.minimum > profile.load(OLD).minimum
    assert p.minimum <= assigned(NEW)


@pytest.mark.parametrize("pid", [OLD, MID])
def test_a_single_reference_failure_voids_a_window_under_the_first_versions(pid):
    assert eligible_after(pid, 0)["eligible"] is True
    one = eligible_after(pid, 1)
    assert one["eligible"] is False and one["reason"] == "SAMPLE_FLOOR"


def test_a_single_reference_failure_no_longer_voids_a_window_under_min_3():
    assert eligible_after(NEW, 1)["eligible"] is True
    tolerated = assigned(NEW) - profile.load(NEW).minimum
    assert tolerated >= 1
    assert eligible_after(NEW, tolerated)["eligible"] is True
    over = eligible_after(NEW, tolerated + 1)
    assert over["eligible"] is False and over["reason"] == "SAMPLE_FLOOR"


def test_the_estimate_itself_is_unchanged_by_the_larger_window():
    """The rule is only about eligibility: the same responses give the same mean."""
    p = profile.load(NEW)
    scores = [1.0, 0.5] * (assigned(NEW) // 2)
    assert epoch_estimate(scores, [True] * len(scores), p)["estimate"] == pytest.approx(0.75)


def test_miner_failures_still_hit_the_unchanged_ceiling():
    p = profile.load(NEW)
    n = assigned(NEW)
    valid = [True] * (n - 3) + [False] * 3  # 3/24 = 0.125 > 0.10
    result = epoch_estimate([1.0] * n, valid, p)
    assert result["eligible"] is False and result["reason"] == "RAW_FAILURE_CEILING"


def test_it_is_active_nowhere_and_named_only_by_the_loader():
    assert {b.profile.profile_id for b in BINDINGS.values()} == {"GRA-W03-3", OLD}
    named = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts
                   and NEW in p.read_bytes().decode("utf-8", "ignore"))
    assert named == ["profile.py", f"profiles/{NEW}.json"]
    scripts = sorted(p.name for p in (ROOT / "scripts").glob("*.py")
                     if NEW in p.read_text("utf-8", "ignore"))
    # Shadow tooling may take it by id; nothing under src/ may bind it.
    assert set(scripts) <= {"contest_dry_run.py", "contest_results.py", "window_sizing_table.py"}


def test_the_profile_scores_through_the_one_scorer():
    bound = replace(IC, profile=profile.load(NEW))
    c = IC.generate("incomplete", 0)
    truth = IC.reference(c) if _executors() else None
    if truth is None:
        pytest.skip("needs the private reference executors")
    from sn87_provenonce.scoring import Integrity, score_response
    abstain = IC.candidates["state_machine"](c)
    score = score_response(bound, c, truth, abstain, Integrity(*[True] * 6))
    assert score["score"] == 0.5 and score["payoff"]["cell"] == 0.5


def _executors():
    from conftest import executors_available
    return executors_available()


def test_adr_sizing_block_is_the_generated_one():
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "window_sizing_table.py"),
                           "--check", str(ADR)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
