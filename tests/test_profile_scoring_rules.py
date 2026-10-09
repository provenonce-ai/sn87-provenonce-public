"""IC-FIRST-LIGHT-MIN-2: the state payoff matrix, the wrong-scope rule and citation precision.

Everything here uses public fixtures, hand-written truth records and the matched public-contract
baseline, so it runs in the public tree. The private suite (test_profile_comparison.py) checks
the same rules against recomputed reference truth. The profile is committed and not active: no
class binding and no weight path names it (ADR-0019).
"""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sn87_provenonce import profile, scoring
from sn87_provenonce.canonical import evidence_commitment
from sn87_provenonce.classes import BINDINGS
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.profile import STATES, Profile, ProfileNotApplied
from sn87_provenonce.scoring import Integrity, evidence_credit, score_response

NEW_ID, OLD_ID = "IC-FIRST-LIGHT-MIN-2", "IC-FIRST-LIGHT-MIN-1"
OK = Integrity(True, True, True, True, True, True)
FINDINGS, CLEAR, ABSTAIN = STATES
NEW = replace(IC, profile=profile.load(NEW_ID))
SRC = Path(profile.__file__).parent


def document(profile_id):
    return json.loads((SRC / "profiles" / f"{profile_id}.json").read_text())


def derive(doc):
    return Profile.from_document(doc, class_id="IC-APPROVAL-APPLICABILITY",
                                 domain="SN87:SCORING_PROFILE:institution/0.2")


def refs(capsule):
    return sorted({e["event_id"] for e in capsule["events"]} | {"$completeness"})


def required(capsule):
    return refs(capsule)[:9]  # a hand-written witness set of 9 references


def truth(capsule, state):
    defects = ([{"code": "STALE_APPROVAL", "severity": "HIGH",
                 "required_refs": required(capsule)}] if state == FINDINGS else [])
    return {"state": state, "defects": defects}


def response(capsule, state, *, cited=None, confidence="1", code="STALE_APPROVAL"):
    """A contract-valid differential, built on the baseline's valid shell."""
    shell = copy.deepcopy(IC.baseline(capsule))
    findings = []
    if state == FINDINGS:
        findings = [{"code": code, "severity": "HIGH",
                     "evidence_refs": required(capsule) if cited is None else cited,
                     "rationale": "A finding.", "confidence": confidence}]
    return shell | {"state": state, "findings": findings, "rationale": "A rationale."}


def score(binding, capsule, truth_state, resp):
    result = score_response(binding, capsule, truth(capsule, truth_state), resp, OK)
    assert result["valid"], result["failures"]
    return result


def wrong_scope(family, index=0):
    """One action's recipient differs from the one the approval covers. The scoped record is
    left otherwise valid, so the matched baseline (which reads conditions only) is blind to it."""
    capsule = copy.deepcopy(IC.generate(family, index))
    action = [e for e in capsule["events"] if e["kind"] == "ACTION"][2]
    action["scope"] = dict(action["scope"], recipient="other-recipient")
    capsule["evidence_commitment"] = evidence_commitment(capsule)
    IC.validate_capsule(copy.deepcopy(capsule))
    return capsule


# --- the old profile is untouched ---------------------------------------------------------------

def test_committed_profiles_declare_no_new_rules_and_keep_their_pins():
    assert IC.profile.commitment == (
        "sha256:7049f165bc9b4fae32133f2d37aa9a48f5bf13f3b4fa47ea94643e5633d3c766")
    for binding in BINDINGS.values():
        p = binding.profile
        assert (p.state_payoff, p.wrong_scope, p.evidence_credit) == (None, None, None)
        assert "scoring_rules" not in p.document
    assert set(profile.REGISTRY) == {"GRA-W03-3", OLD_ID, NEW_ID, "IC-FIRST-LIGHT-MIN-3"}


def test_old_profile_scores_are_unchanged_to_the_last_bit():
    """Literal scores of the original scorer (also checked against the pre-change module over
    every public family and response variant when the rules were added). No ``payoff`` key
    appears for an old profile."""
    c = IC.generate("incomplete", 0)
    abstain = score(IC, c, ABSTAIN, response(c, ABSTAIN))
    assert abstain["score"] == pytest.approx(1e-6, rel=1e-12) and "payoff" not in abstain
    for conf, expected in (("0.9", 1.1369744888101388e-05), ("0.5", 1.4962778697388477e-05)):
        hedged = score(IC, c, ABSTAIN, response(c, FINDINGS, cited=refs(c), confidence=conf))
        assert hedged["score"] == pytest.approx(expected, rel=1e-12)
    s = IC.generate("stale_authority", 0)
    assert score(IC, s, FINDINGS, response(s, FINDINGS, cited=refs(s)))["score"] == 1.0


def test_old_profile_evidence_credit_stays_binary():
    need = ["a", "b", "c"]
    assert evidence_credit(IC.profile, need, ["a", "b", "c"]) == 1.0
    assert evidence_credit(IC.profile, need, ["a", "b", "c", "d", "e", "f", "g"]) == 1.0
    assert evidence_credit(IC.profile, need, ["a", "b"]) == 0.0


def test_the_new_profile_is_not_active_anywhere():
    """No class binding, and no module outside the loader names it; it is reachable by id only."""
    assert {b.profile.profile_id for b in BINDINGS.values()} == {"GRA-W03-3", OLD_ID}
    named = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts
                   and NEW_ID in p.read_bytes().decode("utf-8", "ignore"))
    # MIN-3 (ADR-0020) names its parent in `derived_from`, so its document is the one other carrier.
    assert named == ["profile.py", f"profiles/{NEW_ID}.json", "profiles/IC-FIRST-LIGHT-MIN-3.json"]


# --- the new profile document -------------------------------------------------------------------

def test_new_profile_is_the_old_profile_plus_the_three_rules():
    new, old = document(NEW_ID), document(OLD_ID)
    changed = {k for k in new.keys() | old.keys() if new.get(k) != old.get(k)}
    assert changed == {"profile_id", "revision", "derived_from", "scoring_rules",
                       "evidence_quality"}
    assert new["derived_from"] == OLD_ID
    p = profile.load(NEW_ID)
    assert (p.class_id, p.commitment) == ("IC-APPROVAL-APPLICABILITY", profile.REGISTRY[NEW_ID][2])
    assert p.commitment != IC.profile.commitment
    assert p.weights == IC.profile.weights and p.minimum == IC.profile.minimum
    assert (p.theta, p.gamma, p.epsilon) == (IC.profile.theta, IC.profile.gamma,
                                             IC.profile.epsilon)


def test_payoff_matrix_values_and_order():
    cells = profile.load(NEW_ID).state_payoff
    assert cells == {
        FINDINGS: {FINDINGS: 1.0, CLEAR: 0.0, ABSTAIN: 0.25},
        CLEAR: {FINDINGS: 0.0, CLEAR: 1.0, ABSTAIN: 0.25},
        ABSTAIN: {FINDINGS: 0.0, CLEAR: 0.0, ABSTAIN: 0.5},
    }
    wrong = max(cells[t][r] for t in STATES for r in (FINDINGS, CLEAR) if r != t)
    assert wrong < cells[ABSTAIN][ABSTAIN] < min(cells[FINDINGS][FINDINGS], cells[CLEAR][CLEAR])
    assert cells[FINDINGS][ABSTAIN] < cells[ABSTAIN][ABSTAIN]
    assert profile.load(NEW_ID).wrong_scope == "ABSTENTION_ON_RECORD"
    assert profile.load(NEW_ID).evidence_credit == "PRECISION_TIMES_RECALL"


def _with_cell(truth_state, response_state, value):
    doc = document(NEW_ID)
    doc["scoring_rules"]["state_payoff"][truth_state][response_state] = value
    return doc


@pytest.mark.parametrize("doc", [
    _with_cell(ABSTAIN, ABSTAIN, "1"),          # abstention as good as a correct finding
    _with_cell(ABSTAIN, ABSTAIN, "0.2"),        # below an unwarranted abstention
    _with_cell(FINDINGS, ABSTAIN, "0.75"),      # unwarranted abstention above a correct one
    _with_cell(CLEAR, FINDINGS, "0.3"),         # confident wrong above an unwarranted abstention
    _with_cell(ABSTAIN, CLEAR, "0.5"),          # confident wrong equal to a correct abstention
    _with_cell(FINDINGS, FINDINGS, "0.5"),      # a correct finding no better than an abstention
    _with_cell(CLEAR, CLEAR, "1.5"),            # above 1
    _with_cell(CLEAR, CLEAR, 1),                # not a decimal string
])
def test_loader_rejects_an_unordered_or_unparsed_matrix(doc):
    with pytest.raises(ProfileNotApplied):
        derive(doc)


def test_loader_rejects_incomplete_or_extra_rule_blocks():
    base = document(NEW_ID)
    missing_row = copy.deepcopy(base)
    del missing_row["scoring_rules"]["state_payoff"][CLEAR]
    missing_cell = copy.deepcopy(base)
    del missing_cell["scoring_rules"]["state_payoff"][FINDINGS][ABSTAIN]
    extra_key = copy.deepcopy(base)
    extra_key["scoring_rules"]["new_rule"] = "ON"
    partial = copy.deepcopy(base)
    del partial["scoring_rules"]["evidence_credit"]
    for doc in (missing_row, missing_cell, extra_key, partial):
        with pytest.raises(ProfileNotApplied):
            derive(doc)


@pytest.mark.parametrize("key,value", [
    ("wrong_scope", "NEW_FINDING_CODE"),  # needs a wire-contract change, not a profile
    ("wrong_scope", "ignore"),
    ("evidence_credit", "BINARY_ALL_REQUIRED_REFS_PRESENT"),
    ("evidence_credit", "SURPLUS_FREE"),
])
def test_loader_rejects_unsupported_rule_values(key, value):
    doc = document(NEW_ID)
    doc["scoring_rules"][key] = value
    with pytest.raises(ProfileNotApplied, match="unsupported"):
        derive(doc)


def test_the_rules_move_the_commitment():
    doc = document(NEW_ID)
    doc["scoring_rules"]["state_payoff"][ABSTAIN][ABSTAIN] = "0.6"
    assert derive(doc).commitment != profile.load(NEW_ID).commitment


# --- rule 1: the payoff matrix ------------------------------------------------------------------

@pytest.mark.parametrize("truth_state", STATES)
@pytest.mark.parametrize("response_state", STATES)
def test_each_cell_pays_its_declared_value(truth_state, response_state):
    c = IC.generate("stale_authority", 0)
    resp = response(c, response_state)
    result = score(NEW, c, truth_state, resp)
    expected = NEW.profile.state_payoff[truth_state][response_state]
    if truth_state == response_state == FINDINGS:
        assert result["score"] == 1.0
    else:
        assert result["score"] == pytest.approx(max(expected, NEW.profile.epsilon), rel=1e-9)
        assert result["payoff"] == {"truth": truth_state, "response": response_state,
                                    "cell": expected, "quality": 1.0}


def test_a_correct_abstention_beats_a_hedged_false_finding_and_pays_a_real_value():
    c = IC.generate("incomplete", 0)
    correct = score(NEW, c, ABSTAIN, response(c, ABSTAIN))["score"]
    assert correct == 0.5
    for conf in ("0.1", "0.5", "0.9", "1"):
        hedged = score(NEW, c, ABSTAIN, response(c, FINDINGS, cited=refs(c), confidence=conf))
        assert hedged["score"] == pytest.approx(NEW.profile.epsilon, rel=1e-9)
        assert hedged["score"] < correct
    # Under the original profile the ordering was the other way round.
    old_correct = score(IC, c, ABSTAIN, response(c, ABSTAIN))["score"]
    old_hedged = score(IC, c, ABSTAIN, response(c, FINDINGS, cited=refs(c), confidence="0.5"))
    assert old_hedged["score"] > old_correct


def test_a_confident_wrong_answer_pays_less_than_a_correct_abstention_for_every_truth():
    c = IC.generate("stale_authority", 0)
    for truth_state in STATES:
        correct_abstain = 0.5 if truth_state == ABSTAIN else 0.25
        for wrong in (FINDINGS, CLEAR):
            if wrong != truth_state:
                result = score(NEW, c, truth_state, response(c, wrong))
                assert result["score"] < correct_abstain


def test_always_abstaining_does_not_beat_answering_correctly():
    c = IC.generate("stale_authority", 0)
    answer = score(NEW, c, FINDINGS, response(c, FINDINGS))["score"]
    assert score(NEW, c, FINDINGS, response(c, ABSTAIN))["score"] < answer


def test_per_finding_quality_still_scales_a_correct_finding():
    c = IC.generate("stale_authority", 0)
    exact = score(NEW, c, FINDINGS, response(c, FINDINGS))["score"]
    shy = score(NEW, c, FINDINGS, response(c, FINDINGS, confidence="0.5"))["score"]
    wrong_code = score(NEW, c, FINDINGS, response(c, FINDINGS, code="OTHER_CODE"))["score"]
    assert exact == 1.0 and shy < exact
    assert wrong_code == pytest.approx(NEW.profile.epsilon, rel=1e-9) and wrong_code < shy


def test_invalid_responses_still_score_zero_below_the_floor():
    c = IC.generate("incomplete", 0)
    broken = response(c, ABSTAIN) | {"qid": "someone-else"}
    result = score_response(NEW, c, truth(c, ABSTAIN), broken, OK)
    assert result["valid"] is False and result["score"] == 0.0
    assert score_response(NEW, c, truth(c, ABSTAIN), None, OK)["score"] == 0.0


# --- rule 2: wrong scope is settled as abstention on record --------------------------------------

def test_wrong_scope_abstention_is_the_response_that_pays():
    """Truth for a wrong-scope record is the abstain state (the private test confirms the
    recomputed truth). A named finding, a clear and the public-contract baseline all miss it."""
    for family in ("fresh_review", "stale_authority"):
        c = wrong_scope(family)
        assert score(NEW, c, ABSTAIN, response(c, ABSTAIN))["score"] == 0.5
        named = response(c, FINDINGS, cited=refs(c), code="WRONG_SCOPE")
        assert score(NEW, c, ABSTAIN, named)["score"] == pytest.approx(1e-6, rel=1e-9)
        assert score(NEW, c, ABSTAIN, IC.baseline(copy.deepcopy(c)))["score"] == pytest.approx(
            1e-6, rel=1e-9)
    # The original profile gave all of these the same floor.
    c = wrong_scope("fresh_review")
    assert score(IC, c, ABSTAIN, response(c, ABSTAIN))["score"] == pytest.approx(1e-6)
    assert score(IC, c, ABSTAIN, IC.baseline(copy.deepcopy(c)))["score"] == pytest.approx(1e-6)


def test_the_wrong_scope_rule_adds_no_finding_code():
    assert IC.defect_severity == {"STALE_APPROVAL": "HIGH"}
    assert profile.WRONG_SCOPE_RULES == ("ABSTENTION_ON_RECORD",)


# --- rule 3: citation precision -----------------------------------------------------------------

@pytest.mark.parametrize("cited,expected", [
    (["a", "b", "c", "d"], 1.0),                              # exact
    (["a", "b", "c", "d", "e", "f", "g", "h"], 0.5),         # twice the witness: precision 1/2
    (["a", "b", "c"], 0.75),                                  # recall 3/4
    (["a", "b", "x", "y"], 0.25),                             # half right, half surplus
    (["x", "y"], 0.0),                                        # nothing required
    ([], 0.0),
    (["a", "a", "b", "b", "c", "c", "d", "d"], 1.0),          # repeats are one reference
])
def test_precision_times_recall(cited, expected):
    assert evidence_credit(NEW.profile, ["a", "b", "c", "d"], cited) == expected


def test_no_required_references_gives_full_credit_under_both_rules():
    for p in (IC.profile, NEW.profile):
        assert evidence_credit(p, [], []) == evidence_credit(p, [], ["a"]) == 1.0


def test_citing_everything_no_longer_matches_citing_exactly():
    c = IC.generate("stale_authority", 0)
    assert len(refs(c)) > len(required(c))
    everything = score(NEW, c, FINDINGS, response(c, FINDINGS, cited=refs(c)))
    exact = score(NEW, c, FINDINGS, response(c, FINDINGS))
    assert exact["score"] == 1.0
    assert everything["dimensions"]["evidence"] == pytest.approx(
        len(required(c)) / len(refs(c)))
    assert everything["score"] < exact["score"]
    # Under the original profile the two were indistinguishable.
    old = score(IC, c, FINDINGS, response(c, FINDINGS, cited=refs(c)))["score"]
    assert old == score(IC, c, FINDINGS, response(c, FINDINGS))["score"] == 1.0


def test_dropping_a_required_reference_costs_more_than_one_surplus_reference():
    c = IC.generate("stale_authority", 0)
    witness = required(c)
    surplus = [r for r in refs(c) if r not in witness][:1]
    one_extra = score(NEW, c, FINDINGS, response(c, FINDINGS, cited=witness + surplus))
    one_short = score(NEW, c, FINDINGS, response(c, FINDINGS, cited=witness[:-1]))
    assert one_extra["score"] > one_short["score"]


def test_scoring_module_has_no_profile_id_branch():
    """The new behaviour is selected by the profile's declared rules, never by its name."""
    source = Path(scoring.__file__).read_text()
    assert "IC-FIRST-LIGHT" not in source and "profile_id" not in source
