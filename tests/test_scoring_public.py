"""The public scorer on the published truth: what test_scoring.py checks with the executors.

Runs in the public tree. Truth comes from ``protocol/golden_truth``; the responses are built from
the truth (``golden_support.response_from_truth``) or are the public-contract baseline's. In the
private tree these tests also pass, using the same published truth, so the two trees run the
same assertions.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from golden_support import STORE, response_from_truth

from sn87_provenonce import bundle
from sn87_provenonce.baselines import BASELINES
from sn87_provenonce.canonical import canonical_bytes, parse_canonical
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.classes import TYPE_C_RELEASE as TC
from sn87_provenonce.institutional_v02 import contracts as ic_contracts
from sn87_provenonce.pilot import contracts as tc_contracts
from sn87_provenonce.scoring import Integrity, score_response

OK = Integrity(True, True, True, True, True, True)
WHEN = {"opened_at": "2026-10-04T00:00:00Z", "closed_at": "2026-10-04T00:00:00Z"}


def instances(binding):
    """The profile's full assignment at indices 0 to N, as the validator builds it."""
    document = binding.profile.document
    plan = [(f, "scored") for f, n in document["assignment"].items() for _ in range(n)]
    plan += [(f, "diagnostic") for f, n in document["diagnostics"].items() for _ in range(n)]
    out = []
    for index, (family, track) in enumerate(plan):
        capsule = binding.generate(family, index)
        out.append({"qid": capsule["qid"], "track": track, "family": family,
                    "capsule": capsule, "truth": STORE.truth_for(capsule)})
    return out


@pytest.fixture(scope="module", params=[IC, TC], ids=lambda b: b.class_id)
def bound(request):
    return request.param, instances(request.param)


def test_a_response_that_reproduces_the_truth_scores_one_on_every_scored_case(bound):
    binding, cases = bound
    for case in (c for c in cases if c["track"] == "scored"):
        response = response_from_truth(case["capsule"], case["truth"])
        binding_module = ic_contracts if binding is IC else tc_contracts
        binding_module.validate_differential(case["capsule"], response)
        result = score_response(binding, case["capsule"], case["truth"], response, OK)
        assert result["valid"] and result["score"] == pytest.approx(1), case["qid"]


def test_the_public_baseline_matches_the_published_truth_on_every_case(bound):
    """The statement that makes the truth no secret: the baseline reproduces it."""
    binding, cases = bound
    baseline = BASELINES[binding.class_id]
    for case in cases:
        response = baseline(parse_canonical(canonical_bytes(case["capsule"])))
        assert response["state"] == case["truth"]["state"], case["qid"]
        assert sorted(f["code"] for f in response["findings"]) == sorted(
            d["code"] for d in case["truth"]["defects"]), case["qid"]


def test_a_wrong_state_and_a_missing_finding_cost_the_score(bound):
    binding, cases = bound
    flagged = next(c for c in cases if c["truth"]["state"] == "FINDINGS")
    capsule, truth = flagged["capsule"], flagged["truth"]
    good = response_from_truth(capsule, truth)
    clean = deepcopy(good) | {"state": "NO_MATERIAL_DEVIATION", "findings": []}
    result = score_response(binding, capsule, truth, clean, OK)
    assert result["recall"] == 0 and result["score"] == pytest.approx(1e-6)
    extra = deepcopy(good)
    extra["findings"].append(dict(deepcopy(good["findings"][0]), severity="LOW"))
    duplicated = score_response(binding, capsule, truth, extra, OK)
    assert duplicated["fp_cost"] == 1 and duplicated["score"] < 1


def test_abstaining_on_incomplete_evidence_is_right_and_abstaining_elsewhere_is_not(bound):
    binding, cases = bound
    abstain = next(c for c in cases if c["truth"]["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN")
    flagged = next(c for c in cases if c["truth"]["state"] == "FINDINGS")
    right = response_from_truth(abstain["capsule"], abstain["truth"])
    assert right["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN" and not right["findings"]
    assert score_response(binding, abstain["capsule"], abstain["truth"], right, OK)["valid"]
    wrong = deepcopy(response_from_truth(flagged["capsule"], flagged["truth"]))
    wrong.update(state="INSUFFICIENT_EVIDENCE_ABSTAIN", findings=[])
    assert score_response(binding, flagged["capsule"], flagged["truth"], wrong,
                          OK)["score"] == pytest.approx(1e-6)


@pytest.mark.parametrize("failed", ["schema", "policy", "signature", "nonce", "evidence",
                                    "deadline"])
def test_every_integrity_failure_scores_zero(bound, failed):
    binding, cases = bound
    case = cases[0]
    fields = {k: k != failed for k in ("schema", "policy", "signature", "nonce", "evidence",
                                       "deadline")}
    response = response_from_truth(case["capsule"], case["truth"])
    result = score_response(binding, case["capsule"], case["truth"], response,
                            Integrity(**fields))
    assert result["score"] == 0 and not result["valid"] and failed in result["failures"]


def test_a_bundle_over_the_published_truth_is_a_valid_row_with_no_headroom(bound):
    """The public baseline and a truth-reproducing method both score 1: NULL_NO_HEADROOM."""
    binding, cases = bound
    baseline = BASELINES[binding.class_id]
    methods = {"baseline_miner": baseline,
               "truth_miner": lambda c: response_from_truth(c, STORE.truth_for(c), "truth_miner")}
    staged = replace(binding, candidates=dict(methods), roles=dict.fromkeys(methods, "candidate"))
    unit = bundle.cost_record({}, dict.fromkeys(bundle.COST_UNITS, "NOT_OBSERVED"))
    observations = {
        name: {c["qid"]: {"response": parse_canonical(canonical_bytes(fn(c["capsule"]))),
                          "integrity": OK, "cost": unit} for c in cases}
        for name, fn in methods.items()}
    result = bundle.evaluate(staged, cases, observations, mode="FIXTURE", run_id="golden-test",
                             profile_commitment=binding.profile.commitment, window=WHEN,
                             source_digest="sha256:" + "0" * 64, per_case=True)
    assert result["row"]["state"] == "VALID_PREFERENCE_ROW"
    for name in methods:
        assert result["scores"][name]["estimate"] == "1"
        assert result["comparison"][name]["result"] == "NULL_NO_HEADROOM"
