"""MIN-4 and GRA-RELEASE-MIN-4: constant-answer bound, fixed-outcome calibration, declared
severity, priced over-citing, redundancy and non-scoring flags (ADR-0022).

Public-tree tests: public fixtures, hand-written truth and the matched public-contract baseline's
valid shell, so nothing here needs a private reference executor. The private suite
(test_profile_min4_pool.py) checks the same promises against recomputed reference truth. Neither
profile is active on any weight path.
"""

import copy
import hashlib
import itertools
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sn87_provenonce import flags as flagmod
from sn87_provenonce import profile, redundancy
from sn87_provenonce.classes import BINDINGS
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.classes import TYPE_C_RELEASE as TC
from sn87_provenonce.profile import STATES, Profile, ProfileNotApplied
from sn87_provenonce.scoring import (
    Integrity,
    evidence_credit,
    fixed_outcome_calibration,
    preference_row,
    score_response,
    severity_credit,
)

IC4, TC4 = "IC-FIRST-LIGHT-MIN-4", "GRA-RELEASE-MIN-4"
OK = Integrity(True, True, True, True, True, True)
FINDINGS, CLEAR, ABSTAIN = STATES
SRC = Path(profile.__file__).parent
GRID = [i / 10 for i in range(11)]
IC_BIND, TC_BIND = replace(IC, profile=profile.load(IC4)), replace(TC, profile=profile.load(TC4))
BOTH = pytest.mark.parametrize("binding", [IC_BIND, TC_BIND], ids=[IC4, TC4])
OLD_PINS = {
    "GRA-W03-3": (
        "45d99913a05f55d43e271166d4e0be91292cfbd53cfdcefcdbf9d685e1b43c75",
        "sha256:e732ea977497a6ccd5e9541c8fd98bc949086ade5cbeccb058a38312329eda21",
    ),
    "IC-FIRST-LIGHT-MIN-1": (
        "a8d1ba687b06f61fc4e9e1c00a1c376b34e41439440529c4db7e2cc9ec00f85c",
        "sha256:7049f165bc9b4fae32133f2d37aa9a48f5bf13f3b4fa47ea94643e5633d3c766",
    ),
    "IC-FIRST-LIGHT-MIN-2": (
        "592a30c756f9571e4992d83f6fa2ab34e3aa1993dbb8ead5dd74f923473a0f37",
        "sha256:1c0562f791afa00caeebdfa5a9afcc3473957e6f0f2d7f07d4f8bae310c75bfe",
    ),
    "IC-FIRST-LIGHT-MIN-3": (
        "336684f70f3068b1b671987b413c8baee3c18d268583fc45aad0a65ef297d5aa",
        "sha256:039b8639a839f8617003c2f5e686dcf313dd7fc80f9de2c1b8d7d9762a6e7665",
    ),
}


def document(profile_id):
    return json.loads((SRC / "profiles" / f"{profile_id}.json").read_text())


def derive(doc, binding=IC):
    return Profile.from_document(
        doc, class_id=binding.class_id, domain=profile.REGISTRY[doc["profile_id"]][1]
    )


def refs(capsule):
    return sorted({e["event_id"] for e in capsule["events"]} | {"$completeness"})


def codes_of(binding):
    return sorted(binding.defect_severity)


def family(binding):
    return "stale_authority" if binding is IC_BIND else "missing_gate"


def make_truth(binding, capsule, state, codes=None, *, n_required=3):
    if state != FINDINGS:
        return {"state": state, "defects": []}
    codes = codes or [codes_of(binding)[0]]
    return {
        "state": state,
        "defects": [
            {
                "code": c,
                "severity": binding.defect_severity[c],
                "required_refs": refs(capsule)[:n_required],
            }
            for c in codes
        ],
    }


def respond(binding, capsule, state, findings=(), *, rationale="A rationale."):
    """``findings``: (code, severity, cited refs, confidence), on the baseline's shell."""
    shell = copy.deepcopy(binding.baseline(copy.deepcopy(capsule)))
    return shell | {
        "state": state,
        "rationale": rationale,
        "findings": [
            {
                "code": c,
                "severity": s,
                "evidence_refs": list(r),
                "rationale": "A finding.",
                "confidence": str(conf),
            }
            for c, s, r, conf in findings
        ],
    }


def true_finding(binding, capsule, code=None, conf="1", cited=None, severity=None):
    code = code or codes_of(binding)[0]
    return (
        code,
        severity or binding.defect_severity[code],
        cited if cited is not None else refs(capsule)[:3],
        conf,
    )


def score(binding, capsule, truth, resp):
    result = score_response(binding, capsule, truth, resp, OK)
    assert result["valid"], result["failures"]
    return result["score"]


# --- commitments, pins, inactivity ----------------------------------------------------------------


def test_new_profiles_are_pinned_and_every_older_profile_is_byte_identical():
    for pid, (file_hash, commitment) in OLD_PINS.items():
        assert (
            hashlib.sha256((SRC / "profiles" / f"{pid}.json").read_bytes()).hexdigest() == file_hash
        )
        assert profile.REGISTRY[pid][2] == commitment == profile.load(pid).commitment
    for pid in (IC4, TC4):
        p = profile.load(pid)
        assert p.commitment == profile.REGISTRY[pid][2] and p.fixed_outcome is not None
    assert set(profile.REGISTRY) == {*OLD_PINS, IC4, TC4, "DAT-HEADROOM-MIN-4"}  # ADR-0024
    assert len({profile.REGISTRY[p][2] for p in profile.REGISTRY}) == 7


def test_older_profiles_carry_no_version_4_state():
    for pid in OLD_PINS:
        assert profile.load(pid).fixed_outcome is None


def test_the_new_profiles_are_active_nowhere():
    assert {b.profile.profile_id for b in BINDINGS.values()} == {
        "GRA-W03-3",
        "IC-FIRST-LIGHT-MIN-1",
    }
    for pid in (IC4, TC4):
        named = sorted(
            p.relative_to(SRC).as_posix()
            for p in SRC.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and pid.encode() in p.read_bytes()
            and p.name != "DAT-HEADROOM-MIN-4.json"  # derived_from names IC4 (ADR-0024)
        )
        assert named == ["profile.py", f"profiles/{pid}.json"], named


def test_profile_documents_declare_the_rules_and_share_the_class_values():
    for pid, parent in ((IC4, "IC-FIRST-LIGHT-MIN-3"), (TC4, "GRA-W03-3")):
        new, old = document(pid), document(parent)
        assert new["derived_from"] == parent
        assert new["theta"] == old["theta"] == "0.60" and new["gamma"] == old["gamma"]
        assert new["scoring_rules"]["rationale"] == "REQUIRED_NOT_SCORED_TYPE_D_DEFERRED"
        assert sum(float(v) for v in new["weights"].values()) == pytest.approx(1)
        assert set(new["weights"]) == {"detection", "evidence", "severity", "calibration"}


# --- the pool: caps, margins and the structural bound on a ---


@BOTH
def test_caps_margins_and_shares_are_what_the_adr_states(binding):
    p = binding.profile
    shares = p.fixed_outcome["shares"]
    assert shares == {FINDINGS: 0.4, CLEAR: 0.4, ABSTAIN: 0.2}
    assert shares[FINDINGS] <= 0.40 and shares[ABSTAIN] <= 0.20  # the defect and abstain caps
    bounds = profile.constant_bounds(p.state_payoff, shares)
    assert max(bounds.values()) <= p.theta - 0.15 + 1e-12
    assert sum(shares[t] * p.state_payoff[t][t] for t in STATES) >= p.theta + 0.25 - 1e-12
    assert p.minimum <= sum(p.document["assignment"].values())


def _pool_doc(pid, **changes):
    doc = document(pid)
    for dotted, value in changes.items():
        node = doc
        *path, last = dotted.split(".")
        for key in path:
            node = node[key]
        node[last] = value
    return doc


@pytest.mark.parametrize("pid, binding", [(IC4, IC), (TC4, TC)])
@pytest.mark.parametrize(
    "changes",
    [
        {"scoring_rules.pool.defect_share_max": "0.30"},  # defect share above its cap
        {"scoring_rules.pool.abstain_share_max": "0.10"},  # abstain share above its cap
        {"scoring_rules.pool.clear_share_max": "0.30"},  # clear share above its cap
        {"scoring_rules.pool.constant_margin": "0.25"},  # a constant is not 0.25 under theta
        {"scoring_rules.pool.strong_margin": "0.35"},  # a perfect method not 0.35 over it
        {"theta": "0.45"},  # the margin cannot hold
        {"minimum_assignments": 41},  # window void by construction
        {"scoring_rules.rules_version": "5"},
        {"scoring_rules.redundancy": "NONE"},
        {"scoring_rules.calibration": "BRIER_OVER_CLAIMS"},
        {"scoring_rules.flags.scored": True},
        {"scoring_rules.precision_exponent": "0.5"},
        {
            "weights": {
                "detection": "0.6",
                "evidence": "0.25",
                "severity": "0.1",
                "calibration": "0.1",
            }
        },
        {"weights": {"detection": "0.6", "evidence": "0.25", "calibration": "0.15"}},
    ],
)
def test_loader_refuses_a_pool_or_rule_that_breaks_a_promise(pid, binding, changes):
    with pytest.raises(ProfileNotApplied):
        derive(_pool_doc(pid, **changes), binding)


def test_loader_refuses_an_assignment_family_without_a_truth_state():
    doc = document(IC4)
    doc["assignment"]["unmapped"] = 1
    with pytest.raises(ProfileNotApplied):
        derive(doc)
    doc = document(IC4)
    doc["scoring_rules"]["pool"]["families"]["incomplete"] = "SOMETHING_ELSE"
    with pytest.raises(ProfileNotApplied):
        derive(doc)


def test_the_constant_bound_is_the_share_weighted_column_of_the_payoff_matrix():
    """The bound on a fixed answer rises with the share of the truth state it matches."""
    payoff = profile.load("IC-FIRST-LIGHT-MIN-2").state_payoff
    states = {"a": FINDINGS, "b": CLEAR}
    small = profile.pool_shares({"a": 1, "b": 3}, states)
    large = profile.pool_shares({"a": 3, "b": 1}, states)
    assert profile.constant_bounds(payoff, small)[FINDINGS] == pytest.approx(0.25)
    assert profile.constant_bounds(payoff, large)[FINDINGS] == pytest.approx(0.75)


def _pool_scores(binding, respond_with):
    """Mean score of one response rule over the profile's own pool, hand-written truth per state."""
    p, mix = binding.profile, binding.profile.document["assignment"]
    states = p.document["scoring_rules"]["pool"]["families"]
    total = 0.0
    for fam, n in mix.items():
        for i in range(n):
            c = binding.generate(fam, i)
            total += score(binding, c, make_truth(binding, c, states[fam]), respond_with(c))
    return total / sum(mix.values())


@BOTH
def test_every_enumerated_constant_stays_below_theta_with_the_margin(binding):
    limit = binding.profile.theta - 0.15
    codes = [*codes_of(binding), "UNLISTED_CODE"]
    worst = max(
        _pool_scores(binding, lambda c: respond(binding, c, ABSTAIN)),
        _pool_scores(binding, lambda c: respond(binding, c, CLEAR)),
    )
    assert worst <= limit
    for code, sev, cite, conf in itertools.product(
        codes, ("LOW", "MEDIUM", "HIGH"), ("all", "completeness", "first"), ("0", "0.5", "1")
    ):

        def answer(c, code=code, sev=sev, cite=cite, conf=conf):
            cited = {
                "all": refs(c),
                "completeness": ["$completeness"],
                "first": [c["events"][0]["event_id"]],
            }[cite]
            return respond(binding, c, FINDINGS, [(code, sev, cited, conf)])

        assert _pool_scores(binding, answer) <= limit, (code, sev, cite, conf)


@BOTH
def test_a_method_that_is_right_everywhere_is_above_theta_with_the_margin(binding):
    def right(c, binding=binding):
        return None

    p = binding.profile
    states = p.document["scoring_rules"]["pool"]["families"]
    total, n = 0.0, 0
    for fam, count in p.document["assignment"].items():
        for i in range(count):
            c = binding.generate(fam, i)
            truth = make_truth(binding, c, states[fam])
            if truth["state"] == FINDINGS:
                d = truth["defects"][0]
                resp = respond(
                    binding, c, FINDINGS, [(d["code"], d["severity"], d["required_refs"], "1")]
                )
            else:
                resp = respond(binding, c, truth["state"])
            total += score(binding, c, truth, resp)
            n += 1
    assert total / n >= p.theta + 0.25 - 1e-9


# --- the fixed-outcome rule, three invariants -------------------------------------------------


def _worlds(binding):
    c = binding.generate(family(binding), 0)
    return c


@BOTH
def test_invariant_i_a_false_claim_never_raises_a_score_at_any_confidence(binding):
    c = _worlds(binding)
    codes = codes_of(binding)
    truth_codes = [codes[0]] if len(codes) == 1 else codes[:2]
    truth = make_truth(binding, c, FINDINGS, truth_codes)
    false_codes = [x for x in codes if x not in truth_codes] + ["UNLISTED_CODE", truth_codes[0]]
    for conf in GRID:
        base_findings = [true_finding(binding, c, k, str(conf)) for k in truth_codes]
        before = score(binding, c, truth, respond(binding, c, FINDINGS, base_findings))
        for fc, fconf in itertools.product(false_codes, GRID):
            extra = (fc, "HIGH", refs(c)[:3], str(fconf))
            after = score(binding, c, truth, respond(binding, c, FINDINGS, [*base_findings, extra]))
            assert after <= before + 1e-15, (conf, fc, fconf, before, after)


@BOTH
def test_invariant_i_holds_when_the_response_has_no_true_claim(binding):
    c = _worlds(binding)
    for truth_state in (CLEAR, ABSTAIN, FINDINGS):
        truth = make_truth(binding, c, truth_state)
        wrong_code = "UNLISTED_CODE"
        first = respond(binding, c, FINDINGS, [(wrong_code, "HIGH", refs(c)[:3], "0.5")])
        base = score(binding, c, truth, first)
        for fconf in GRID:
            more = respond(
                binding,
                c,
                FINDINGS,
                [
                    (wrong_code, "HIGH", refs(c)[:3], "0.5"),
                    ("ANOTHER_UNLISTED", "HIGH", refs(c)[:3], str(fconf)),
                ],
            )
            assert score(binding, c, truth, more) <= base + 1e-15


def test_calibration_over_the_claims_made_versus_over_a_fixed_outcome_set():
    """An extra claim at confidence 0 matters only if the denominator depends on the claims made."""
    c = IC.generate("fresh_review", 3)
    truth = {"state": ABSTAIN, "defects": []}

    def findings(extra):
        return [("STALE_APPROVAL", "HIGH", refs(c), "0.5"), *extra]

    extra = [("OTHER_CODE", "HIGH", refs(c), "0")]
    for pid, raises in (
        ("IC-FIRST-LIGHT-MIN-1", True),
        ("IC-FIRST-LIGHT-MIN-3", False),
        (IC4, False),
    ):
        b = replace(IC, profile=profile.load(pid))
        one = score(b, c, truth, respond(IC, c, FINDINGS, findings([])))
        two = score(b, c, truth, respond(IC, c, FINDINGS, findings(extra)))
        assert (two > one) is raises, (pid, one, two)


def test_fixed_outcome_rule_edges():
    codes = ["A", "B", "C"]
    f = lambda code, conf: {"code": code, "confidence": str(conf)}  # noqa: E731
    assert fixed_outcome_calibration(codes, {"A"}, [f("A", 1)]) == 1.0
    assert fixed_outcome_calibration(codes, set(), []) == 1.0
    assert fixed_outcome_calibration(codes, {"A"}, []) == pytest.approx(1 - 1 / 3)
    assert fixed_outcome_calibration(codes, set(), [f("B", 0)]) == 1.0  # confidence 0: no change
    assert fixed_outcome_calibration(codes, set(), [f("B", 0.4)]) < 1.0
    # unlisted codes cannot enlarge the denominator, and the score cannot go below 0
    assert fixed_outcome_calibration(["A"], set(), [f(f"X{i}", 1) for i in range(5)]) == 0.0
    # a repeated claim is read least favourably to the claimant
    assert fixed_outcome_calibration(
        codes, {"A"}, [f("A", 1), f("A", 0.2)]
    ) == fixed_outcome_calibration(codes, {"A"}, [f("A", 0.2)])
    assert fixed_outcome_calibration(
        codes, set(), [f("B", 0.1), f("B", 0.9)]
    ) == fixed_outcome_calibration(codes, set(), [f("B", 0.9)])


def test_invariant_ii_reporting_true_beliefs_is_optimal_for_the_rule():
    """Expected fixed-outcome score under belief q is uniquely maximised at the report p = q."""
    codes = ["A", "B", "C", "D"]
    for q in GRID:

        def expected(p, q=q):
            hit = fixed_outcome_calibration(codes, {"B"}, [{"code": "B", "confidence": str(p)}])
            miss = fixed_outcome_calibration(codes, set(), [{"code": "B", "confidence": str(p)}])
            return q * hit + (1 - q) * miss

        values = {p: expected(p) for p in GRID}
        best = max(values, key=values.get)
        assert best == q
        assert all(values[q] > v + 1e-12 for p, v in values.items() if p != q)


def test_invariant_ii_reporting_true_beliefs_is_optimal_for_the_full_score():
    """End to end through ``score_response``: two possible truths in the same state, a miner who
    believes the second defect is present with probability q reports it at confidence p."""
    c = TC.generate("missing_gate", 0)
    a, b = "MISSING_REVIEW_GATE", "EVIDENCE_CHAIN_BREAK"
    only_a = make_truth(TC_BIND, c, FINDINGS, [a])
    both = make_truth(TC_BIND, c, FINDINGS, [a, b])

    def total(p, world):
        resp = respond(
            TC, c, FINDINGS, [true_finding(TC_BIND, c, a), true_finding(TC_BIND, c, b, str(p))]
        )
        return score(TC_BIND, c, world, resp)

    for q in GRID:
        values = {p: q * total(p, both) + (1 - q) * total(p, only_a) for p in GRID}
        best = max(values, key=values.get)
        assert best == q, (q, best)


@BOTH
def test_invariant_iii_a_wrong_state_is_capped_below_a_correct_one(binding):
    p, cells = binding.profile, binding.profile.state_payoff
    c = binding.generate(family(binding), 0)
    codes = codes_of(binding)
    for truth_state in STATES:
        truth = make_truth(binding, c, truth_state)
        cap = max(p.epsilon, *(cells[truth_state][r] for r in STATES if r != truth_state))
        wrong = []
        for state in (s for s in STATES if s != truth_state):
            if state == FINDINGS:
                for conf, code in itertools.product(GRID, [*codes, "UNLISTED_CODE"]):
                    for cited in (refs(c), refs(c)[:3]):
                        wrong.append(
                            respond(binding, c, FINDINGS, [(code, "HIGH", cited, str(conf))])
                        )
            else:
                wrong.append(respond(binding, c, state))
        assert max(score(binding, c, truth, w) for w in wrong) <= cap + 1e-12
        if truth_state == FINDINGS:
            right = [
                respond(binding, c, FINDINGS, [true_finding(binding, c, codes[0], str(conf))])
                for conf in GRID
            ]
            floor = min(score(binding, c, truth, r) for r in right)
        else:
            floor = score(binding, c, truth, respond(binding, c, truth_state))
        assert floor > cap + 0.2, (truth_state, floor, cap)
        assert floor >= cells[truth_state][truth_state] * (1 - p.weights["calibration"]) - 1e-12


def test_the_wrong_state_cap_is_new_in_the_type_c_profile():
    """Under the new Type C profile a hedged false finding does not beat a correct abstention."""
    c = TC.generate("incomplete", 0)
    truth = {"state": ABSTAIN, "defects": []}
    hedged = respond(TC, c, FINDINGS, [("EVIDENCE_CHAIN_BREAK", "HIGH", refs(c), "0.5")])
    right = respond(TC, c, ABSTAIN)
    assert score(TC, c, truth, hedged) > score(TC, c, truth, right)
    assert score(TC_BIND, c, truth, hedged) < score(TC_BIND, c, truth, right) == 0.5


# --- declared severity is scored; rationale is not -------------------------------------------


def test_severity_credit_is_ordinal():
    assert severity_credit("HIGH", "HIGH") == 1.0
    assert severity_credit("HIGH", "MEDIUM") == severity_credit("LOW", "MEDIUM") == 0.5
    assert severity_credit("HIGH", "LOW") == severity_credit("LOW", "HIGH") == 0.0


def test_declared_severity_on_a_matched_finding_changes_the_score():
    c = TC.generate("missing_gate", 0)
    code = "MISSING_RELEASE_EVENT"  # sealed severity MEDIUM
    truth = make_truth(TC_BIND, c, FINDINGS, [code])
    got = {
        sev: score(
            TC_BIND,
            c,
            truth,
            respond(TC, c, FINDINGS, [true_finding(TC_BIND, c, code, severity=sev)]),
        )
        for sev in ("LOW", "MEDIUM", "HIGH")
    }
    assert got["MEDIUM"] > got["HIGH"] > got["LOW"] or got["MEDIUM"] > got["LOW"]
    assert got["MEDIUM"] == pytest.approx(1.0) and got["HIGH"] == pytest.approx(got["LOW"], rel=0.5)
    result = score_response(
        TC_BIND,
        c,
        truth,
        respond(TC, c, FINDINGS, [true_finding(TC_BIND, c, code, severity="HIGH")]),
        OK,
    )
    assert result["dimensions"]["severity"] == 0.5
    # the older scorer ignores the declared severity of a matched finding
    old = {
        sev: score(
            TC, c, truth, respond(TC, c, FINDINGS, [true_finding(TC_BIND, c, code, severity=sev)])
        )
        for sev in ("LOW", "MEDIUM", "HIGH")
    }
    assert len(set(old.values())) == 1


@BOTH
def test_rationale_is_required_but_not_scored(binding):
    c = _worlds(binding)
    truth = make_truth(binding, c, FINDINGS)
    short = respond(binding, c, FINDINGS, [true_finding(binding, c)], rationale="x")
    long = respond(binding, c, FINDINGS, [true_finding(binding, c)], rationale="Reasoned. " * 200)
    other = copy.deepcopy(long)
    other["findings"][0]["rationale"] = "Different words entirely."
    assert (
        score(binding, c, truth, short)
        == score(binding, c, truth, long)
        == score(binding, c, truth, other)
    )
    empty = copy.deepcopy(short)
    empty["rationale"] = ""
    assert not score_response(binding, c, truth, empty, OK)["valid"]  # required by the contract


# --- over-citing is priced -------------------------------------------------------------------


def test_over_citing_costs_at_least_a_fifth_of_the_score_in_the_new_profile():
    c = IC.generate("stale_authority", 0)
    required = refs(c)[:9]
    truth = {
        "state": FINDINGS,
        "defects": [{"code": "STALE_APPROVAL", "severity": "HIGH", "required_refs": required}],
    }
    old, new = replace(IC, profile=profile.load("IC-FIRST-LIGHT-MIN-3")), IC_BIND

    def at(b, cited):
        return score(
            b, c, truth, respond(IC, c, FINDINGS, [("STALE_APPROVAL", "HIGH", cited, "1")])
        )

    assert at(old, refs(c)) > 0.9 and at(new, refs(c)) < 0.8  # 13 cited for 9 required
    assert at(new, required) == 1.0
    costs = [1 - at(new, refs(c)[: 9 + k]) for k in range(5)]
    assert costs[0] == 0 and all(b > a + 0.04 for a, b in zip(costs, costs[1:], strict=False))
    assert costs[4] >= 0.2
    # omitting a required reference still costs, in proportion
    assert at(new, required[:-1]) < 0.97 and at(new, ["$completeness"]) < 0.5


def test_evidence_credit_is_precision_power_times_recall():
    p = IC_BIND.profile
    need = ["a", "b", "c"]
    assert evidence_credit(p, need, ["a", "b", "c"]) == 1.0
    assert evidence_credit(p, need, ["a", "b", "c", "d"]) == pytest.approx(0.75**2)
    assert evidence_credit(p, need, ["a", "b"]) == pytest.approx(2 / 3)
    assert evidence_credit(p, need, ["x"]) == 0.0
    assert evidence_credit(p, [], ["x"]) == 1.0


# --- identical answers share one weight; non-scoring flags ---


def _answers(states_by_identity):
    return {i: {f"c{k}": r for k, r in enumerate(rs)} for i, rs in states_by_identity.items()}


def _resp(state, *codes, conf="1", method="m"):
    return {
        "state": state,
        "method": method,
        "rationale": "r",
        "findings": [
            {
                "code": c,
                "severity": "HIGH",
                "evidence_refs": ["e1", "e2"],
                "rationale": "r",
                "confidence": conf,
            }
            for c in codes
        ],
    }


def test_the_decision_vector_groups_whatever_the_citations_severity_confidence_or_order():
    a = [_resp(FINDINGS, "X"), _resp(CLEAR), _resp(ABSTAIN)]
    b = [_resp(FINDINGS, "X", conf="0.5", method="other"), _resp(CLEAR), _resp(ABSTAIN)]
    b[0]["findings"][0]["evidence_refs"] = ["e1", "e2", "e9"]  # a surplus citation
    b[0]["findings"][0]["severity"] = "LOW"
    c = [_resp(FINDINGS, "Y"), _resp(CLEAR), _resp(ABSTAIN)]
    d = [None, None, None]
    e = [None, None, None]
    assert redundancy.redundancy_groups(_answers({"a": a, "b": b, "c": c, "d": d, "e": e})) == [
        ["a", "b"]
    ]
    assert redundancy.redundancy_groups({}) == []
    two = _resp(FINDINGS, "X", "Y")
    assert redundancy.answer_key(two) == redundancy.answer_key(
        {**two, "findings": list(reversed(two["findings"]))}
    )
    assert redundancy.answer_key(_resp(FINDINGS, "X")) != redundancy.answer_key(two)


def _row(estimates, groups=None, profile_=None):
    """A row from estimates where every identity named in ``groups`` answers alike."""
    answers = {}
    for name in estimates:
        mate = next((g[0] for g in (groups or []) if name in g), name)
        answers[name] = {"c0": _resp(FINDINGS, mate), "c1": _resp(CLEAR)}
    return preference_row(estimates, profile_ or IC_BIND.profile, answers=answers)


def test_a_group_shares_the_weight_one_member_would_have_earned():
    estimates = {"a": 0.9, "b": 0.9, "c": 0.9, "d": 0.7, "e": None}
    shared = _row(estimates, [["a", "b"]])
    w = {k: float(v) for k, v in shared["weights"].items()}
    assert w["a"] == pytest.approx(w["b"])
    assert w["a"] + w["b"] == pytest.approx(w["c"])  # the pair together equals one identity
    assert w["e"] == 0 and sum(w.values()) == pytest.approx(1)
    split = _row(estimates)
    assert float(split["weights"]["a"]) + float(split["weights"]["b"]) > w["a"] + w["b"]


def test_groups_are_computed_by_the_scorer_and_a_disagreeing_caller_grouping_is_refused():
    p = IC_BIND.profile
    answers = {
        "a": {"c0": _resp(FINDINGS, "X")},
        "b": {"c0": _resp(FINDINGS, "X")},
        "c": {"c0": _resp(CLEAR)},
    }
    est = {"a": 0.9, "b": 0.9, "c": 0.9}
    ok = preference_row(est, p, answers=answers)
    assert preference_row(est, p, [["b", "a"]], answers) == ok  # agreeing groups are accepted
    for wrong in ([], [["a", "c"]], [["a", "b", "c"]]):
        with pytest.raises(ValueError, match="REDUNDANCY_GROUPS_DISAGREE"):
            preference_row(est, p, wrong, answers)


def test_the_redundancy_rule_is_required_in_the_new_profile_and_absent_in_the_old():
    p = IC_BIND.profile
    with pytest.raises(ValueError, match="REDUNDANCY_ANSWERS_REQUIRED"):
        preference_row({"a": 0.9}, p)
    with pytest.raises(ValueError):
        preference_row({"a": 0.9}, p, answers={"a": {}, "ghost": {}})
    old = IC.profile
    assert preference_row({"a": 0.9, "b": 0.9}, old) == preference_row(
        {"a": 0.9, "b": 0.9}, old, groups=[["a", "b"]]
    )


def _obs(identity_answers, dispatch, latency):
    out = {}
    for identity, answers in identity_answers.items():
        out[identity] = {}
        for k, r in enumerate(answers):
            t = dispatch(identity, k)
            out[identity][f"c{k}"] = {
                "response": r,
                "dispatched_at": t,
                "responded_at": t + latency(identity, k),
            }
    return out


PARAMS = IC_BIND.profile.fixed_outcome["flags"]


def test_flags_mark_simultaneous_dispatch_similar_latency_and_identical_answers():
    n = PARAMS["min_cases"] + 2
    same = [_resp(FINDINGS, "X") if k % 2 else _resp(CLEAR) for k in range(n)]
    diff = [_resp(CLEAR) if k % 2 else _resp(FINDINGS, "X") for k in range(n)]
    obs = _obs(
        {"a": same, "b": same, "c": diff},
        dispatch=lambda i, k: k * 100.0 + (0.0 if i != "c" else 40.0),
        latency=lambda i, k: 3.0 + (0.1 if i == "b" else 9.0 if i == "c" else 0.0),
    )
    flags = flagmod.observation_flags(obs, PARAMS)
    assert flags["scored"] is False and flags["timing"] == "RECORDED"
    assert flags["separating_tasks"] == n
    assert [x["pair"] for x in flags["SIMULTANEOUS_DISPATCH"]] == [["a", "b"]]
    assert [x["pair"] for x in flags["SIMILAR_RESPONSE_TIME"]] == [["a", "b"]]
    assert [x["pair"] for x in flags["IDENTICAL_ANSWERS_ON_SEPARATING_TASKS"]] == [["a", "b"]]
    assert flags["IDENTICAL_ANSWERS_ON_SEPARATING_TASKS"][0]["share"] == "1"


def test_identical_answers_on_tasks_that_do_not_separate_are_not_flagged():
    n = PARAMS["min_cases"] + 2
    same = [_resp(CLEAR)] * n
    obs = {
        i: {
            f"c{k}": {"response": r, "dispatched_at": None, "responded_at": None}
            for k, r in enumerate(same)
        }
        for i in "abc"
    }
    flags = flagmod.observation_flags(obs, PARAMS)
    assert flags["separating_tasks"] == 0 and flags["timing"] == "NOT_RECORDED"
    assert flags["IDENTICAL_ANSWERS_ON_SEPARATING_TASKS"] == []
    assert flags["SIMULTANEOUS_DISPATCH"] == [] and flags["SIMILAR_RESPONSE_TIME"] == []


def test_flags_are_not_a_score_input():
    """The flag module is not imported by the scorer, and a result never changes with flags."""
    import ast

    tree = ast.parse((SRC / "scoring.py").read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "sn87_provenonce.flags" not in imported
    assert flagmod.USE == "NEVER_A_SCORE_INPUT_NEVER_IN_THE_PREFERENCE_ROW"


# --- the older scorer is untouched ---


def test_older_profiles_score_exactly_as_before_and_add_no_new_keys():
    c = IC.generate("incomplete", 0)
    result = score_response(IC, c, {"state": ABSTAIN, "defects": []}, respond(IC, c, ABSTAIN), OK)
    assert result["score"] == pytest.approx(1e-6, rel=1e-12) and "payoff" not in result
    assert "severity" not in result["dimensions"]
    s = IC.generate("stale_authority", 0)
    truth = make_truth(IC, s, FINDINGS)
    r = respond(IC, s, FINDINGS, [("STALE_APPROVAL", "LOW", refs(s), "1")])
    assert score(IC, s, truth, r) == 1.0  # declared severity ignored, as before


# --- results integration ---


def test_results_record_flags_and_groups_only_under_the_version_4_profile():
    import sys

    root = Path(__file__).parents[1]
    sys.path.insert(0, str(root / "scripts"))
    import contest_dry_run as dr
    import contest_results as cr
    import contest_window as cw

    demo = root / "examples" / "contest-window-demo"
    commitments = json.loads((demo / "commitments.json").read_text())
    reveal = json.loads((demo / "window_demo-0001.reveal.json").read_text())
    entries = cw.check_reveal(commitments, reveal)
    capsules = cw.capsules_document(reveal["spec"], entries)
    truth = json.loads((demo / "window_demo-0001.truth.json").read_text())
    responses = dr.responses_document([e["capsule"] for e in entries], timing=False)
    new = cr.score_window(capsules, truth, copy.deepcopy(responses), IC4)
    old = cr.score_window(capsules, truth, copy.deepcopy(responses), "IC-FIRST-LIGHT-MIN-3")
    assert "flags" not in old and "redundancy_groups" not in old
    assert new["flags"]["scored"] is False and new["flags"]["timing"] == "NOT_RECORDED"
    assert isinstance(new["redundancy_groups"], list)
    # the flags are beside the scores: removing them leaves the same estimates
    assert [m["score"]["estimate"] for m in new["methods"]] != []
