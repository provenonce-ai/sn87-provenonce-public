"""The second-party reproduction kit on the committed synthetic fixture.

The untouched fixture gives PASS on every recomputed step and UNVERIFIED on the four things the
files alone cannot show (exit 3). Each published artifact is then changed in turn and the step
that owns it must FAIL (exit 1). Public: it needs no private executor and no chain.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contest_window as cw  # noqa: E402
import reproduce_window as rw  # noqa: E402

FIXTURE = ROOT / "examples" / "window-repro-fixture"
WID = "demo-repro-0001"
BLOCK = "4242424:0x" + "2c0550be68db226c01c3460689b240a82498b44ad7ec3cc754439cf04849cad4"
RECOMPUTED = [f"S{i}" for i in range(1, 12)]
UNVERIFIABLE = ["A", "B", "G", "O", "T"]


def run(directory, capsys, *extra):
    code = rw.main(["--dir", str(directory), "--json", *extra])
    out = json.loads(capsys.readouterr().out)
    return code, {s["key"]: s for s in out["steps"]}, out


@pytest.fixture
def pub(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / "pub")
    return tmp_path / "pub"


def edit(pub, name, change):
    path = pub / name
    doc = json.loads(path.read_text("utf-8"))
    change(doc)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", "utf-8")


def sha(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def test_untouched_fixture(pub, capsys):
    code, steps, out = run(pub, capsys)
    assert code == 3 and out["verdict"] == "UNVERIFIED"
    assert {k: steps[k]["status"] for k in RECOMPUTED} == dict.fromkeys(RECOMPUTED, "PASS")
    assert {k: steps[k]["status"] for k in UNVERIFIABLE} == dict.fromkeys(UNVERIFIABLE,
                                                                          "UNVERIFIED")
    claim = "\n".join(out["claim"])
    assert "independent participation: not shown" in claim
    assert "weighted activity: not shown" in claim
    assert "T truth correct for capsule-computed families: UNVERIFIED" in claim
    assert "B opening block is canonical: UNVERIFIED" in claim
    assert "MANUAL" in steps["S3"]["reason"]


def test_text_output_and_exit_code(capsys):
    assert rw.main(["--dir", str(FIXTURE)]) == 3
    text = capsys.readouterr().out
    assert "[PASS] S1 schedule commitments" in text and "[UNVERIFIED] B opening block" in text
    assert "CLAIM for window demo-repro-0001" in text


def test_outside_evidence_turns_unverified_into_pass_or_fail(capsys):
    code, steps, _ = run(FIXTURE, capsys, "--expect-block", BLOCK,
                         "--commitments-seen-at", "2026-11-09T00:00:00Z")
    assert code == 3 and steps["B"]["status"] == steps["A"]["status"] == "PASS"
    code, steps, _ = run(FIXTURE, capsys, "--expect-block", "4242424:0x" + "0" * 64)
    assert code == 1 and steps["B"]["status"] == "FAIL"
    code, steps, _ = run(FIXTURE, capsys, "--commitments-seen-at", "2026-11-10T00:00:01Z")
    assert code == 1 and steps["A"]["status"] == "FAIL"


def test_window_is_detected_and_given(capsys):
    assert rw.detect_window(FIXTURE) == WID
    assert rw.main(["--dir", str(FIXTURE), "--window", WID, "--json"]) == 3
    capsys.readouterr()
    assert rw.main(["--dir", str(FIXTURE.parent)]) == 2  # no single window there


def test_no_truth_published_leaves_scores_unverified_not_failed(pub, capsys):
    (pub / f"window_{WID}.truth.json").unlink()
    code, steps, _ = run(pub, capsys)
    assert code == 3
    assert steps["S5"]["status"] == "UNVERIFIED" and "not supplied" in steps["S5"]["reason"]
    for key in ("S7", "S8", "S9", "S10", "S11"):
        assert steps[key]["status"] == "UNVERIFIED", key
    assert all(steps[k]["status"] == "PASS" for k in ("S1", "S2", "S3", "S4", "S6"))


def test_missing_files_never_pass(pub, capsys):
    (pub / "reveal-bundle.json").unlink()
    code, steps, _ = run(pub, capsys)
    assert code == 3 and steps["S2"]["status"] == "UNVERIFIED"
    assert steps["S3"]["status"] == "UNVERIFIED" and steps["S4"]["status"] == "UNVERIFIED"


def test_unparsable_file_is_a_fail(pub, capsys):
    (pub / f"window_{WID}.derived.json").write_text("{not json", "utf-8")
    code, steps, _ = run(pub, capsys)
    assert code == 1 and steps["S8"]["status"] == "FAIL" and "not valid JSON" in steps["S8"][
        "reason"]


def test_digest_only_submissions_are_unverified_not_pass(pub, capsys):
    def drop(doc):
        for sub in doc["methods"][0]["submissions"].values():
            sub["response"] = None
    edit(pub, f"window_{WID}.submissions.json", drop)
    code, steps, _ = run(pub, capsys)
    assert steps["S6"]["status"] == "UNVERIFIED" and "digest only" in steps["S6"]["reason"]
    assert code == 1  # S7 also fails: the scored response is gone
    assert steps["S7"]["status"] == "FAIL"


def commitments_resealed(doc):
    doc["schedule_commitment"] = cw.digest(cw.SCHEDULE_DOMAIN, rw.canonical_bytes(doc["windows"]))


def t_schedule_row(doc):
    doc["windows"][0]["spec_commitment"] = sha("other")


def t_seed_commitment_resealed(doc):
    doc["windows"][0]["seed_commitment"] = sha("other")
    commitments_resealed(doc)


def t_spec_commitment_resealed(doc):
    doc["windows"][0]["spec_commitment"] = sha("other")
    commitments_resealed(doc)


def t_profile_commitment(doc):
    doc["profile_commitment"] = sha("other")


def t_preseed(doc):
    doc["windows"][0]["reveal"]["preseed"] = "00" * 32


def t_block_hash(doc):
    doc["windows"][0]["reveal"]["beacon"]["hash"] = "0x" + "11" * 32
    doc["windows"][0]["open_record"]["beacon"]["hash"] = "0x" + "11" * 32


def t_mix(doc):
    doc["windows"][0]["reveal"]["spec"]["mix"][0]["count"] += 1


def t_not_opened(doc):
    doc["windows"][0] = {"window_id": WID, "status": "NOT_OPENED"}


def t_capsule(doc):
    doc["capsules"][0]["qid"] = "q-tampered"


def t_cases_commitment(doc):
    doc["cases_commitment"] = sha("other")


def t_beacon_in_open_record(doc):
    doc["beacon"]["number"] += 1


def t_truth_state(doc):
    case = next(c for c in doc["cases"] if c["truth"]["state"] == "FINDINGS")
    case["truth"]["state"] = "NO_MATERIAL_DEVIATION"


def t_truth_resealed(doc):
    t_truth_state(doc)
    doc["truth_commitment"] = cw.truth_commitment(
        doc["cases"], window_id=doc["window_id"], seed_commitment=doc["seed_commitment"],
        cases_commitment=doc["cases_commitment"], salt=doc["salt"])


def _method(doc, name):
    return next(m for m in doc["methods"] if m["method_id"] == name)


def t_response_changed(doc):
    sub = next(iter(_method(doc, "outside_uid_7")["submissions"].values()))
    sub["response"]["rationale"] = "changed after publication"


def t_response_changed_with_digest(doc):
    sub = next(iter(_method(doc, "outside_uid_7")["submissions"].values()))
    sub["response"]["findings"] = []
    sub["response"]["state"] = "NO_MATERIAL_DEVIATION"
    sub["response_digest"] = rw.digest_of(sub["response"])


def t_outcome_timeout_with_response(doc):
    next(iter(_method(doc, "outside_uid_7")["submissions"].values()))["outcome"] = "TIMEOUT"


def t_unknown_code(doc):
    sub = next(iter(_method(doc, "outside_uid_7")["submissions"].values()))
    sub["outcome"], sub["response"], sub["response_digest"] = "MADE_UP_CODE", None, None


def t_wrong_capsule_reply_claimed_valid(doc):
    sub = next(s for s in _method(doc, "outside_uid_5")["submissions"].values()
               if s["outcome"] == "REPLY_WRONG_CAPSULE")
    sub["outcome"] = "REPLY_SCHEMA_INVALID"


def t_baseline_response(doc):
    sub = next(iter(_method(doc, "public_contract_baseline")["submissions"].values()))
    sub["response"]["rationale"] = "not the public baseline"
    sub["response_digest"] = rw.digest_of(sub["response"])


def t_estimate(doc):
    _method(doc, "outside_uid_7")["score"]["estimate"] = "0.5"


def t_agreement(doc):
    _method(doc, "outside_uid_7")["agreement"]["state_all"]["agree"] -= 1


def t_pref_weight(doc):
    doc["preference_row"]["weights"]["weighted_b"] = "0.5"


def t_u16(doc):
    doc["weight_row"]["u16_weights"][1] += 1


def t_shadow_in_row(doc):
    doc["weight_row"]["uids"].append(5)
    doc["weight_row"]["u16_weights"].append(100)


def t_gate(doc):
    doc["weight_gate"]["family"]["weight_eligible"] = True


def t_admission_verdict(doc):
    report = next(r for r in doc["admission"]["reports"] if r["uid"] == 5)
    report["passed"], report["verdict"], report["reasons"] = True, "PASS", []


def t_admission_record(doc):
    doc["admission"]["results"][0]["valid_responses"] += 1


def t_criteria(doc):
    doc["admission"]["criteria"]["rules"]["min_valid_responses_per_window"] = 1


TAMPERS = [
    ("commitments.json", t_schedule_row, "S1"),
    ("commitments.json", t_profile_commitment, "S1"),
    ("reveal-bundle.json", t_preseed, "S2"),
    ("reveal-bundle.json", t_block_hash, "S3"),
    ("reveal-bundle.json", t_mix, "S3"),
    ("reveal-bundle.json", t_not_opened, "S2"),
    (f"window_{WID}.capsules.json", t_capsule, "S4"),
    (f"window_{WID}.capsules.json", t_cases_commitment, "S3"),  # the bundle's copy disagrees
    (f"window_{WID}.capsules.json", t_beacon_in_open_record, "S3"),
    (f"window_{WID}.truth.json", t_truth_state, "S5"),
    (f"window_{WID}.truth.json", t_truth_resealed, "S5"),
    (f"window_{WID}.submissions.json", t_response_changed, "S6"),
    (f"window_{WID}.submissions.json", t_response_changed_with_digest, "S7"),
    (f"window_{WID}.submissions.json", t_outcome_timeout_with_response, "S6"),
    (f"window_{WID}.submissions.json", t_unknown_code, "S6"),
    (f"window_{WID}.submissions.json", t_wrong_capsule_reply_claimed_valid, "S6"),
    (f"window_{WID}.submissions.json", t_baseline_response, "S6"),
    (f"window_{WID}.json", t_estimate, "S7"),
    (f"window_{WID}.json", t_agreement, "S7"),
    (f"window_{WID}.derived.json", t_pref_weight, "S8"),
    (f"window_{WID}.derived.json", t_u16, "S9"),
    (f"window_{WID}.derived.json", t_shadow_in_row, "S9"),
    (f"window_{WID}.derived.json", t_gate, "S10"),
    (f"window_{WID}.derived.json", t_admission_verdict, "S11"),
    (f"window_{WID}.derived.json", t_admission_record, "S11"),
    (f"window_{WID}.derived.json", t_criteria, "S11"),
]


def tamper_by_bundle(name, change):
    if name != "reveal-bundle.json":
        return change

    def wrapped(doc):
        change({"windows": doc["windows"]})
    return wrapped


@pytest.mark.parametrize("name,change,step", TAMPERS,
                         ids=[f"{t[2]}-{t[1].__name__}" for t in TAMPERS])
def test_tampering_fails_the_owning_step(pub, capsys, name, change, step):
    edit(pub, name, tamper_by_bundle(name, change))
    code, steps, _ = run(pub, capsys)
    assert code == 1
    assert steps[step]["status"] == "FAIL", {k: v["status"] for k, v in steps.items()}
    if int(step[1:]) >= 6:  # a change to a later artifact never fails the commitment steps
        assert all(steps[f"S{i}"]["status"] == "PASS" for i in range(1, 6))


@pytest.mark.parametrize("change,step", [(t_seed_commitment_resealed, "S2"),
                                         (t_spec_commitment_resealed, "S3")])
def test_commitments_changed_and_resealed_with_the_bundle_still_fail(pub, capsys, change, step):
    """An operator who rewrites the commitments and the bundle's pointer to them is caught by
    the reveal: the revealed values no longer open the rewritten commitments."""
    edit(pub, "commitments.json", change)
    sealed = json.loads((pub / "commitments.json").read_text("utf-8"))["schedule_commitment"]
    edit(pub, "reveal-bundle.json", lambda d: d.update(schedule_commitment=sealed))
    code, steps, _ = run(pub, capsys)
    assert code == 1 and steps[step]["status"] == "FAIL"


def test_tamper_table_covers_every_artifact_and_every_recomputed_step():
    assert {t[0].replace(WID, "ID") for t in TAMPERS} >= {
        "commitments.json", "reveal-bundle.json", "window_ID.capsules.json",
        "window_ID.truth.json", "window_ID.submissions.json", "window_ID.json",
        "window_ID.derived.json"}
    assert {t[2] for t in TAMPERS} == set(RECOMPUTED)


def test_quantizer_matches_the_chain_dry_run_quantizer():
    from sn87_provenonce import weights_dry_run as dry
    if dry.normalize is None:
        pytest.skip("the bittensor SDK is an optional extra")
    target = {"network": "test", "genesis": dry.TESTNET_GENESIS, "sdk_version": "11.1.0",
              "netuid": 87, "block": 1000, "spec_version": 471, "version_key": 0,
              "min_allowed_weights": 1, "max_weights_limit": 65535, "validator_uid": 0,
              "rate_limit_blocks": 100, "last_update_block": 0, "registered": True,
              "validator_permit": True, "active": True, "commit_reveal": False}
    for rows in ([(1, "0.5"), (2, "0.25")], [(3, "1"), (9, "0.333333333333333314")],
                 [(4, "0.7"), (5, "0.00001"), (6, "0")], [(1, "0"), (2, "0")]):
        got = rw.quantize_u16(rows)
        if not got[0]:
            continue  # the dry run reports an empty row as a state; the kit as empty lists
        want = dry.dry_run({"target": target, "weights": [
            {"uid": u, "weight": w} for u, w in rows]})
        assert got == (want["uids"], want["u16_weights"])
    assert rw.quantize_u16([(1, "0"), (2, "0")]) == ([], [])


def test_outcome_kinds():
    kinds = {"VALID": "valid", "REPLY_SCHEMA_INVALID": "invalid", "REPLY_WRONG_CAPSULE": "invalid",
             "TIMEOUT": "unavailable", "NOT_QUERIED_TIME_BUDGET": "unavailable",
             "REMOTE_REJECTED_403": "unavailable", "CONNECTION_ConnectError": "unavailable",
             "RESPONSE_BINDING_FAILED": "integrity", "RATE_LIMITED": "integrity",
             "BOUNDARY_ERROR_UNCODED": "integrity", "nope": None, 7: None}
    assert {k: rw.outcome_kind(k) for k in kinds} == kinds


def test_fixture_is_synthetic_and_names_its_fake_block():
    reveal = json.loads((FIXTURE / "reveal-bundle.json").read_text("utf-8"))
    beacon = reveal["windows"][0]["reveal"]["beacon"]
    assert beacon["manual"] is True and WID.startswith("demo-")
    commitments = json.loads((FIXTURE / "commitments.json").read_text("utf-8"))
    assert commitments["beacon"]["network"] == "fixture:fake-beacon"
    text = (FIXTURE / f"window_{WID}.submissions.json").read_text("utf-8")
    assert "FICTIONAL-PLACEHOLDER-HOTKEY" in text


# --- review fixes -------------------------------------------------------------------------------

def reseal_truth_everywhere(pub):
    """A forger who changes a truth state and re-seals the truth, the open record and the bundle's
    copy of it so that every published file agrees."""
    edit(pub, f"window_{WID}.truth.json", t_truth_resealed)
    new = json.loads((pub / f"window_{WID}.truth.json").read_text("utf-8"))["truth_commitment"]
    edit(pub, f"window_{WID}.capsules.json", lambda d: d.update(truth_commitment=new))
    edit(pub, "reveal-bundle.json", lambda d: d["windows"][0]["open_record"].update(
        truth_commitment=new))


def seen_file(tmp_path):
    opened = json.loads((FIXTURE / f"window_{WID}.capsules.json").read_text("utf-8"))
    path = tmp_path / "seen.json"
    path.write_text(json.dumps({"window_commitments": cw.request_commitments(opened)}), "utf-8")
    return path


def test_b1_profile_swap_in_the_result_fails(pub, capsys):
    from sn87_provenonce import profile as profiles
    other = profiles.load("IC-FIRST-LIGHT-MIN-1")

    def swap(doc):
        doc["profile"]["profile_id"] = other.profile_id
        doc["profile"]["profile_commitment"] = other.commitment
    edit(pub, f"window_{WID}.json", swap)
    code, steps, _ = run(pub, capsys)
    assert code == 1
    assert steps["S7"]["status"] == steps["S8"]["status"] == "FAIL"
    assert "PROFILE_NOT_THE_COMMITTED_PROFILE" in steps["S7"]["reason"]


def test_b2_identity_stage_cannot_be_changed_in_the_derived_record(pub, capsys):
    def smuggle(doc):
        next(i for i in doc["identities"] if i["method_id"] == "outside_uid_5")["stage"] = (
            "weighted")
    edit(pub, f"window_{WID}.derived.json", smuggle)
    code, steps, _ = run(pub, capsys)
    assert code == 1 and steps["S8"]["status"] == steps["S9"]["status"] == "FAIL"
    assert "IDENTITIES_DIFFER_FROM_SUBMISSIONS" in steps["S9"]["reason"]


@pytest.mark.parametrize("field,value", [("uid", 9), ("hotkey", "OTHER"), ("method_id", "ghost")])
def test_b2_any_identity_field_difference_fails(pub, capsys, field, value):
    edit(pub, f"window_{WID}.derived.json", lambda d: d["identities"][0].update({field: value}))
    code, steps, _ = run(pub, capsys)
    assert code == 1 and steps["S9"]["status"] == "FAIL"


def test_b2_shadow_set_comes_from_the_submissions(pub, capsys):
    """Changing the stage in the submissions as well still leaves the derived record and the
    recomputed rows disagreeing with the published ones."""
    edit(pub, f"window_{WID}.submissions.json", lambda d: next(
        m for m in d["methods"] if m["method_id"] == "outside_uid_5").update(stage="weighted"))
    code, steps, _ = run(pub, capsys)
    assert code == 1 and steps["S9"]["status"] == "FAIL"


def test_b3_resealed_truth_and_open_record_pass_s1_to_s11_but_not_the_o_line(pub, capsys,
                                                                            tmp_path):
    reseal_truth_everywhere(pub)
    code, steps, _ = run(pub, capsys)
    # the truth now differs, so scores differ from the published result: S7 catches this forger
    # only because the result was not re-sealed. A forger who re-seals that too is caught by O.
    assert steps["S5"]["status"] == "PASS" and steps["O"]["status"] == "UNVERIFIED"
    code, steps, _ = run(pub, capsys, "--open-record-seen", str(seen_file(tmp_path)))
    assert code == 1 and steps["O"]["status"] == "FAIL"


def test_o_line_passes_on_the_real_open_record_and_the_wording_is_conditional(tmp_path, capsys):
    code, steps, _ = run(FIXTURE, capsys, "--open-record-seen", str(seen_file(tmp_path)))
    assert code == 3 and steps["O"]["status"] == "PASS"
    assert "only if the open record is the one seen when the window opened" in steps["S5"][
        "reason"]


def test_o_line_with_a_malformed_seen_file_fails_cleanly(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("[]", "utf-8")
    code, steps, _ = run(FIXTURE, capsys, "--open-record-seen", str(path))
    assert code == 1 and steps["O"]["status"] == "FAIL"


def test_b4_claim_states_the_limits(capsys):
    _, _, out = run(FIXTURE, capsys)
    claim = "\n".join(out["claim"])
    assert claim.startswith("Internally consistent, operator-supplied files: CLAIM for window")
    assert "MANUAL" in claim
    assert "passes S1 to S11" in claim and "miner signatures" in claim
    assert "cannot be falsified from files" in claim


def test_commitments_seen_at_needs_a_time_zone(capsys):
    with pytest.raises(SystemExit) as stop:
        rw.main(["--dir", str(FIXTURE), "--commitments-seen-at", "2026-11-09T00:00:00"])
    assert stop.value.code == 2
    with pytest.raises(SystemExit):
        rw.main(["--dir", str(FIXTURE), "--commitments-seen-at", "yesterday"])
    code, steps, _ = run(FIXTURE, capsys, "--commitments-seen-at", "2026-11-09T01:00:00+01:00")
    assert steps["A"]["status"] == "PASS"
    code, steps, _ = run(FIXTURE, capsys, "--commitments-seen-at", "2026-11-10T01:00:00+02:00")
    assert steps["A"]["status"] == "PASS"  # 23:00 UTC the day before
    code, steps, _ = run(FIXTURE, capsys, "--commitments-seen-at", "2026-11-10T00:00:00Z")
    assert steps["A"]["status"] == "FAIL"


def test_expect_block_hash_compare_is_case_insensitive(capsys):
    number, _, digest = BLOCK.partition(":")
    code, steps, _ = run(FIXTURE, capsys, "--expect-block", number + ":0x" + digest[2:].upper())
    assert steps["B"]["status"] == "PASS"


def test_s6_and_s7_do_not_run_on_cases_that_did_not_verify(pub, capsys):
    edit(pub, f"window_{WID}.capsules.json", t_capsule)
    code, steps, _ = run(pub, capsys)
    assert steps["S4"]["status"] == "FAIL"
    for key in ("S6", "S7", "S8", "S9", "S10", "S11"):
        assert steps[key]["status"] == "UNVERIFIED", key
        assert "S4" in steps[key]["reason"]


@pytest.mark.parametrize("name,body", [("commitments.json", "null"), ("commitments.json", "[]"),
                                       (f"window_{WID}.derived.json", "null"),
                                       ("reveal-bundle.json", "[]"),
                                       (f"window_{WID}.truth.json", "null")])
def test_null_or_list_json_is_malformed_not_missing(pub, capsys, name, body):
    (pub / name).write_text(body, "utf-8")
    code, steps, _ = run(pub, capsys)  # never a traceback
    assert code == 1
    assert any(s["status"] == "FAIL" and "not an object" in s["reason"] for s in steps.values())


def test_informational_lines_never_traceback_on_odd_input(pub, capsys):
    (pub / "commitments.json").write_text("[]", "utf-8")
    code, steps, _ = run(pub, capsys, "--commitments-seen-at", "2026-11-09T00:00:00Z",
                         "--expect-block", BLOCK)
    assert code == 1 and steps["A"]["status"] in ("UNVERIFIED", "FAIL")


def test_free_text_is_not_published_in_the_fixture():
    doc = json.loads((FIXTURE / f"window_{WID}.submissions.json").read_text("utf-8"))

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("method", "rationale"):
                    assert item == rw.NOT_PUBLISHED, key
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(doc["methods"])
    assert rw.redact({"method": "x", "rationale": "y", "findings": [{"rationale": "z",
                                                                      "code": "C"}]}) == {
        "method": "NOT_PUBLISHED", "rationale": "NOT_PUBLISHED",
        "findings": [{"rationale": "NOT_PUBLISHED", "code": "C"}]}
