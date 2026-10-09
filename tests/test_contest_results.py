"""Per-window results: scoring, agreement with truth, failures, guards and determinism.

Public tree: uses the committed demonstration window (public seed, committed truth) and the public
miner and baseline code. No reference executor is needed.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contest_dry_run as dr  # noqa: E402
import contest_results as cr  # noqa: E402
import contest_window as cw  # noqa: E402

from sn87_provenonce.canonical import canonical_bytes  # noqa: E402
from sn87_provenonce.scoring import wire  # noqa: E402

DEMO = ROOT / "examples" / "contest-window-demo"
CLOSES = dr.DEMO_CLOSES
ABSTAIN, CLEAR, FINDINGS = ("INSUFFICIENT_EVIDENCE_ABSTAIN", "NO_MATERIAL_DEVIATION", "FINDINGS")


@pytest.fixture(scope="module")
def window():
    """(capsules document, truth document, responses document) of the committed demo window."""
    commitments = json.loads((DEMO / "commitments.json").read_text())
    reveal = json.loads((DEMO / "window_demo-0001.reveal.json").read_text())
    entries = cw.check_reveal(commitments, reveal)
    spec = reveal["spec"]
    truth = json.loads((DEMO / "window_demo-0001.truth.json").read_text())
    return (cw.capsules_document(spec, entries), truth,
            dr.responses_document([e["capsule"] for e in entries], timing=False))


def recommit(truth):
    truth["truth_commitment"] = cw.truth_commitment(
        truth["cases"], window_id=truth["window_id"], seed_commitment=truth["seed_commitment"],
        cases_commitment=truth["cases_commitment"], salt=truth["salt"])


def doc(window, profile="IC-FIRST-LIGHT-MIN-3", **kw):
    capsules, truth, responses = copy.deepcopy(window)
    mutate = kw.pop("mutate", None)
    if mutate:
        mutate(capsules, truth, responses)
    return wire(cr.score_window(capsules, truth, responses, profile, **kw))


def method(document, method_id):
    return next(m for m in document["methods"] if m["method_id"] == method_id)


def test_committed_pages_are_reproduced_byte_for_byte(window):
    capsules, truth, responses = window
    full = wire(cr.score_window(capsules, truth, responses, "IC-FIRST-LIGHT-MIN-3"))
    for name, document in (("results-full", full), ("results", cr.scores_only(full))):
        committed = (DEMO / name / "window_demo-0001.json").read_text()
        assert cw.dumps(document) == committed
        assert cr.render_markdown(document, revealed=None if name == "results" else {
            "seed_commitment": "x"}).splitlines()[0].startswith("# Contest window demo-0001")
    assert cr.render_markdown(cr.scores_only(full), revealed=None) == (
        DEMO / "results" / "window_demo-0001.md").read_text()


def test_scores_only_record_withholds_everything_derived_from_truth(window):
    capsules, truth, responses = window
    full = wire(cr.score_window(capsules, truth, responses, "IC-FIRST-LIGHT-MIN-3"))
    lean = cr.scores_only(full)
    text = json.dumps(lean)
    assert lean["disclosure"] == "SCORES_ONLY" and full["disclosure"] == "TRUTH_DERIVED"
    for key in ("agreement", "confusion", "by_family", "failures", "truth_state_counts",
                "reference_failure", "admitted_scored", "assigned_scored", "status",
                "dimensions"):
        assert key not in text, key
    assert set(lean["methods"][0]["score"]) == {"estimate", "eligible", "reason"}
    assert salt_of(truth) not in text and "cases" not in lean


def salt_of(truth):
    return truth["salt"]


def test_record_is_float_free_and_canonical(window):
    document = doc(window)
    assert canonical_bytes(document, max_bytes=2**24)
    assert document["claim"] == "SHADOW_RESULTS_NOT_WIRED_TO_WEIGHTS"
    assert "weights" not in document and "row" not in document


def test_agreement_beside_score_and_a_gap_the_score_can_hide(window):
    min1 = doc(window, "IC-FIRST-LIGHT-MIN-1")
    cand, base = method(min1, "approval_witness"), method(min1, "public_contract_baseline")
    # The same responses: under MIN-1 the estimates tie, agreement with truth does not.
    assert cand["score"]["estimate"] == base["score"]["estimate"]
    assert cand["agreement"]["state_all"]["fraction"] == "1"
    assert float(base["agreement"]["state_all"]["fraction"]) < 1
    assert cand["versus_baseline"]["result"] == "NULL_NO_HEADROOM"
    assert float(cand["versus_baseline"]["agreement_delta"]) > 0
    # Under the profile with the payoff rules the estimate separates them too.
    min3 = doc(window)
    assert method(min3, "approval_witness")["versus_baseline"]["result"] == "ABOVE_BASELINE"


def test_profile_is_selectable_and_agreement_does_not_depend_on_it(window):
    docs = {pid: doc(window, pid) for pid in ("IC-FIRST-LIGHT-MIN-1", "IC-FIRST-LIGHT-MIN-2",
                                              "IC-FIRST-LIGHT-MIN-3")}
    agreements = {pid: [m["agreement"] for m in d["methods"]] for pid, d in docs.items()}
    assert agreements["IC-FIRST-LIGHT-MIN-1"] == agreements["IC-FIRST-LIGHT-MIN-2"] == (
        agreements["IC-FIRST-LIGHT-MIN-3"])
    estimates = {pid: method(d, "public_contract_baseline")["score"]["estimate"]
                 for pid, d in docs.items()}
    assert len(set(estimates.values())) == 2  # MIN-2 and MIN-3 share rules, MIN-1 differs
    assert estimates["IC-FIRST-LIGHT-MIN-2"] == estimates["IC-FIRST-LIGHT-MIN-3"]
    assert docs["IC-FIRST-LIGHT-MIN-1"]["profile"]["state_payoff"] is False
    with pytest.raises(Exception, match="PROFILE_NOT_APPLIED"):
        doc(window, "IC-FIRST-LIGHT-MIN-9")


def test_confusion_table_and_counts_are_consistent(window):
    document = doc(window)
    admitted = document["window"]["admitted_scored"] + document["window"]["admitted_diagnostic"]
    for m in document["methods"]:
        assert sum(sum(row.values()) for row in m["confusion"].values()) == admitted
        diagonal = sum(m["confusion"][s][s] for s in m["confusion"])
        assert diagonal == m["agreement"]["state_all"]["agree"]
        assert {t: sum(row.values()) for t, row in m["confusion"].items()} == (
            document["truth_state_counts"])
    base = method(document, "public_contract_baseline")
    # The naive method over-claims exactly where the references abstain on wrong scope.
    assert base["confusion"][ABSTAIN][FINDINGS] + base["confusion"][ABSTAIN][CLEAR] > 0
    assert method(document, "approval_witness")["confusion"][ABSTAIN][ABSTAIN] == (
        document["truth_state_counts"][ABSTAIN])


def test_invalid_and_missing_responses_are_counted_and_scored_zero(window):
    def mutate(capsules, truth, responses):
        responses_of = next(m for m in responses["methods"]
                            if m["method_id"] == "approval_witness")["responses"]
        qids = [c["qid"] for c in truth["cases"] if c["track"] == "scored"]
        responses_of[qids[0]]["response"]["state"] = "NOT_A_STATE"   # schema failure
        del responses_of[qids[1]]                                     # missing
        responses_of[qids[2]]["integrity"] = {k: k != "deadline" for k in cr.INTEGRITY_KEYS}

    m = method(doc(window, mutate=mutate), "approval_witness")
    assert m["failures"]["invalid_or_missing"] == 3
    assert m["failures"]["by_reason"] == {"deadline": 1, "missing": 1, "schema": 1}
    assert m["score"]["evaluable"] == m["score"]["admitted"] - 3
    assert m["agreement"]["state_all"]["agree"] == m["agreement"]["state_all"]["n"] - 3
    assert sum(row["NO_VALID_RESPONSE"] for row in m["confusion"].values()) == 3
    assert m["score"]["eligible"] is False and m["score"]["reason"] == "RAW_FAILURE_CEILING"


def test_a_reference_failure_leaves_the_supply_and_the_window_stays_valid_under_min_3(window):
    def mutate(capsules, truth, responses):
        first = next(c for c in truth["cases"] if c["track"] == "scored")
        first["truth"], first["reference_failure"] = None, "RuntimeError"
        recommit(truth)

    one = doc(window, mutate=mutate)
    assert one["window"]["reference_failures"] == 1
    assert one["window"]["admitted_scored"] == one["window"]["assigned_scored"] - 1
    assert one["window"]["status"] == "VALID"
    assert all(m["score"]["eligible"] for m in one["methods"])
    # The same loss voids a window sized and scored under the first profile versions' floor.
    assert one["window"]["reference_failures_tolerated"] == 2


def test_three_reference_failures_void_a_min_3_window(window):
    def mutate(capsules, truth, responses):
        for c in [c for c in truth["cases"] if c["track"] == "scored"][:3]:
            c["truth"], c["reference_failure"] = None, "RuntimeError"
        recommit(truth)

    void = doc(window, mutate=mutate)
    assert void["window"]["status"] == "VOID_SAMPLE_FLOOR"
    assert all(m["score"]["reason"] == "SAMPLE_FLOOR" and not m["score"]["eligible"]
               for m in void["methods"])


def test_baseline_is_recomputed_from_public_code(window):
    assert doc(window)["evidence"]["baseline_recomputed_from_public_code"] is True

    def mutate(capsules, truth, responses):
        base = next(m for m in responses["methods"] if m["role"] == "baseline")["responses"]
        entry = next(iter(base.values()))["response"]
        entry["rationale"] = "A different baseline."

    altered = doc(window, mutate=mutate)
    assert altered["evidence"]["baseline_recomputed_from_public_code"] is False
    assert method(altered, "public_contract_baseline")["recomputed_from_public_code"] is False


def test_inputs_must_describe_the_same_cases(window, tmp_path):
    capsules, truth, responses = copy.deepcopy(window)
    paths = {}
    for name, value in (("capsules", capsules), ("truth", truth), ("responses", responses)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(value))
    cr.load_inputs(paths["capsules"], paths["truth"], paths["responses"])
    truth["cases"][0]["capsule_commitment"] = "sha256:" + "1" * 64
    paths["truth"].write_text(json.dumps(truth))
    with pytest.raises(ValueError, match="TRUTH_BOUND_TO_OTHER_CAPSULES"):
        cr.load_inputs(paths["capsules"], paths["truth"], paths["responses"])


def test_baseline_row_and_roles_are_checked(window):
    def not_baseline(capsules, truth, responses):
        next(m for m in responses["methods"] if m["role"] == "baseline")["method_id"] = "mine"

    with pytest.raises(ValueError, match="public-contract baseline"):
        doc(window, mutate=not_baseline)


# --- publication guards and files --------------------------------------------------------------

def args(window_dir, tmp_path, *extra, now=CLOSES):
    argv = ["--capsules", str(window_dir / "capsules.json"), "--truth",
            str(window_dir / "truth.json"), "--responses", str(window_dir / "responses.json"),
            "--out-dir", str(tmp_path / "pages"), "--profile", "IC-FIRST-LIGHT-MIN-3",
            "--now", now, *extra]
    return cr.parser().parse_args(argv)


@pytest.fixture
def window_dir(window, tmp_path):
    base = tmp_path / "in"
    base.mkdir()
    for name, value in zip(("capsules", "truth", "responses"), window, strict=True):
        (base / f"{name}.json").write_text(json.dumps(value))
    return base


def test_results_are_refused_before_the_window_closes(window_dir, tmp_path):
    with pytest.raises(cw.PhaseError, match="RESULTS_BEFORE_CLOSE"):
        cr.run(args(window_dir, tmp_path, now="2026-10-20T23:59:59Z"))
    assert not (tmp_path / "pages").exists()


def test_files_are_written_once_and_deterministically(window_dir, tmp_path):
    first = cr.run(args(window_dir, tmp_path))
    texts = [Path(p).read_text() for p in first]
    with pytest.raises(FileExistsError):
        cr.run(args(window_dir, tmp_path))
    second = cr.run(args(window_dir, tmp_path / "again"))
    assert [Path(p).read_text() for p in second] == texts
    assert texts[0] == (DEMO / "results" / "window_demo-0001.json").read_text()
    assert json.loads(texts[0])["disclosure"] == "SCORES_ONLY"


REVEALED = ["--commitments", str(DEMO / "commitments.json"),
            "--reveal", str(DEMO / "window_demo-0001.reveal.json")]


def test_truth_derived_aggregates_need_close_reveal_and_the_policy_flag(window_dir, tmp_path):
    with pytest.raises(cw.PhaseError, match="TRUTH_PUBLICATION_BEFORE_REVEAL"):
        cr.run(args(window_dir, tmp_path, "--publish-closed-window-truth"))
    # A reveal without the flag changes nothing: still scores only.
    paths = cr.run(args(window_dir, tmp_path / "a", *REVEALED))
    assert json.loads(Path(paths[0]).read_text())["disclosure"] == "SCORES_ONLY"
    paths = cr.run(args(window_dir, tmp_path / "b", "--publish-closed-window-truth", *REVEALED))
    full = json.loads(Path(paths[0]).read_text())
    assert full["disclosure"] == "TRUTH_DERIVED" and "cases" not in full
    assert Path(paths[0]).read_text() == (DEMO / "results-full" / "window_demo-0001.json"
                                          ).read_text()
    with pytest.raises(cw.PhaseError, match="RESULTS_BEFORE_CLOSE"):
        cr.run(args(window_dir, tmp_path / "c", "--publish-closed-window-truth", *REVEALED,
                    now="2026-10-20T23:59:59Z"))


def test_case_rows_need_a_reveal_and_the_policy_flag(window_dir, tmp_path):
    with pytest.raises(cw.PhaseError, match="TRUTH_PUBLICATION_NOT_AUTHORIZED"):
        cr.run(args(window_dir, tmp_path, "--include-case-detail", *REVEALED))
    paths = cr.run(args(window_dir, tmp_path / "d", "--include-case-detail",
                        "--publish-closed-window-truth", *REVEALED))
    page = json.loads(Path(paths[0]).read_text())
    assert len(page["cases"]) == page["window"]["cases"]
    assert "Seed: revealed and verified" in Path(paths[1]).read_text()


def test_a_reveal_that_does_not_match_the_truth_is_refused(window_dir, tmp_path):
    truth_path = window_dir / "truth.json"
    truth = json.loads(truth_path.read_text())
    truth["cases"][0]["family"] = "fresh_review" if truth["cases"][0]["family"] != (
        "fresh_review") else "stale_authority"
    recommit(truth)
    truth_path.write_text(json.dumps(truth))
    with pytest.raises(ValueError, match="TRUTH_CASES_DIFFER_FROM_REGENERATED_INSTANCES"):
        cr.run(args(window_dir, tmp_path, *REVEALED))


def test_page_adds_no_number_that_is_not_in_the_record(window):
    document = doc(window)
    page = cr.render_markdown(document, revealed=None)
    assert document["window"]["cases_commitment"] in page
    assert page.count("# Contest window") == 1
    for m in document["methods"]:
        assert f"## {m['method_id']}" in page
    for forbidden in ("\u2014", "rew" + "ard", "Auth" + "ority"):  # the public word rules
        assert forbidden not in page


def test_a_profile_for_another_class_is_refused(window):
    with pytest.raises(ValueError, match="PROFILE_CLASS_MISMATCH"):
        doc(window, "GRA-W03-3")


def test_exactly_one_baseline_row_is_required(window):
    def drop(capsules, truth, responses):
        responses["methods"] = [m for m in responses["methods"] if m["role"] != "baseline"]

    def twice(capsules, truth, responses):
        responses["methods"].append(copy.deepcopy(
            next(m for m in responses["methods"] if m["role"] == "baseline")))

    for mutate in (drop, twice):
        with pytest.raises(ValueError, match="DUPLICATE_METHOD_ID|exactly one"):
            doc(window, mutate=mutate)


def test_a_reveal_is_compared_with_the_capsules_not_only_their_ids(window_dir, tmp_path):
    path = window_dir / "capsules.json"
    capsules = json.loads(path.read_text())
    capsules["capsules"][0]["events"][0]["at"] = "2026-10-19T23:00:00Z"  # same qid and commitment
    path.write_text(json.dumps(capsules))
    with pytest.raises(ValueError, match="CAPSULES_DIFFER_FROM_REGENERATED_INSTANCES"):
        cr.run(args(window_dir, tmp_path, *REVEALED))
