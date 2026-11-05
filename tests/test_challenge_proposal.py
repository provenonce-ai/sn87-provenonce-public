"""Challenge proposals: admissibility rules, round trip and CLI exit codes."""

import copy
import json
from pathlib import Path

import pytest

from sn87_provenonce import challenge_proposal as cp
from sn87_provenonce.cli import main

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples" / "challenge-proposals"
EXAMPLE = EXAMPLES / "ic-approval-applicability.example.json"
TEMPLATE = EXAMPLES / "TEMPLATE.json"
PINNED = "sha256:1c0562f791afa00caeebdfa5a9afcc3473957e6f0f2d7f07d4f8bae310c75bfe"
A_VALID = {
    "proposal_id": "T-1", "schema_version": "sn87/challenge-proposal/0.1",
    "proposal_version": "1", "challenge_family": "FAM",
    "intended_consumer": "a reviewer",
    "evidence_rights": {
        "visibility": [{"party": "miner", "may_see": ["capsule"]}],
        "raw_evidence_leaves_source": False, "export_default": "DERIVED_ONLY"},
    "truth_source": {"oracle_class": "A", "description": "planted defect list"},
    "submission_format": "AssuranceResponse",
    "scoring": {"reference": "IC-FIRST-LIGHT-MIN-2", "commitment": PINNED},
    "baselines": [{"baseline_id": "b", "description": "naive", "sees_public_contract_only": True,
                   "status": "IMPLEMENTED"}],
    "resource_budget": {"compute_seconds": 1, "wall_clock_seconds": 2, "cost_credits": 0},
    "headroom": {"statement": "baseline misses planted defects"},
    "known_limitations": ["synthetic"],
}
A_VALID["challenge_family"] = "IC-APPROVAL-APPLICABILITY"
RELIABILITY = {"method": "two-rater blind review", "sample_size": 120,
               "agreement": {"name": "COHEN_KAPPA", "value": 0.81}}


@pytest.fixture(autouse=True)
def no_recorded_null(request, monkeypatch):
    """Only the tests that name it see the repository's recorded nulls; the rest isolate rules."""
    if "keep_nulls" not in request.fixturenames:
        monkeypatch.setattr(cp, "KNOWN_NULLS", {})


def make(**changes):
    data = copy.deepcopy(A_VALID)
    for key, value in changes.items():
        data[key] = value
    return data


def codes(data):
    return codes_text(json.dumps(data))


def codes_text(text):
    result = cp.check_proposal_text(text)
    return result.verdict, {r.code for r in result.reasons}


def test_clean_type_a_proposal_is_admissible():
    assert codes(make()) == (cp.Verdict.ADMISSIBLE, set())


@pytest.fixture
def keep_nulls():
    return None


def test_worked_example_needs_decision_for_recorded_null(keep_nulls):
    result = cp.check_proposal_file(EXAMPLE)
    assert result.verdict is cp.Verdict.NEEDS_DECISION
    assert {r.code for r in result.reasons} == {"PRIOR_NULL_NO_HEADROOM_RECORDED"}


def test_recorded_null_applies_even_if_proposal_omits_it(keep_nulls):
    assert codes(make()) == (cp.Verdict.NEEDS_DECISION, {"PRIOR_NULL_NO_HEADROOM_RECORDED"})


def test_template_needs_decision_not_admissible():
    result = cp.check_proposal_file(TEMPLATE)
    assert result.verdict is cp.Verdict.NEEDS_DECISION
    assert "SCORING_UNPINNED" in {r.code for r in result.reasons}


def test_type_d_without_reliability_is_inadmissible():
    verdict, found = codes(make(truth_source={"oracle_class": "D", "description": "experts"}))
    assert verdict is cp.Verdict.INADMISSIBLE and "TYPE_D_RELIABILITY_MISSING" in found


def test_type_d_is_never_admissible_even_with_reliability():
    data = make(truth_source={"oracle_class": "D", "description": "experts",
                              "reliability": RELIABILITY})
    assert codes(data) == (cp.Verdict.NEEDS_DECISION, {"TYPE_D_RELIABILITY_REVIEW"})


def test_type_d_degenerate_reliability_is_still_only_review():
    rel = {"method": "n/a", "sample_size": 1, "agreement": {"name": "COHEN_KAPPA", "value": 0.0}}
    data = make(truth_source={"oracle_class": "D", "description": "e", "reliability": rel})
    assert codes(data)[0] is cp.Verdict.NEEDS_DECISION


@pytest.mark.parametrize("bad", [
    {"sample_size": "120"}, {"sample_size": 1.5}, {"sample_size": 0},
    {"agreement": {"name": "vibes", "value": 0.8}},
    {"agreement": {"name": "COHEN_KAPPA", "value": "0.8"}},
    {"agreement": {"name": "COHEN_KAPPA", "value": 1.5}},
    {"agreement": {"name": "COHEN_KAPPA", "value": float("nan")}},
])
def test_type_d_reliability_fields_are_strict(bad):
    rel = {**RELIABILITY, **bad}
    data = make(truth_source={"oracle_class": "D", "description": "e", "reliability": rel})
    assert codes(data) == (cp.Verdict.INADMISSIBLE, {"SCHEMA_INVALID"})


def test_self_verifying_claim_on_type_d_is_inadmissible():
    data = make(truth_source={"oracle_class": "D", "description": "experts",
                              "reliability": RELIABILITY, "claims_self_verifying": True})
    verdict, found = codes(data)
    assert verdict is cp.Verdict.INADMISSIBLE and "SELF_VERIFYING_CLAIM_ON_TYPE_D" in found


@pytest.mark.parametrize("phrase", [
    "a self-verifying panel", "a self\u2011verifying panel", "a self\u200bverifying panel",
    "a self\u00adverifying panel", "a SELF\u2013VERIFYING panel",
    "a \uff53\uff45\uff4c\uff46-verifying panel",
    "the result verifies itself", "a self-checking result", "objective ground truth",
])
@pytest.mark.parametrize("field", ["description", "limitation", "consumer", "headroom"])
def test_self_verifying_text_variants_are_caught_in_every_field(phrase, field):
    data = make(truth_source={"oracle_class": "D", "description": "experts",
                              "reliability": RELIABILITY})
    if field == "description":
        data["truth_source"]["description"] = phrase
    elif field == "limitation":
        data["known_limitations"] = [phrase]
    elif field == "consumer":
        data["intended_consumer"] = phrase
    else:
        data["headroom"]["statement"] = phrase
    assert "SELF_VERIFYING_CLAIM_ON_TYPE_D" in codes(data)[1]


def test_self_verifying_wording_on_type_d_is_inadmissible():
    data = make(truth_source={"oracle_class": "D", "description": "a self-verifying panel",
                              "reliability": RELIABILITY})
    assert "SELF_VERIFYING_CLAIM_ON_TYPE_D" in codes(data)[1]


def test_self_verifying_claim_on_type_c_is_inadmissible():
    data = make(truth_source={"oracle_class": "C", "description": "ref",
                              "claims_self_verifying": True,
                              "independent_reference_executions": 2,
                              "reference_executor_private": True})
    verdict, found = codes(data)
    assert verdict is cp.Verdict.INADMISSIBLE
    assert "SELF_VERIFYING_CLAIM_ON_NON_SELF_VERIFYING_CLASS" in found


@pytest.mark.parametrize("oracle_class", ["A", "B"])
def test_self_verifying_claim_on_a_or_b_is_allowed(oracle_class):
    data = make(truth_source={"oracle_class": oracle_class, "description": "x",
                              "claims_self_verifying": True})
    assert codes(data) == (cp.Verdict.ADMISSIBLE, set())


def test_type_c_needs_two_private_executions():
    verdict, found = codes(make(truth_source={"oracle_class": "C", "description": "ref",
                                              "independent_reference_executions": 1}))
    assert verdict is cp.Verdict.NEEDS_DECISION
    assert {"TYPE_C_NEEDS_INDEPENDENT_EXECUTIONS", "TYPE_C_EXECUTOR_NOT_DECLARED_PRIVATE"} <= found


def test_missing_baseline_is_inadmissible():
    verdict, found = codes(make(baselines=[]))
    assert verdict is cp.Verdict.INADMISSIBLE and "BASELINE_MISSING" in found


def test_proposed_only_baseline_needs_decision():
    baselines = copy.deepcopy(A_VALID["baselines"])
    baselines[0]["status"] = "PROPOSED"
    assert codes(make(baselines=baselines)) == (
        cp.Verdict.NEEDS_DECISION, {"BASELINE_NOT_IMPLEMENTED"})


def test_unpinned_scoring_needs_decision():
    data = make(scoring={"reference": "PROPOSED_UNPINNED", "description": "to be designed"})
    assert codes(data) == (cp.Verdict.NEEDS_DECISION, {"SCORING_UNPINNED"})


def test_whitespace_in_ids_is_rejected_not_stripped():
    assert codes(make(scoring={"reference": " PROPOSED_UNPINNED", "description": "d"}))[1] == {
        "SCHEMA_INVALID"}
    assert codes(make(scoring={"reference": "IC-FIRST-LIGHT-MIN-2 ", "commitment": PINNED}))[
        1] == {"SCHEMA_INVALID"}
    assert codes(make(challenge_family="IC-APPROVAL-APPLICABILITY\n"))[1] == {"SCHEMA_INVALID"}


def test_unpinned_scoring_without_description_is_schema_invalid():
    assert codes(make(scoring={"reference": "PROPOSED_UNPINNED"}))[1] == {"SCHEMA_INVALID"}


def test_unknown_profile_and_wrong_commitment_are_inadmissible():
    assert "SCORING_PROFILE_UNKNOWN" in codes(make(scoring={"reference": "NOPE"}))[1]
    wrong = make(scoring={"reference": "IC-FIRST-LIGHT-MIN-2", "commitment": "sha256:" + "0" * 64})
    verdict, found = codes(wrong)
    assert verdict is cp.Verdict.INADMISSIBLE and "SCORING_COMMITMENT_MISMATCH" in found


def test_profile_family_mismatch_needs_decision():
    data = make(challenge_family="OTHER-FAMILY")
    assert codes(data) == (cp.Verdict.NEEDS_DECISION, {"SCORING_PROFILE_FAMILY_MISMATCH"})


def test_raw_export_by_default_is_inadmissible_unless_justified():
    rights = {"visibility": [{"party": "x", "may_see": ["raw"]}],
              "raw_evidence_leaves_source": True, "export_default": "RAW_RECORDS"}
    verdict, found = codes(make(evidence_rights=rights))
    assert verdict is cp.Verdict.INADMISSIBLE and "RAW_EXPORT_BY_DEFAULT" in found
    rights["export_justification"] = "regulator requires the originals"
    assert codes(make(evidence_rights=rights)) == (
        cp.Verdict.NEEDS_DECISION, {"RAW_EXPORT_JUSTIFIED"})


def test_inconsistent_evidence_rights_are_inadmissible():
    rights = {"visibility": [{"party": "x", "may_see": ["raw"]}],
              "raw_evidence_leaves_source": True, "export_default": "NONE"}
    assert "EVIDENCE_RIGHTS_INCONSISTENT" in codes(make(evidence_rights=rights))[1]


def test_declared_prior_null_needs_decision():
    data = make(headroom={"statement": "s", "prior_nulls": [
        {"reference": "earlier-run", "result": "NULL_NO_HEADROOM", "note": "tie"}]})
    assert codes(data) == (cp.Verdict.NEEDS_DECISION, {"PRIOR_NULL_NO_HEADROOM"})


def test_raw_mentioned_in_rights_text_needs_decision():
    rights = {"visibility": [{"party": "auditor", "may_see": ["Raw ledger rows"]}],
              "raw_evidence_leaves_source": False, "export_default": "DERIVED_ONLY"}
    assert codes(make(evidence_rights=rights)) == (
        cp.Verdict.NEEDS_DECISION, {"EVIDENCE_TEXT_MENTIONS_RAW"})
    rights = {"visibility": [{"party": "auditor", "may_see": ["summaries"]}],
              "raw_evidence_leaves_source": False, "export_default": "DERIVED_ONLY",
              "export_justification": "the raw rows stay put"}
    assert "EVIDENCE_TEXT_MENTIONS_RAW" in codes(make(evidence_rights=rights))[1]


@pytest.mark.parametrize("path,value", [
    (("resource_budget", "compute_seconds"), float("inf")),
    (("resource_budget", "cost_credits"), float("nan")),
    (("resource_budget", "wall_clock_seconds"), "2"),
    (("truth_source", "claims_self_verifying"), "false"),
])
def test_budgets_are_finite_and_strict(path, value):
    data = make()
    data[path[0]][path[1]] = value
    assert codes(data) == (cp.Verdict.INADMISSIBLE, {"SCHEMA_INVALID"})


def test_schema_version_is_required_and_exact():
    data = make()
    del data["schema_version"]
    assert codes(data)[1] == {"SCHEMA_INVALID"}
    assert codes(make(schema_version="sn87/challenge-proposal/9"))[1] == {"SCHEMA_INVALID"}


def test_duplicate_baseline_ids_are_rejected():
    twin = copy.deepcopy(A_VALID["baselines"][0])
    assert codes(make(baselines=[A_VALID["baselines"][0], twin])) == (
        cp.Verdict.INADMISSIBLE, {"SCHEMA_INVALID"})


def test_deeply_nested_json_is_a_result_not_a_crash():
    deep = "[" * 100000 + "]" * 100000
    assert codes_text(deep) == (cp.Verdict.INADMISSIBLE, {"SCHEMA_INVALID"})
    nested = '{"proposal_id": "X", "a": ' + deep + "}"
    assert codes_text(nested) == (cp.Verdict.INADMISSIBLE, {"SCHEMA_INVALID"})
    assert codes_text("1" * 10000) == (cp.Verdict.INADMISSIBLE, {"SCHEMA_INVALID"})


def test_schema_violations_are_inadmissible_not_exceptions():
    assert codes(make(extra_field=1))[0] is cp.Verdict.INADMISSIBLE
    assert codes(make(status="ACTIVE"))[1] == {"SCHEMA_INVALID"}
    assert codes(make(known_limitations=[]))[1] == {"SCHEMA_INVALID"}
    assert cp.check_proposal_text("{not json").reasons[0].code == "SCHEMA_INVALID"


def test_json_round_trip():
    proposal = cp.ChallengeProposal.model_validate_json(EXAMPLE.read_text())
    again = cp.ChallengeProposal.model_validate_json(proposal.model_dump_json())
    assert again == proposal
    result = cp.check_proposal_file(EXAMPLE)
    assert cp.AdmissibilityResult.model_validate_json(result.model_dump_json()) == result


def test_result_activates_nothing():
    assert cp.check_proposal_file(EXAMPLE).activates_nothing is True


def test_cli_exit_codes(tmp_path, capsys, keep_nulls, monkeypatch):
    assert main(["challenge", "check", str(EXAMPLE)]) == 3
    assert "NEEDS_DECISION" in capsys.readouterr().out
    good = tmp_path / "good.json"
    good.write_text(json.dumps(make()))
    assert main(["challenge", "check", str(good)]) == 3  # IC family: null recorded
    monkeypatch.setattr(cp, "KNOWN_NULLS", {})
    assert main(["challenge", "check", str(good)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(make(baselines=[])))
    assert main(["challenge", "check", str(bad)]) == 1
    assert "BASELINE_MISSING" in capsys.readouterr().out
    assert main(["challenge", "check", str(tmp_path / "absent.json")]) == 4
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00{")
    assert main(["challenge", "check", str(binary)]) == 4
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 100000 + "]" * 100000)
    assert main(["challenge", "check", str(deep)]) == 1
    capsys.readouterr()
    assert main(["challenge", "check", "--json", str(good)]) == 0
    assert json.loads(capsys.readouterr().out.split("\n", 0)[0])["verdict"] == "ADMISSIBLE"
