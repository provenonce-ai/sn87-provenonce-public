"""Candidate versus matched baseline on IC-APPROVAL-APPLICABILITY: where they tie and where not.

Contributed by an independent reviewer. The checks were first run by the reviewer as two
read-only probe scripts; this module is a re-implementation against the public API only, so it
runs in the exported tree (no reference executor, no network, nothing written).

What it establishes, all by computation:

1. The tie belongs to the published fixtures (the three default ones and every case with
   published truth). On those, the candidate
   (`miners/witness_ic.py`) and the matched baseline (`baselines.py`) return the same state.
2. The methods are not equivalent. Capsules built from the public fixture generator, edited in
   memory, re-sealed and still accepted by the capsule contract, produce different response
   states. The cases are listed in `VARIANTS`; the numbers are counted, not typed in.
3. Why. The candidate checks the approval chain (approved review, ordering, approval still
   valid, scope and artifact equality, event kinds) and abstains when it is broken. The baseline
   reads only the review condition against the governing policy, so it never sees a broken
   chain. In the other direction the candidate resolves a same-instant tie of governing policy
   versions that carry the same condition, and the baseline abstains.
4. Evidence precision. For one finding the candidate cites the witness chain, the baseline cites
   every event plus the completeness scope. The candidate's set is a strict subset.
5. Under IC-FIRST-LIGHT-MIN-1 (binary evidence credit) both get full evidence credit on the
   published stale_authority fixture, which reproduces the null separation. Under
   IC-FIRST-LIGHT-MIN-2 (ADR-0019, citation precision) the baseline's credit is lower, so the
   profile separates them on that fixture.

Limit, stated in LIMITATIONS.md: truth for the edited capsules is not published (it needs the
private reference executors), so this module compares response states and payoff cells. It does
not say which method is right on an edited capsule, and it does not say the candidate would win.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from itertools import product

import pytest
from golden_support import STORE, golden_truth

from sn87_provenonce import profile as profile_module
from sn87_provenonce.baselines import ic_approval_applicability
from sn87_provenonce.canonical import evidence_commitment
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.institutional_v02 import contracts as ic
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.miners.witness_ic import approval_witness
from sn87_provenonce.profile import STATES
from sn87_provenonce.scoring import Integrity, evidence_credit, score_response

GOLDEN = golden_truth.GOLDEN_DIR
FINDINGS, CLEAR, ABSTAIN = STATES
FAMILIES = ("stale_authority", "fresh_review", "incomplete")
OK = Integrity(True, True, True, True, True, True)
MIN_1, MIN_2 = "IC-FIRST-LIGHT-MIN-1", "IC-FIRST-LIGHT-MIN-2"
CANDIDATE = approval_witness
BASELINE = ic_approval_applicability


# --- helpers ------------------------------------------------------------------------------------

def run(method, capsule):
    """One method on its own copy of the capsule, so neither can see the other's edits."""
    return method(copy.deepcopy(capsule))


def kind_of(capsule, kind):
    return [e for e in capsule["events"] if e["kind"] == kind]


def resealed(capsule):
    """The capsule binds its own contents: any edit must be re-sealed to stay contract-valid."""
    capsule["evidence_commitment"] = evidence_commitment(capsule)
    return capsule


def with_scope_suffix(action):
    action["scope"] = dict(action["scope"], mission=action["scope"]["mission"] + "-x")


def add_policy_twin(capsule, *, same_condition):
    governing = max(kind_of(capsule, "POLICY_VERSION"), key=lambda v: v["effective_at"])
    twin = copy.deepcopy(governing)
    twin["event_id"] += "-twin"
    twin["version_id"] += "-twin"
    if not same_condition:
        twin["condition_commitment"] = "sha256:" + "1" * 64
    capsule["events"].append(twin)
    capsule["events"].sort(key=lambda e: (e["at"], e["event_id"]))


def edit_no_action(c):
    c["events"] = [e for e in c["events"] if e["kind"] != "ACTION"]


def edit_expired(c):
    kind_of(c, "APPROVAL")[0]["valid_until"] = kind_of(c, "ACTION")[0]["at"]


def edit_scope(c):
    with_scope_suffix(kind_of(c, "ACTION")[0])


def edit_artifact(c):
    kind_of(c, "ACTION")[0]["artifact_commitment"] = "sha256:" + "0" * 64


def edit_unapproved(c):
    kind_of(c, "REVIEW")[0]["approved"] = False


def edit_link_to_review(c):
    kind_of(c, "APPROVAL_LINK")[0]["approval_ref"] = kind_of(c, "REVIEW")[0]["event_id"]


# name -> (family the edit starts from, edit, what the edit does to the record)
VARIANTS = {
    "no_action": ("stale_authority", edit_no_action, "no ACTION event at all"),
    "approval_expired": ("stale_authority", edit_expired,
                         "approval valid_until is not after the action"),
    "scope_mismatch": ("stale_authority", edit_scope, "action scope differs from the approval's"),
    "artifact_mismatch": ("stale_authority", edit_artifact,
                          "action artifact differs from the approval's"),
    "review_not_approved": ("stale_authority", edit_unapproved, "the review did not approve"),
    "policy_tie_same_condition": (
        "stale_authority", lambda c: add_policy_twin(c, same_condition=True),
        "two governing versions at one instant, same condition"),
    "policy_tie_other_condition": (
        "stale_authority", lambda c: add_policy_twin(c, same_condition=False),
        "two governing versions at one instant, different conditions"),
    "link_to_review": ("stale_authority", edit_link_to_review,
                       "the approval link points at a REVIEW, not an APPROVAL"),
    "fresh_expired": ("fresh_review", edit_expired, "fresh record, approval expired"),
    "fresh_scope_mismatch": ("fresh_review", edit_scope, "fresh record, scope mismatch"),
}

# Edits that break the approval chain itself (the candidate's chain check fails).
CHAIN_BROKEN = {"no_action", "approval_expired", "scope_mismatch", "artifact_mismatch",
                "review_not_approved", "link_to_review", "fresh_expired",
                "fresh_scope_mismatch"}


def build_variant(name):
    family, edit, _ = VARIANTS[name]
    capsule = build_case(family)
    edit(capsule)
    return resealed(capsule)


def contract_valid(capsule):
    try:
        ic.validate_capsule(copy.deepcopy(capsule))
    except Exception:  # noqa: BLE001 - any rejection means not contract-valid
        return False
    return True


def states(capsule):
    return run(CANDIDATE, capsule)["state"], run(BASELINE, capsule)["state"]


def measured():
    """name -> (candidate state, baseline state) over the contract-valid variants."""
    return {n: states(c) for n in VARIANTS if contract_valid(c := build_variant(n))}


def approval_chain_intact(capsule):
    """Independent restatement of the approval-chain conditions the contract describes."""
    by_id = {e["event_id"]: e for e in capsule["events"]}
    for action in kind_of(capsule, "ACTION"):
        links = [x for x in kind_of(capsule, "APPROVAL_LINK")
                 if x["local_token"] == action["approval_token"]]
        approval = by_id.get(links[0]["approval_ref"]) if len(links) == 1 else None
        if not approval or approval["kind"] != "APPROVAL":
            return False
        review = by_id.get(approval["review_ref"])
        if not review or review["kind"] != "REVIEW" or not review["approved"]:
            return False
        if not review["at"] < approval["at"] <= links[0]["at"] < action["at"]:
            return False
        if not action["at"] < approval["valid_until"]:
            return False
        if not review["scope"] == approval["scope"] == action["scope"]:
            return False
        if not (review["artifact_commitment"] == approval["artifact_commitment"]
                == action["artifact_commitment"]):
            return False
    return bool(kind_of(capsule, "ACTION"))


# --- 1. the tie belongs to the published fixtures ----------------------------------------------

@pytest.mark.parametrize("family", FAMILIES)
def test_candidate_and_baseline_tie_on_each_published_fixture(family):
    capsule = build_case(family)
    assert contract_valid(capsule)
    assert len(set(states(capsule))) == 1, family


def test_the_three_published_fixtures_cover_all_three_response_states():
    assert {states(build_case(f))[0] for f in FAMILIES} == set(STATES)


@pytest.mark.parametrize("family", FAMILIES)
def test_each_published_fixture_has_published_truth_and_both_methods_match_its_state(family):
    capsule = build_case(family)
    truth = STORE.truth_for(capsule)
    assert states(capsule) == (truth["state"], truth["state"])


def published_ic_cases():
    """Every IC case with published truth, rebuilt with the public generators only."""
    doc = json.loads((GOLDEN / "ic_fixture_set.json").read_text(encoding="utf-8"))
    for case in doc["cases"]:
        kind, _, rest = case["case_id"].partition("/")
        capsule = IC.generate(case["family"], case["index"]) if kind == "fixture-run" \
            else build_case(rest)
        yield case, capsule


def test_the_tie_holds_on_every_case_with_published_truth():
    cases = list(published_ic_cases())
    assert len(cases) >= len(FAMILIES)
    for case, capsule in cases:
        assert evidence_commitment(capsule) == case["capsule_commitment"]
        cand, base = states(capsule)
        assert cand == base == case["truth"]["state"], case["case_id"]


def test_on_every_published_finding_the_candidate_cites_exactly_the_required_refs():
    findings = [(c, k) for c, k in published_ic_cases() if c["truth"]["state"] == FINDINGS]
    assert findings
    for case, capsule in findings:
        required = sorted(case["truth"]["defects"][0]["required_refs"])
        assert sorted(run(CANDIDATE, capsule)["findings"][0]["evidence_refs"]) == required
        baseline_refs = run(BASELINE, capsule)["findings"][0]["evidence_refs"]
        assert set(required) < set(baseline_refs)


# --- 2. the methods are not equivalent elsewhere ----------------------------------------------

def test_every_variant_is_contract_valid_once_resealed():
    assert [n for n in VARIANTS if not contract_valid(build_variant(n))] == []


def test_an_unsealed_edit_is_rejected_so_the_reseal_is_needed():
    capsule = build_case("stale_authority")
    edit_expired(capsule)
    assert not contract_valid(capsule)


def test_the_methods_return_different_states_on_some_contract_valid_variants():
    result = measured()
    total = len(result)
    differing = {n for n, (cand, base) in result.items() if cand != base}
    assert total == len(VARIANTS)
    assert 0 < len(differing) < total
    # Both directions occur: the baseline abstains on some, the candidate on others.
    assert any(result[n][1] == ABSTAIN for n in differing)
    assert any(result[n][0] == ABSTAIN for n in differing)


def test_variants_that_diverge_are_exactly_the_ones_the_two_methods_read_differently():
    result = measured()
    differing = {n for n, (cand, base) in result.items() if cand != base}
    # Candidate abstains because its chain check fails, baseline answers from conditions only.
    for name in CHAIN_BROKEN - {"link_to_review"}:
        assert not approval_chain_intact(build_variant(name)), name
        assert result[name][0] == ABSTAIN, name
        assert name in differing, name
    # Both abstain when the link points at the wrong kind (baseline checks the review kind).
    assert result["link_to_review"] == (ABSTAIN, ABSTAIN)
    # A same-instant tie with different conditions is genuine ambiguity: both abstain.
    assert result["policy_tie_other_condition"] == (ABSTAIN, ABSTAIN)
    # A same-instant tie with the same condition: the candidate decides, the baseline abstains.
    assert result["policy_tie_same_condition"] == (FINDINGS, ABSTAIN)
    assert approval_chain_intact(build_variant("policy_tie_same_condition"))


def test_baseline_never_reads_chain_validity():
    """The baseline answer on a chain-broken edit equals its answer on the unedited capsule."""
    for name in CHAIN_BROKEN - {"link_to_review", "no_action"}:
        family = VARIANTS[name][0]
        assert states(build_variant(name))[1] == states(build_case(family))[1], name


def test_candidate_clean_state_requires_an_intact_chain():
    for name in VARIANTS:
        capsule = build_variant(name)
        if run(CANDIDATE, capsule)["state"] != ABSTAIN:
            assert approval_chain_intact(capsule), name


def test_the_baseline_answers_clean_where_the_candidate_abstains_on_a_broken_chain():
    result = measured()
    clean_over_broken = [n for n, (cand, base) in result.items()
                         if cand == ABSTAIN and base == CLEAR]
    assert clean_over_broken, "expected at least one edit where the baseline reports no deviation"
    for name in clean_over_broken:
        assert not approval_chain_intact(build_variant(name)), name


# --- 3. evidence precision ---------------------------------------------------------------------

def test_baseline_cites_every_event_plus_completeness_candidate_cites_a_strict_subset():
    capsule = build_case("stale_authority")
    cited = {name: run(fn, capsule)["findings"][0]["evidence_refs"]
             for name, fn in (("candidate", CANDIDATE), ("baseline", BASELINE))}
    every_ref = {e["event_id"] for e in capsule["events"]} | {"$completeness"}
    assert set(cited["baseline"]) == every_ref
    assert len(cited["baseline"]) == len(capsule["events"]) + 1
    assert set(cited["candidate"]) < set(cited["baseline"])
    assert len(cited["candidate"]) < len(cited["baseline"])


def test_candidate_cites_exactly_the_published_required_refs():
    capsule = build_case("stale_authority")
    required = STORE.truth_for(capsule)["defects"][0]["required_refs"]
    assert sorted(run(CANDIDATE, capsule)["findings"][0]["evidence_refs"]) == sorted(required)
    assert set(required) < set(run(BASELINE, capsule)["findings"][0]["evidence_refs"])


# --- 4. what each profile does with the difference --------------------------------------------

def scored(profile_id, family, method):
    capsule = build_case(family)
    binding = replace(IC, profile=profile_module.load(profile_id))
    return score_response(binding, capsule, STORE.truth_for(capsule), run(method, capsule), OK)


def test_min_1_binary_rule_gives_both_methods_full_evidence_credit_and_equal_scores():
    result = {n: scored(MIN_1, "stale_authority", m)
              for n, m in (("candidate", CANDIDATE), ("baseline", BASELINE))}
    assert result["candidate"]["dimensions"]["evidence"] == 1.0
    assert result["baseline"]["dimensions"]["evidence"] == 1.0
    assert result["candidate"]["score"] == result["baseline"]["score"]


def test_min_2_precision_rule_gives_the_baseline_lower_evidence_credit():
    capsule = build_case("stale_authority")
    required = STORE.truth_for(capsule)["defects"][0]["required_refs"]
    cited_baseline = run(BASELINE, capsule)["findings"][0]["evidence_refs"]
    cand = scored(MIN_2, "stale_authority", CANDIDATE)
    base = scored(MIN_2, "stale_authority", BASELINE)
    assert cand["dimensions"]["evidence"] == 1.0
    # precision * recall, recomputed here from the sets: recall is 1, precision is |req|/|cited|
    expected = (len(required) / len(cited_baseline)) * 1.0
    assert base["dimensions"]["evidence"] == pytest.approx(expected)
    assert base["dimensions"]["evidence"] < cand["dimensions"]["evidence"]
    assert base["score"] < cand["score"]
    # the two other composite dimensions are the same, so the evidence term is the whole gap
    assert base["dimensions"]["detection"] == cand["dimensions"]["detection"]
    assert base["dimensions"]["calibration"] == cand["dimensions"]["calibration"]


def test_min_2_evidence_credit_function_on_the_two_citation_sets():
    capsule = build_case("stale_authority")
    required = STORE.truth_for(capsule)["defects"][0]["required_refs"]
    p1, p2 = profile_module.load(MIN_1), profile_module.load(MIN_2)
    for method, equal_to_required in ((CANDIDATE, True), (BASELINE, False)):
        cited = run(method, capsule)["findings"][0]["evidence_refs"]
        assert evidence_credit(p1, required, cited) == 1.0
        assert (evidence_credit(p2, required, cited) == 1.0) is equal_to_required


@pytest.mark.parametrize("family", ["fresh_review", "incomplete"])
def test_min_2_does_not_separate_the_fixtures_with_no_finding(family):
    """No finding means no citation to weigh: both profiles still tie on those two fixtures."""
    for profile_id in (MIN_1, MIN_2):
        a = scored(profile_id, family, CANDIDATE)
        b = scored(profile_id, family, BASELINE)
        assert a["score"] == b["score"], (profile_id, family)


def test_min_2_separates_the_published_fixture_set_only_through_citation_precision():
    gaps = {}
    for profile_id, family in product((MIN_1, MIN_2), FAMILIES):
        gap = (scored(profile_id, family, CANDIDATE)["score"]
               - scored(profile_id, family, BASELINE)["score"])
        gaps[profile_id, family] = gap
    assert all(gaps[MIN_1, f] == 0 for f in FAMILIES)
    assert [f for f in FAMILIES if gaps[MIN_2, f] != 0] == ["stale_authority"]
    assert gaps[MIN_2, "stale_authority"] > 0


# --- 5. what MIN-2 pays when the states differ -------------------------------------------------

def payoff(profile_id, truth_state, response_state):
    matrix = profile_module.load(profile_id).state_payoff
    return matrix[truth_state][response_state]


def test_min_1_declares_no_payoff_matrix_and_min_2_does():
    assert profile_module.load(MIN_1).state_payoff is None
    assert profile_module.load(MIN_2).state_payoff is not None


def test_under_min_2_two_different_states_are_paid_differently_under_every_truth():
    """For every diverging pair measured above, the matrix cells differ under all three truths,
    so which method scores higher depends only on which truth is right for that capsule."""
    differing = {n: pair for n, pair in measured().items() if pair[0] != pair[1]}
    assert differing
    for name, (cand, base) in differing.items():
        for truth_state in STATES:
            assert payoff(MIN_2, truth_state, cand) != payoff(MIN_2, truth_state, base), (
                name, truth_state)


def hypothetical_truth(capsule, state):
    """A truth record for scoring only: the witness set the candidate cites on the unedited
    capsule stands in for 'required refs' (an assumption, not published truth)."""
    if state != FINDINGS:
        return {"state": state, "defects": []}
    required = run(CANDIDATE, build_case("stale_authority"))["findings"][0]["evidence_refs"]
    return {"state": state, "defects": [{"code": "STALE_APPROVAL", "severity": "HIGH",
                                         "required_refs": sorted(required)}]}


def test_payoff_consequences_by_truth_for_each_diverging_variant():
    """Score both methods against each possible truth state with the public scorer.

    No truth is published for the edited capsules, so this is a table of consequences, not a
    ranking: the candidate wins under some truths and the baseline under others."""
    binding = replace(IC, profile=profile_module.load(MIN_2))
    wins = {"candidate": 0, "baseline": 0, "tie": 0}
    for name, (cand_state, base_state) in measured().items():
        if cand_state == base_state:
            continue
        capsule = build_variant(name)
        for truth_state in STATES:
            truth = hypothetical_truth(capsule, truth_state)
            s = {m: score_response(binding, capsule, truth, run(fn, capsule), OK)
                 for m, fn in (("candidate", CANDIDATE), ("baseline", BASELINE))}
            assert s["candidate"]["valid"] and s["baseline"]["valid"], (name, truth_state)
            for m, fn in (("candidate", CANDIDATE), ("baseline", BASELINE)):
                cell = s[m]["payoff"]["cell"]
                assert cell == payoff(MIN_2, truth_state, run(fn, capsule)["state"])
            delta = s["candidate"]["score"] - s["baseline"]["score"]
            wins["candidate" if delta > 0 else "baseline" if delta < 0 else "tie"] += 1
    # Both directions occur, so the profile separates the methods but neither dominates.
    assert wins["candidate"] > 0 and wins["baseline"] > 0


def test_min_1_floor_ties_that_min_2_breaks_for_an_abstention_against_a_clean_answer():
    """Where the candidate abstains and the baseline says clean, and the record is truly clean
    or truly abstain, MIN-1 scores an abstention at the floor either way (LIMITATIONS item on
    abstention). MIN-2 pays the abstention instead."""
    capsule = build_variant("fresh_expired")
    assert states(capsule) == (ABSTAIN, CLEAR)
    abstain_truth = {"state": ABSTAIN, "defects": []}
    floors = {}
    for profile_id in (MIN_1, MIN_2):
        binding = replace(IC, profile=profile_module.load(profile_id))
        floors[profile_id] = {
            m: score_response(binding, capsule, abstain_truth, run(fn, capsule), OK)["score"]
            for m, fn in (("candidate", CANDIDATE), ("baseline", BASELINE))}
    assert floors[MIN_1]["candidate"] == floors[MIN_1]["baseline"]  # both at the epsilon floor
    assert floors[MIN_2]["candidate"] > floors[MIN_2]["baseline"]
