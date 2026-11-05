"""A reply the contract rejects scores zero and takes no part in redundancy grouping or flags.

Under a profile with the redundancy rule (ADR-0022, MIN-4) a malformed non-null reply used to
reach ``answer_key`` and raise KeyError or TypeError, which aborted the whole evaluation. Public
tree: uses the published truth and the committed demonstration window.
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from golden_support import STORE, response_from_truth

from sn87_provenonce import bundle, flags, profile, redundancy
from sn87_provenonce.baselines import BASELINES
from sn87_provenonce.canonical import canonical_bytes, parse_canonical
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.scoring import Integrity

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contest_dry_run as dr  # noqa: E402
import contest_results as cr  # noqa: E402
import contest_window as cw  # noqa: E402

MIN4 = "IC-FIRST-LIGHT-MIN-4"
OK = Integrity(True, True, True, True, True, True)
WHEN = {"opened_at": "2026-10-04T00:00:00Z", "closed_at": "2026-10-04T00:00:00Z"}
DEMO = ROOT / "examples" / "contest-window-demo"

MALFORMED = {
    "empty-mapping": {},
    "list": [],
    "state-only": {"state": "X"},
    "findings-not-a-list": {"state": "NO_MATERIAL_DEVIATION", "findings": "none"},
    "non-dict-finding": {"state": "FINDINGS", "findings": ["not-a-finding"]},
    "finding-without-code": {"state": "FINDINGS", "findings": [{"severity": "HIGH"}]},
    "state-not-a-string": {"state": ["FINDINGS"], "findings": []},
}


@pytest.mark.parametrize("reply", MALFORMED.values(), ids=MALFORMED.keys())
def test_answer_key_gives_a_malformed_reply_no_key(reply):
    assert redundancy.answer_key(reply) is None


def test_two_identical_malformed_replies_never_group_or_count_as_the_same_answer():
    good = {"state": "NO_MATERIAL_DEVIATION", "findings": []}
    answers = {"a": {"q": {}}, "b": {"q": {}}, "c": {"q": good}, "d": {"q": good}}
    assert redundancy.redundancy_groups(answers) == [["c", "d"]]
    for reply in MALFORMED.values():
        assert redundancy.redundancy_groups({"a": {"q": reply}, "b": {"q": reply}}) == []

    def seen(response):
        return {"q": {"response": response, "dispatched_at": 0.0, "responded_at": 1.0}}

    params = {"dispatch_window_seconds": 1, "latency_difference_seconds": 1,
              "pair_share": "0.5", "min_cases": 1}
    odd = {"state": "FINDINGS", "findings": [{"code": "C"}]}
    out = flags.observation_flags(
        {"a": seen({}), "b": seen({}), "c": seen(odd), "d": seen(good)}, params)
    assert out["IDENTICAL_ANSWERS_ON_SEPARATING_TASKS"] == []


@pytest.fixture(scope="module")
def ic_cases():
    # The published truth covers the default profile's instances; score them under MIN-4.
    document = IC.profile.document
    binding = replace(IC, profile=profile.load(MIN4))
    plan = [(f, "scored") for f, n in document["assignment"].items() for _ in range(n)]
    cases = []
    for index, (family, track) in enumerate(plan):
        capsule = binding.generate(family, index)
        cases.append({"qid": capsule["qid"], "track": track, "family": family,
                      "capsule": capsule, "truth": STORE.truth_for(capsule)})
    return binding, cases


@pytest.mark.parametrize("reply", MALFORMED.values(), ids=MALFORMED.keys())
def test_bundle_evaluate_scores_a_malformed_reply_zero_outside_every_group(
    ic_cases, reply, monkeypatch
):
    binding, cases = ic_cases
    seen_answers = []
    real = bundle.preference_row

    def spy(*args, **kwargs):
        seen_answers.append(kwargs["answers"])
        return real(*args, **kwargs)

    monkeypatch.setattr(bundle, "preference_row", spy)
    unit = bundle.cost_record({}, dict.fromkeys(bundle.COST_UNITS, "NOT_OBSERVED"))
    good = {
        "truth_miner": lambda c, t: response_from_truth(c, t, "truth_miner"),
        "twin_miner": lambda c, t: response_from_truth(c, t, "twin_miner"),
    }
    methods = ["truth_miner", "twin_miner", "bad_miner", "bad_twin"]
    staged = replace(binding, candidates=dict.fromkeys(methods, BASELINES[binding.class_id]),
                     roles=dict.fromkeys(methods, "candidate"))
    observations = {}
    for name in methods:
        observations[name] = {}
        for c in cases:
            response = (copy.deepcopy(reply) if name.startswith("bad")
                        else parse_canonical(canonical_bytes(good[name](c["capsule"], c["truth"]))))
            observations[name][c["qid"]] = {"response": response, "integrity": OK, "cost": unit}
    result = bundle.evaluate(staged, cases, observations, mode="FIXTURE", run_id="malformed",
                             profile_commitment=binding.profile.commitment, window=WHEN,
                             source_digest="sha256:" + "0" * 64, per_case=True)
    for name in ("bad_miner", "bad_twin"):
        assert result["scores"][name]["evaluable"] == 0
        assert result["scores"][name]["estimate"] == "NA"
    assert result["scores"]["truth_miner"]["evaluable"] > 0
    # The answers the preference row groups on: the correct twins group, the malformed pair
    # has no answer to group on.
    answers = seen_answers[0]
    assert all(v is None for v in answers["bad_miner"].values())
    assert redundancy.redundancy_groups(answers) == [["truth_miner", "twin_miner"]]
    for record in result["cases"]:
        for name in ("bad_miner", "bad_twin"):
            assert record["methods"][name]["valid"] is False
            assert float(record["methods"][name]["score"]) == 0


@pytest.fixture(scope="module")
def window():
    commitments = json.loads((DEMO / "commitments.json").read_text())
    reveal = json.loads((DEMO / "window_demo-0001.reveal.json").read_text())
    entries = cw.check_reveal(commitments, reveal)
    truth = json.loads((DEMO / "window_demo-0001.truth.json").read_text())
    return (cw.capsules_document(reveal["spec"], entries), truth,
            dr.responses_document([e["capsule"] for e in entries], timing=False))


@pytest.mark.parametrize("reply", MALFORMED.values(), ids=MALFORMED.keys())
def test_score_window_scores_a_malformed_reply_zero_outside_every_group(window, reply):
    capsules, truth, responses = copy.deepcopy(window)
    template = responses["methods"][0]
    for name in ("bad_one", "bad_two"):
        bad = copy.deepcopy(template) | {"method_id": name}
        for entry in bad["responses"].values():
            entry["response"] = copy.deepcopy(reply)
        responses["methods"].append(bad)
    twin = copy.deepcopy(template) | {"method_id": "twin"}
    responses["methods"].append(twin)
    document = cr.score_window(capsules, truth, responses, MIN4)
    by_id = {m["method_id"]: m for m in document["methods"]}
    for name in ("bad_one", "bad_two"):
        assert by_id[name]["score"]["evaluable"] == 0
        assert str(by_id[name]["score"]["estimate"]) in ("0", "NA")
    grouped = {m for g in document["redundancy_groups"] for m in g}
    assert not grouped & {"bad_one", "bad_two"}
    assert [template["method_id"], "twin"] in [sorted(g, key=lambda m: m != template["method_id"])
                                              for g in document["redundancy_groups"]]
