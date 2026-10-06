"""The replaceable candidate: bound as role "candidate", measured against truth and baseline."""

import pytest

from sn87_provenonce import miners
from sn87_provenonce.bundle import fixture_run
from sn87_provenonce.canonical import evidence_commitment
from sn87_provenonce.classes import BINDINGS, with_candidates
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.institutional_v02.fixtures import build_case

CLASS_ID = "IC-APPROVAL-APPLICABILITY"
METHOD = "approval_witness"


def test_registry_and_binding():
    assert set(miners.for_class(CLASS_ID)) == {METHOD}
    assert miners.for_class("TYPE-C-RELEASE") == {}
    with pytest.raises(ValueError):
        miners.register(CLASS_ID, METHOD, lambda c: c)
    bound = with_candidates(IC, miners.for_class(CLASS_ID))
    assert [bound.role_of(m) for m in bound.candidates] == ["reference", "reference", "candidate"]
    assert set(IC.candidates) == {"state_machine", "relational"} and not IC.roles  # unchanged
    with pytest.raises(ValueError):
        with_candidates(IC, {"relational": lambda c: c})


def test_measured_candidate_equals_truth_and_baseline_on_first_light_fixtures():
    """Measured, not designed: on the public First Light generator the candidate matches truth
    on every case, so against the matched baseline the result is a null (no headroom). The
    witness set is smaller than the baseline's, and still earns full evidence credit."""
    bundle = fixture_run(with_candidates(IC, miners.for_class(CLASS_ID)))
    roles = {m["method_id"]: m["role"] for m in bundle["methods"]}
    assert roles[METHOD] == "candidate" and roles["public_contract_baseline"] == "baseline"
    assert bundle["methods"][2]["uid"] is None
    score = bundle["scores"][METHOD]
    assert (score["admitted"], score["evaluable"], score["estimate"], score["eligible"]) == (
        12, 12, "1", True)
    assert bundle["comparison"][METHOD] == {"estimate_delta": "0", "result": "NULL_NO_HEADROOM"}
    assert set(bundle["row"]["weights"]) == {"state_machine", "relational", METHOD}
    assert bundle["cost"][METHOD]["oracle_time"]["missing"].startswith("NOT_APPLICABLE")
    assert bundle["diagnostics"][METHOD]["correct_abstentions"] == 4


def test_witness_is_smaller_than_the_baselines_and_ambiguity_is_handled_its_own_way():
    candidate = miners.for_class(CLASS_ID)[METHOD]
    from sn87_provenonce.baselines import ic_approval_applicability as baseline

    capsule = build_case("stale_authority")
    mine = candidate(capsule)["findings"][0]["evidence_refs"]
    theirs = baseline(capsule)["findings"][0]["evidence_refs"]
    assert set(mine) < set(theirs) and len(mine) < len(capsule["events"])
    # A same-time tie of governing versions with DIFFERENT conditions is ambiguous: abstain.
    # With the SAME condition the tie is moot: the candidate decides, the baseline abstains.
    tied = build_case("stale_authority")
    versions = [e for e in tied["events"] if e["kind"] == "POLICY_VERSION"]
    versions[1]["at"], versions[1]["effective_at"] = versions[0]["at"], versions[0]["effective_at"]
    tied["evidence_commitment"] = evidence_commitment(tied)
    assert candidate(tied)["state"] == baseline(tied)["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN"
    versions[1]["condition_commitment"] = versions[0]["condition_commitment"]
    tied["evidence_commitment"] = evidence_commitment(tied)
    assert candidate(tied)["state"] == "NO_MATERIAL_DEVIATION"
    assert baseline(tied)["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN"
    # Measured divergence: the reference truth abstains on any tie, so this decisiveness is
    # not rewarded (detection is 0 whenever truth abstains). Kept, not tuned away.
    assert IC.reference(tied)["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN"


def test_existing_fixture_bundles_do_not_gain_the_candidate():
    for binding in BINDINGS.values():
        assert set(fixture_run(binding)["scores"]) == {
            "state_machine", "relational", "public_contract_baseline"}
