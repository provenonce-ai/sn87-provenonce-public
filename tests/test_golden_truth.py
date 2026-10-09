"""The published golden truth: well formed, sealed, bound to the public generators' capsules.

Runs in the public tree. Nothing here needs a reference executor: each case is checked by
rebuilding its capsule with the public generator and comparing the recomputed evidence
commitment, and the Type C oracle report is checked against the commitment pinned in public code.
"""

from __future__ import annotations

import copy
import json

import pytest
from golden_support import STORE, golden_truth

from sn87_provenonce.canonical import evidence_commitment
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.classes import TYPE_C_RELEASE as TC
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.pilot.contracts import capsule_from_fixture
from sn87_provenonce.protocol.v0alpha1 import canonical_sha256
from sn87_provenonce.simulation.type_c import FIXTURES, REPORT_COMMITMENT_DOMAIN
from sn87_provenonce.simulation.type_c_candidate_artifact import REFERENCE_ORACLE_REPORT_COMMITMENT

GOLDEN = golden_truth.GOLDEN_DIR


def document(name):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def plan(binding):
    spec = binding.profile.document
    rows = [(f, "scored") for f, n in spec["assignment"].items() for _ in range(n)]
    rows += [(f, "diagnostic") for f, n in spec["diagnostics"].items() for _ in range(n)]
    return [(i, f, t) for i, (f, t) in enumerate(rows)]


def rebuilt(binding, case):
    """The capsule a case names, rebuilt with the public generator only."""
    kind, _, rest = case["case_id"].partition("/")
    if kind == "fixture-run":
        return binding.generate(case["family"], case["index"])
    if binding is IC:
        return build_case(rest)
    return capsule_from_fixture(next(f for f in FIXTURES if f.fixture_id == rest))


@pytest.mark.parametrize("name,binding", [("ic_fixture_set.json", IC),
                                          ("type_c_fixture_set.json", TC)])
def test_every_case_is_bound_to_its_publicly_rebuilt_capsule(name, binding):
    doc = document(name)
    assert doc["class_id"] == binding.class_id
    assert doc["profile_id"] == binding.profile.profile_id
    for case in doc["cases"]:
        capsule = rebuilt(binding, case)
        assert evidence_commitment(capsule) == case["capsule_commitment"], case["case_id"]
        assert capsule["qid"] == case["qid"]
        assert STORE.truth_for(capsule) == case["truth"]


@pytest.mark.parametrize("name,binding", [("ic_fixture_set.json", IC),
                                          ("type_c_fixture_set.json", TC)])
def test_the_full_fixture_run_of_each_class_is_covered(name, binding):
    doc = document(name)
    run = {c["index"]: c for c in doc["cases"] if c["case_id"].startswith("fixture-run/")}
    assert sorted(run) == [i for i, _, _ in plan(binding)]
    assert {run[i]["family"] for i, _, _ in plan(binding)} == {f for _, f, _ in plan(binding)}


def test_every_public_type_c_fixture_has_truth():
    for fixture in FIXTURES:
        assert STORE.truth_for(capsule_from_fixture(fixture))["state"]
    for family in ("stale_authority", "fresh_review", "incomplete"):
        assert STORE.truth_for(build_case(family))["state"]


def test_no_truth_exists_for_other_seeds_or_other_capsules():
    """Only the attested seed is published: later windows draw fresh instances."""
    for seed in (1, 2, 17):
        capsule = IC.generate("stale_authority", seed * 1000)
        with pytest.raises(golden_truth.GoldenTruthMissing):
            STORE.truth_for(capsule)
    tampered = build_case("stale_authority")
    tampered["events"][0]["source"] = "someone-else"
    tampered["evidence_commitment"] = evidence_commitment(tampered)
    with pytest.raises(golden_truth.GoldenTruthMissing):
        STORE.truth_for(tampered)


def test_the_commitment_is_recomputed_not_read_from_the_capsule():
    """A capsule with altered content but the original commitment field gets no truth."""
    forged = build_case("stale_authority")
    claimed = forged["evidence_commitment"]
    forged["policy"] = dict(forged["policy"], nonce_note="altered")
    forged["evidence_commitment"] = claimed
    with pytest.raises(golden_truth.GoldenTruthMissing):
        STORE.truth_for(forged)


def test_an_edited_file_is_detected_unless_it_is_resealed():
    doc = document("ic_fixture_set.json")
    edited = copy.deepcopy(doc)
    edited["cases"][0]["truth"] = {"state": "NO_MATERIAL_DEVIATION", "defects": []}
    with pytest.raises(golden_truth.GoldenTruthInvalid, match="set_digest"):
        golden_truth.validate_document("edited", edited)
    edited["set_digest"] = golden_truth.seal(edited)  # a re-sealed edit is well formed...
    golden_truth.validate_document("edited", edited)
    # ... which is why the proof of the truth is the digest it reproduces, not the seal
    assert edited["set_digest"] != doc["set_digest"]


@pytest.mark.parametrize("truth", [
    {"state": "FINDINGS", "defects": []},
    {"state": "NO_MATERIAL_DEVIATION",
     "defects": [{"code": "X", "severity": "LOW", "required_refs": []}]},
    {"state": "MAYBE", "defects": []},
    {"state": "FINDINGS", "defects": [{"code": "X", "severity": "HUGE", "required_refs": []}]},
    {"state": "NO_MATERIAL_DEVIATION", "defects": [], "rule_reliability": "0.95"},
])
def test_malformed_truth_is_rejected(truth):
    doc = copy.deepcopy(document("ic_fixture_set.json"))
    doc["cases"][0]["truth"] = truth
    doc["set_digest"] = golden_truth.seal(doc)
    with pytest.raises(golden_truth.GoldenTruthInvalid):
        golden_truth.validate_document("bad", doc)


def test_two_files_may_not_disagree_about_one_capsule():
    first = copy.deepcopy(document("ic_fixture_set.json"))
    second = copy.deepcopy(first)
    second["cases"][0]["truth"] = {"state": "INSUFFICIENT_EVIDENCE_ABSTAIN", "defects": []}
    second["set_digest"] = golden_truth.seal(second)
    with pytest.raises(golden_truth.GoldenTruthInvalid, match="different truth"):
        golden_truth.GoldenTruth({"a.json": first, "b.json": second})


def test_the_type_c_oracle_report_matches_the_commitment_pinned_in_public_code():
    doc = document("oracle/type_c_reference_oracle.json")
    assert doc["set_digest"] == golden_truth.seal(doc)
    report = doc["report"]
    body = {k: v for k, v in report.items() if k != "report_commitment"}
    recomputed = canonical_sha256(body, domain=REPORT_COMMITMENT_DOMAIN)
    assert recomputed == report["report_commitment"] == REFERENCE_ORACLE_REPORT_COMMITMENT
    assert report["all_references_agree"] is True


def test_the_oracle_report_and_the_scorer_truth_agree_on_every_fixture():
    """Two independently published records of the same eight outcomes."""
    report = document("oracle/type_c_reference_oracle.json")["report"]
    assert [f["fixture_id"] for f in report["fixtures"]] == [f.fixture_id for f in FIXTURES]
    for entry in report["fixtures"]:
        fixture = next(f for f in FIXTURES if f.fixture_id == entry["fixture_id"])
        truth = STORE.truth_for(capsule_from_fixture(fixture))
        outcome = entry["agreed_outcome"]
        assert outcome["response_state"] == truth["state"]
        assert outcome["defect_codes"] == sorted(d["code"] for d in truth["defects"])


def test_the_published_files_hold_only_the_two_public_case_kinds():
    for name in ("ic_fixture_set.json", "type_c_fixture_set.json"):
        for case in document(name)["cases"]:
            assert case["case_id"].startswith(("fixture-run/", "default/")), case["case_id"]
            assert set(case) <= {"case_id", "capsule_commitment", "qid", "family", "track",
                                 "index", "fixture_id", "truth"}
