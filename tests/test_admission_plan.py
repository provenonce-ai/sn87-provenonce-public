"""Admission as plan versions: proposals only, criteria, checker, row choke point.

Self-contained: a synthetic parent document stands in for the approved plan. The real plan
builder is operator tooling; the maintainers' private suite checks the real digest there.
NO CHAIN, NO NETWORK, NO KEYS.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


ap = load("admission_plan")
HOTKEY = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
OTHER = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
NETUID = 582
NOW = 1_800_000_000_000
SECURE = "https://{}"


def parent_document():
    plan = {
        "schema_version": "sn87-flip-plan/0.1", "mode": "PLAN",
        "would_set": {"dests": [1, 2], "weights": [65535, 65535], "netuid": NETUID},
        "binding": {"miners": [{"expected_uid": 1, "hotkey": "a"},
                               {"expected_uid": 2, "hotkey": "b"}]},
    }
    return {"schema_version": "sn87-flip-plan/0.1", "plan_digest": ap.sha256_of(plan),
            "plan": plan}


def record(**override):
    base = {"schema_version": ap.ENDPOINT_RECORD_SCHEMA, "netuid": NETUID, "uid": 3,
            "hotkey": HOTKEY, "endpoint": "https://example.invalid:8443",
            "issued_at_ms": NOW - 1000, "expires_at_ms": NOW + 86_400_000}
    return base | override


def endpoint(**override):
    return ap.check_endpoint_record(record(**override), netuid=NETUID, now_ms=NOW,
                                    expected_hotkey=HOTKEY, expected_uid=3,
                                    signature_verifier=lambda _r: True)


def criteria(**override):
    args = {"criteria_id": "test-1", "consecutive_windows": 3,
            "min_valid_responses_per_window": 12} | override
    return ap.make_criteria(**args)


def result(window, **override):
    args = dict(uid=3, hotkey=HOTKEY, netuid=NETUID, window=window, seed=window, queried=12,
                valid_responses=12, invalid_responses=0, unavailable=0,
                integrity_failure_codes=[], estimate=0.5, evaluable=12, admitted=12,
                profile_id="IC-FIRST-LIGHT-MIN-1", endpoint_record_digest="sha256:" + "0" * 64)
    args |= override
    if "queried" not in override:
        args["queried"] = (args["valid_responses"] + args["invalid_responses"]
                           + args["unavailable"] + len(list(args["integrity_failure_codes"])))
    return ap.build_window_result(**args)


def evaluate(criteria_doc, results, endpoint_check, *, uid, hotkey, now_window=3,
             netuid=NETUID):
    return ap.evaluate_criteria(criteria_doc, results, endpoint_check, uid=uid, hotkey=hotkey,
                                now_window=now_window, netuid=netuid)


def passing_report(crit=None, results=None):
    crit = crit or criteria()
    results = results or [result(w) for w in (1, 2, 3)]
    return crit, evaluate(crit, results, endpoint(), uid=3, hotkey=HOTKEY)


# ------------------------------------------------------------------ endpoint record
def test_endpoint_record_valid_both_shapes():
    assert endpoint().valid
    signed = {"announcement": {**record(schema_version=ap.ANNOUNCEMENT_SCHEMA)},
              "signature": {"crypto": "sr25519", "signer": HOTKEY, "value": "0x00"}}
    check = ap.check_endpoint_record(signed, netuid=NETUID, now_ms=NOW,
                                     signature_verifier=lambda _r: True)
    assert check.valid and check.signature == "VERIFIED"


@pytest.mark.parametrize("override,code", [
    ({"endpoint": "http://example.invalid"}, "ENDPOINT_NOT_HTTPS_ORIGIN"),
    ({"endpoint": "https://example.invalid/path"}, "ENDPOINT_NOT_AN_ORIGIN"),
    ({"endpoint": SECURE.format("local" + "host:8443")}, "ENDPOINT_LOCAL_HOST"),
    ({"endpoint": SECURE.format(".".join(["10", "0", "0", "5"]))},
     "ENDPOINT_ADDRESS_NOT_GLOBAL"),
    ({"endpoint": SECURE.format("2130706433")}, "ENDPOINT_NUMERIC_HOST_FORM"),
    ({"endpoint": "https://example.invalid:0"}, "ENDPOINT_PORT_ZERO"),
    ({"endpoint": "https://example.invalid/a b"}, "ENDPOINT_NOT_VISIBLE_ASCII"),
    ({"netuid": 1}, "ENDPOINT_NETUID_MISMATCH"),
    ({"hotkey": OTHER}, "ENDPOINT_HOTKEY_MISMATCH"),
    ({"hotkey": "not-a-key"}, "ENDPOINT_HOTKEY_MALFORMED"),
    ({"uid": 9}, "ENDPOINT_UID_MISMATCH"),
    ({"expires_at_ms": NOW - 1}, "ENDPOINT_RECORD_EXPIRED_OR_UNDATED"),
    ({"issued_at_ms": NOW + 3_600_000}, "ENDPOINT_RECORD_ISSUED_IN_FUTURE"),
    ({"schema_version": "other/1"}, "ENDPOINT_SCHEMA_UNKNOWN"),
])
def test_endpoint_record_refusals(override, code):
    check = endpoint(**override)
    assert not check.valid and code in check.reasons


def test_endpoint_signature_is_never_assumed():
    unchecked = ap.check_endpoint_record(record(), netuid=NETUID, now_ms=NOW)
    assert unchecked.valid and unchecked.signature == "NOT_CHECKED"
    bad = ap.check_endpoint_record(record(), netuid=NETUID, now_ms=NOW,
                                   signature_verifier=lambda _r: False)
    assert not bad.valid and bad.signature == "INVALID"
    raising = ap.check_endpoint_record(
        record(), netuid=NETUID, now_ms=NOW,
        signature_verifier=lambda _r: (_ for _ in ()).throw(RuntimeError("x")))
    assert raising.signature == "INVALID"
    assert not ap.check_endpoint_record(None, netuid=NETUID, now_ms=NOW).valid


# ------------------------------------------------------------------------- criteria
def test_criteria_digest_and_validation():
    doc = criteria()
    assert doc["status"] == ap.STATUS and ap.criteria_digest_ok(doc)
    tampered = copy.deepcopy(doc)
    tampered["rules"]["consecutive_windows"] = 1
    assert not ap.criteria_digest_ok(tampered)
    with pytest.raises(ap.AdmissionError):
        criteria(consecutive_windows=0)
    with pytest.raises(ap.AdmissionError):
        criteria(criteria_id="bad id")
    assert criteria() == criteria()  # deterministic


def test_checker_passes_a_clean_streak():
    crit, report = passing_report()
    assert report.passed and report.reasons == [] and report.windows_checked == [1, 2, 3]
    assert len(report.result_digests) == 3
    document = report.as_document()
    assert document["verdict"] == "PASS" and document["criteria_digest"] == crit["criteria_digest"]


def codes(report):
    return [r["code"] for r in report.reasons]


def test_checker_integrity_failure_in_the_streak_fails():
    results = [result(1), result(2, integrity_failure_codes=["RESPONDER_IDENTITY_MISMATCH"]),
               result(3)]
    report = evaluate(criteria(), results, endpoint(), uid=3, hotkey=HOTKEY)
    assert not report.passed and "INTEGRITY_FAILURE" in codes(report)


def test_checker_old_failure_outside_the_streak_does_not_count():
    results = [result(0, integrity_failure_codes=["X"]), result(1), result(2), result(3)]
    report = evaluate(criteria(), results, endpoint(), uid=3, hotkey=HOTKEY)
    assert report.passed


def test_checker_gap_too_few_valid_and_too_few_windows():
    gap = [result(1), result(3), result(4)]
    assert "MISSING_WINDOW" in codes(evaluate(
        criteria(), gap, endpoint(), uid=3, hotkey=HOTKEY, now_window=4))
    thin = [result(1), result(2, valid_responses=11), result(3)]
    assert "TOO_FEW_VALID_RESPONSES" in codes(evaluate(
        criteria(), thin, endpoint(), uid=3, hotkey=HOTKEY))
    few = evaluate(criteria(), [result(1), result(2)], endpoint(), uid=3,
                               hotkey=HOTKEY)
    assert "MISSING_WINDOW" in codes(few) and not few.passed
    early = evaluate(criteria(), [result(0), result(1)], endpoint(), uid=3, hotkey=HOTKEY,
                     now_window=1)
    assert "INSUFFICIENT_WINDOWS" in codes(early) and not early.passed
    none = evaluate(criteria(), [], endpoint(), uid=3, hotkey=HOTKEY)
    assert not none.passed


def test_checker_refuses_tampered_or_non_shadow_results():
    tampered = result(2)
    tampered["valid_responses"] = 99
    report = evaluate(criteria(), [result(1), tampered, result(3)], endpoint(),
                                  uid=3, hotkey=HOTKEY)
    assert "RESULT_DIGEST_INVALID" in codes(report) and not report.passed
    weighted = result(2)
    weighted["weight"] = 1
    weighted["record_digest"] = ap.result_digest(weighted)
    report = evaluate(criteria(), [result(1), weighted, result(3)], endpoint(),
                                  uid=3, hotkey=HOTKEY)
    assert "RESULT_NOT_SHADOW_WEIGHT_ZERO" in codes(report)
    wrong_key = result(2, hotkey=OTHER)
    report = evaluate(criteria(), [result(1), wrong_key, result(3)], endpoint(),
                                  uid=3, hotkey=HOTKEY)
    assert "RESULT_HOTKEY_MISMATCH" in codes(report)
    report = evaluate(criteria(), [result(1), result(2), result(2), result(3)],
                                  endpoint(), uid=3, hotkey=HOTKEY)
    assert "DUPLICATE_WINDOW" in codes(report)


def test_checker_ignores_other_uids_and_checks_endpoint():
    others = [result(w, uid=4) for w in (1, 2, 3)]
    assert not evaluate(criteria(), others, endpoint(), uid=3, hotkey=HOTKEY).passed
    results = [result(w) for w in (1, 2, 3)]
    missing = evaluate(criteria(), results, None, uid=3, hotkey=HOTKEY)
    assert "ENDPOINT_RECORD_MISSING" in codes(missing)
    unsigned = ap.check_endpoint_record(record(), netuid=NETUID, now_ms=NOW)
    report = evaluate(criteria(), results, unsigned, uid=3, hotkey=HOTKEY)
    assert "ENDPOINT_SIGNATURE_NOT_VERIFIED" in codes(report)
    relaxed = criteria(require_signature_verified=False)
    assert evaluate(relaxed, results, unsigned, uid=3, hotkey=HOTKEY).passed
    broken = copy.deepcopy(criteria())
    broken["rules"]["consecutive_windows"] = 1
    assert codes(evaluate(broken, results, endpoint(), uid=3, hotkey=HOTKEY)) \
        == ["CRITERIA_DIGEST_OR_RULES_INVALID"]


# --------------------------------------------------------------------- plan versions
def test_existing_plan_is_never_mutated_and_digest_is_unchanged():
    parent = parent_document()
    before, digest = copy.deepcopy(parent), parent["plan_digest"]
    version = ap.propose_version(parent, uid=3, stage="shadow", hotkey=HOTKEY,
                                 endpoint_check=endpoint())
    assert parent == before and parent["plan_digest"] == digest
    assert ap.document_digest_ok(parent)
    assert version["plan_digest"] != digest
    assert version["parent_plan_digest"] == digest
    assert version["plan"]["parent_plan_digest"] == digest  # lineage is inside the digest
    assert ap.version_digest_ok(version)
    assert version["status"] == "PROPOSED_NEEDS_AUTHORITY_APPROVAL"
    assert version["approval"]["reference"] == ""
    assert version["plan"]["would_set"] == parent["plan"]["would_set"]
    assert "admission" not in parent["plan"]


def test_shadow_uid_never_appears_in_a_weight_row():
    parent = parent_document()
    shadow = ap.propose_version(parent, uid=3, stage="shadow", hotkey=HOTKEY,
                                endpoint_check=endpoint())
    assert ap.eligible_row_uids(shadow) == (1, 2)
    assert ap.compose_row(shadow, {1: 65535, 2: 65535}) == {1: 65535, 2: 65535}
    with pytest.raises(ap.ShadowUidInRow):
        ap.compose_row(shadow, {1: 1, 2: 1, 3: 1})
    local = ap.propose_version(parent, uid=3, stage="local")
    assert ap.eligible_row_uids(local) == (1, 2)
    with pytest.raises(ap.ShadowUidInRow):
        ap.compose_row(local, {3: 1})


def test_row_refuses_non_numbers_and_unknown_uids():
    parent = parent_document()
    with pytest.raises(TypeError):
        ap.compose_row(parent_as_version(parent), {1: object()})
    with pytest.raises(TypeError):
        ap.compose_row(parent_as_version(parent), {1: True})
    with pytest.raises(ap.AdmissionError):
        ap.compose_row(parent_as_version(parent), {"1": 1})
    with pytest.raises(ap.ShadowUidInRow):
        ap.compose_row(parent_as_version(parent), {99: 1})
    assert ap.compose_row(parent_as_version(parent), {2: Decimal("0.5"), 1: 0.25}) \
        == {1: 0.25, 2: Decimal("0.5")}


def parent_as_version(parent):
    return ap.propose_version(parent, uid=3, stage="local")


def shadow_version():
    return ap.propose_version(parent_document(), uid=3, stage="shadow", hotkey=HOTKEY,
                              endpoint_check=endpoint())


def approved(version, reference="approval-record-1"):
    """Stand-in for the approval made outside this repository (adds a reference only)."""
    approved_doc = copy.deepcopy(version)
    approved_doc["approval"]["reference"] = reference
    return approved_doc


def pinned_shadow(crit=None):
    """An approved shadow version that pins the criteria digest."""
    version = ap.propose_version(parent_document(), uid=3, stage="shadow", hotkey=HOTKEY,
                                 endpoint_check=endpoint(), criteria=crit or criteria())
    return approved(version)


def weighted_args(**override):
    args = dict(uid=3, stage="weighted", hotkey=HOTKEY, endpoint_check=endpoint(),
                criteria=criteria(), results=[result(w) for w in (1, 2, 3)], now_window=3)
    return args | override


def test_weighted_needs_criteria_pass_and_leaves_approval_empty():
    shadow = pinned_shadow()
    weighted = ap.propose_version(shadow, **weighted_args())
    assert weighted["approval"]["reference"] == ""
    entry = weighted["plan"]["admission"]["uids"]["3"]
    assert entry["stage"] == "weighted" and entry["now_window"] == 3
    assert entry["criteria_digest"] == criteria()["criteria_digest"]
    assert len(entry["result_digests"]) == 3
    # a weighted uid is NOT row-eligible until an approval reference exists
    assert ap.eligible_row_uids(weighted) == (1, 2)
    with pytest.raises(ap.ShadowUidInRow):
        ap.compose_row(weighted, {3: 1})
    assert ap.eligible_row_uids(approved(weighted, "ref-2")) == (1, 2, 3)
    assert ap.compose_row(approved(weighted, "ref-2"), {3: 7}) == {3: 7}
    with pytest.raises(ap.AdmissionError, match="APPROVAL_REFERENCE_FORMAT"):
        ap.eligible_row_uids(approved(weighted, "has space"))


def test_weighted_refusals():
    shadow = pinned_shadow()
    fail = lambda match, **o: pytest.raises(ap.AdmissionError, match=match)  # noqa: E731
    with fail("CRITERIA_RESULTS_AND_WINDOW_REQUIRED"):
        ap.propose_version(shadow, **weighted_args(results=None))
    with fail("CRITERIA_NOT_PASSED"):
        ap.propose_version(shadow, **weighted_args(results=[result(1)]))
    with fail("CRITERIA_NOT_PASSED"):  # the evidence is recomputed: tampered record
        bad = result(2)
        bad["valid_responses"] = 99
        ap.propose_version(shadow, **weighted_args(results=[result(1), bad, result(3)]))
    with fail("CRITERIA_NOT_PASSED"):  # old windows do not stand in for the current ones
        ap.propose_version(shadow, **weighted_args(now_window=9))
    with fail("CRITERIA_NOT_PINNED_IN_PARENT"):
        ap.propose_version(shadow, **weighted_args(criteria=criteria(criteria_id="other")))
    with fail("WEIGHTED_NEEDS_SHADOW_FIRST"):
        ap.propose_version(parent_document(), **weighted_args())
    with fail("HOTKEY_DIFFERS_FROM_SHADOW_ENTRY"):
        ap.propose_version(shadow, **weighted_args(
            hotkey=OTHER, endpoint_check=ap.check_endpoint_record(
                record(hotkey=OTHER), netuid=NETUID, now_ms=NOW,
                signature_verifier=lambda _r: True),
            results=[result(w, hotkey=OTHER) for w in (1, 2, 3)]))
    unpinned = approved(shadow_version())  # shadow without pinned criteria
    with fail("CRITERIA_NOT_PINNED_IN_PARENT"):
        ap.propose_version(unpinned, **weighted_args())


def test_pin_cannot_change_and_report_documents_are_no_longer_accepted():
    shadow = pinned_shadow()
    with pytest.raises(ap.AdmissionError, match="CRITERIA_PIN_CHANGE"):
        ap.propose_version(shadow, uid=4, stage="shadow", hotkey=OTHER,
                           endpoint_check=ap.check_endpoint_record(
                               record(hotkey=OTHER), netuid=NETUID, now_ms=NOW),
                           criteria=criteria(criteria_id="changed"))
    with pytest.raises(TypeError):  # there is no report argument to forge
        ap.propose_version(shadow, report={"passed": True}, **weighted_args())


def test_the_same_hotkey_cannot_be_staged_on_two_uids():
    shadow = pinned_shadow()
    with pytest.raises(ap.AdmissionError, match="HOTKEY_ALREADY_STAGED"):
        ap.propose_version(shadow, uid=4, stage="shadow", hotkey=HOTKEY,
                           endpoint_check=endpoint())
    base = parent_document()
    base["plan"]["binding"]["miners"][0]["hotkey"] = HOTKEY
    base["plan_digest"] = ap.sha256_of(base["plan"])
    with pytest.raises(ap.AdmissionError, match="HOTKEY_ALREADY_STAGED"):
        ap.propose_version(base, uid=3, stage="shadow", hotkey=HOTKEY, endpoint_check=endpoint())


def test_choke_point_verifies_the_whole_document():
    weighted = approved(ap.propose_version(pinned_shadow(), **weighted_args()), "ref-9")
    assert ap.eligible_row_uids(weighted) == (1, 2, 3)

    def tamper(mutate, code):
        doc = copy.deepcopy(weighted)
        mutate(doc)
        with pytest.raises(ap.AdmissionError, match=code):
            ap.compose_row(doc, {1: 1})

    tamper(lambda d: d["plan"].__setitem__("mode", "X"), "VERSION_DIGEST_INVALID")

    def redigest(doc):
        doc["plan_digest"] = ap.sha256_of(doc["plan"])

    def drop_evidence(doc):
        del doc["plan"]["admission"]["uids"]["3"]["criteria_report_digest"]
        redigest(doc)

    def drop_parent(doc):
        del doc["plan"]["parent_plan_digest"]
        redigest(doc)

    def other_criteria(doc):
        doc["plan"]["admission"]["uids"]["3"]["criteria_digest"] = "sha256:" + "9" * 64
        redigest(doc)

    def duplicate_hotkey(doc):
        doc["plan"]["admission"]["uids"]["4"] = {"stage": "shadow", "hotkey": HOTKEY}
        redigest(doc)

    tamper(drop_evidence, "VERSION_WEIGHTED_ENTRY_WITHOUT_EVIDENCE")
    tamper(drop_parent, "VERSION_PARENT_DIGEST_MISSING")
    tamper(other_criteria, "VERSION_CRITERIA_NOT_PINNED")
    tamper(duplicate_hotkey, "VERSION_ENTRY_HOTKEY_INVALID")
    plain = parent_document()
    plain["plan"]["mode"] = "X"
    with pytest.raises(ap.AdmissionError, match="PLAN_DIGEST_INVALID"):
        ap.eligible_row_uids(plain)


def test_row_values_must_be_finite_non_negative_numbers():
    version = parent_as_version(parent_document())
    for bad in (float("nan"), float("inf"), -1, -0.5, Decimal("-1"), Decimal("NaN")):
        with pytest.raises(ap.AdmissionError, match="ROW_VALUE_MUST_BE_FINITE"):
            ap.compose_row(version, {1: bad})
    assert ap.compose_row(version, {1: 0}) == {1: 0}


def test_criteria_rules_are_validated_and_bad_input_never_crashes():
    for override in ({"consecutive_windows": 0}, {"min_valid_responses_per_window": 0},
                     {"consecutive_windows": True}, {"consecutive_windows": "3"},
                     {"max_integrity_failures_per_window": -1}):
        with pytest.raises(ap.AdmissionError):
            criteria(**override)
    forged = criteria()
    forged["rules"]["consecutive_windows"] = 0
    forged["rules"]["min_valid_responses_per_window"] = 0
    body = {k: v for k, v in forged.items() if k != "criteria_digest"}
    forged["criteria_digest"] = ap.sha256_of(body)  # self-consistent but invalid rules
    assert not ap.criteria_digest_ok(forged)
    report = evaluate(forged, [], endpoint(), uid=3, hotkey=HOTKEY)
    assert not report.passed and codes(report) == ["CRITERIA_DIGEST_OR_RULES_INVALID"]
    assert not ap.criteria_digest_ok(None) and not ap.criteria_digest_ok([])
    assert codes(evaluate(criteria(), [], endpoint(), uid=3, hotkey=HOTKEY, now_window="3")) \
        == ["NOW_WINDOW_INVALID"]


def redigested(record_):
    record_["record_digest"] = ap.result_digest(record_)
    return record_


def test_malformed_results_fail_with_codes_not_exceptions():
    for field, value, code in (("valid_responses", "12", "RESULT_FIELD_INVALID_valid_responses"),
                               ("queried", True, "RESULT_FIELD_INVALID_queried"),
                               ("valid_responses", 13, "RESULT_COUNTS_INCONSISTENT"),
                               ("integrity_failure_codes", [1],
                                "RESULT_FIELD_INVALID_integrity_failure_codes"),
                               ("window", 1.5, "RESULT_WINDOW_INVALID")):
        broken = redigested(result(2) | {field: value})
        report = evaluate(criteria(), [result(1), broken, result(3)], endpoint(), uid=3,
                          hotkey=HOTKEY)
        assert not report.passed and code in codes(report), (field, codes(report))
    junk = evaluate(criteria(), [None, "x", {}], endpoint(), uid=3, hotkey=HOTKEY)
    assert not junk.passed and "RESULT_SCHEMA_INVALID" in codes(junk)


def test_results_after_the_current_window_do_not_count():
    results = [result(w) for w in (1, 2, 3, 4)]
    report = evaluate(criteria(), results, endpoint(), uid=3, hotkey=HOTKEY, now_window=3)
    assert "RESULT_WINDOW_IN_THE_FUTURE" in codes(report) and not report.passed


def test_other_proposal_refusals():
    parent = parent_document()
    with pytest.raises(ap.AdmissionError, match="UID_IN_APPROVED_BASE_PLAN"):
        ap.propose_version(parent, uid=1, stage="local")
    with pytest.raises(ap.AdmissionError, match="UID_INVALID"):
        ap.propose_version(parent, uid=0, stage="local")
    with pytest.raises(ap.AdmissionError, match="STAGE_UNKNOWN"):
        ap.propose_version(parent, uid=3, stage="live")
    with pytest.raises(ap.AdmissionError, match="ENDPOINT_RECORD_NOT_VALID_FOR_HOTKEY"):
        ap.propose_version(parent, uid=3, stage="shadow", hotkey=HOTKEY)
    with pytest.raises(ap.AdmissionError, match="ENDPOINT_RECORD_NOT_VALID_FOR_HOTKEY"):
        ap.propose_version(parent, uid=3, stage="shadow", hotkey=OTHER,
                           endpoint_check=endpoint())
    with pytest.raises(ap.AdmissionError, match="HOTKEY_REQUIRED"):
        ap.propose_version(parent, uid=3, stage="shadow", endpoint_check=endpoint())
    with pytest.raises(ap.AdmissionError, match="PARENT_VERSION_NOT_APPROVED"):
        ap.propose_version(shadow_version(), uid=4, stage="local")
    bad = parent_document()
    bad["plan"]["mode"] = "CHANGED"
    with pytest.raises(ap.AdmissionError, match="PARENT_DIGEST_INVALID"):
        ap.propose_version(bad, uid=3, stage="local")


def test_versions_chain_on_an_approved_parent():
    first = approved(shadow_version())
    second = ap.propose_version(first, uid=4, stage="local")
    assert second["plan_version"] == 3 and second["parent_plan_digest"] == first["plan_digest"]
    assert set(second["plan"]["admission"]["uids"]) == {"3", "4"}
    # a downgrade is a proposal like any other and needs no criteria
    down = ap.propose_version(first, uid=3, stage="local")
    assert down["plan"]["admission"]["uids"]["3"]["stage"] == "local"


# ------------------------------------------------------------------------------ CLI
def test_cli_criteria_check_and_propose(tmp_path, capsys):
    parent_path = tmp_path / "PLAN.json"
    parent_path.write_text(json.dumps(parent_document()))
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(record()))
    crit_path = tmp_path / "criteria.json"
    assert ap.main(["criteria", "--criteria-id", "cli-1", "--windows", "2",
                    "--min-valid-responses", "12", "--allow-unverified-signature",
                    "--out", str(crit_path)]) == 0
    results = tmp_path / "results"
    results.mkdir()
    for w in (1, 2):
        (results / f"w{w}.json").write_text(json.dumps(result(w)))
    common = ["--criteria", str(crit_path), "--results", str(results), "--uid", "3",
              "--hotkey", HOTKEY, "--netuid", str(NETUID), "--endpoint-record",
              str(record_path), "--now-ms", str(NOW), "--now-window", "2"]
    assert ap.main(["check", *common, "--report-out", str(tmp_path / "report.json")]) == 0
    assert "PASS" in capsys.readouterr().out
    (results / "w2.json").unlink()
    assert ap.main(["check", *common]) == 1
    assert "FAIL" in capsys.readouterr().out
    out = tmp_path / "out"
    assert ap.main(["propose", "--parent", str(parent_path), "--uid", "3", "--stage", "shadow",
                    "--hotkey", HOTKEY, "--endpoint-record", str(record_path),
                    "--now-ms", str(NOW), "--out", str(out)]) == 0
    written = json.loads(next(out.glob("PLAN_VERSION_*")).read_text())
    assert written["status"] == ap.STATUS and written["approval"]["reference"] == ""
    # create-only: a second identical run refuses to overwrite
    assert ap.main(["propose", "--parent", str(parent_path), "--uid", "3", "--stage", "shadow",
                    "--hotkey", HOTKEY, "--endpoint-record", str(record_path),
                    "--now-ms", str(NOW), "--out", str(out)]) == 2
    assert ap.main(["propose", "--parent", str(parent_path), "--uid", "1", "--stage", "local",
                    "--out", str(out)]) == 2


def test_module_is_standard_library_only():
    import ast
    tree = ast.parse((ROOT / "scripts/admission_plan.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


def test_a_result_from_another_subnet_is_rejected():
    results = [result(1), result(2, netuid=7), result(3)]
    report = evaluate(criteria(), results, endpoint(), uid=3, hotkey=HOTKEY)
    assert not report.passed and "RESULT_NETUID_MISMATCH" in codes(report)
    assert not evaluate(criteria(), [result(w) for w in (1, 2, 3)], endpoint(), uid=3,
                        hotkey=HOTKEY, netuid=7).passed
    with pytest.raises(ap.AdmissionError, match="CRITERIA_NOT_PASSED"):
        ap.propose_version(pinned_shadow(), **weighted_args(
            results=[result(1), result(2, netuid=7), result(3)]))


VERIFIER_CALLS = []


def accepting_verifier(record_):
    VERIFIER_CALLS.append(record_)
    return True


def test_cli_check_can_pass_with_a_named_signature_verifier(tmp_path, capsys):
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(record()))
    crit_path = tmp_path / "criteria.json"
    ap.main(["criteria", "--criteria-id", "v", "--windows", "2", "--min-valid-responses", "12",
             "--out", str(crit_path)])  # the secure default: a verified signature is required
    results = tmp_path / "results"
    results.mkdir()
    for w in (1, 2):
        (results / f"w{w}.json").write_text(json.dumps(result(w)))
    common = ["check", "--criteria", str(crit_path), "--results", str(results), "--uid", "3",
              "--hotkey", HOTKEY, "--netuid", str(NETUID), "--endpoint-record",
              str(record_path), "--now-ms", str(NOW), "--now-window", "2"]
    assert ap.main(common) == 1  # the default verifier rejects an unsigned minimal record
    assert "ENDPOINT_SIGNATURE_INVALID" in capsys.readouterr().out
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        assert ap.main([*common, "--signature-verifier",
                        "test_admission_plan:accepting_verifier"]) == 0
    finally:
        sys.path.pop(0)
    assert VERIFIER_CALLS
    assert ap.main([*common, "--signature-verifier", "nonsense"]) == 2


def test_cli_check_uses_the_repository_announcement_verifier_by_default(tmp_path, capsys):
    from bittensor import sp_core

    from sn87_provenonce.miner_node import announcement as ann
    key = sp_core.Keypair.create_from_uri("//Bob")
    signed = ann.sign(ann.Announcement(
        netuid=NETUID, hotkey=key.ss58_address, endpoint="https://example.invalid:8443",
        sequence=1, issued_at_ms=NOW - 1000, expires_at_ms=NOW + 86_400_000,
        transport="gra-transport/0.1"), key)
    path = tmp_path / "announcement.json"
    path.write_bytes(signed)
    crit = tmp_path / "criteria.json"
    ap.main(["criteria", "--criteria-id", "d", "--windows", "2", "--min-valid-responses", "12",
             "--out", str(crit)])
    results = tmp_path / "results"
    results.mkdir()
    for w in (1, 2):
        (results / f"w{w}.json").write_text(json.dumps(result(w, hotkey=key.ss58_address)))
    common = ["check", "--criteria", str(crit), "--results", str(results), "--uid", "3",
              "--hotkey", key.ss58_address, "--netuid", str(NETUID), "--now-ms", str(NOW),
              "--now-window", "2"]
    assert ap.main([*common, "--endpoint-record", str(path)]) == 0
    assert "PASS" in capsys.readouterr().out
    tampered = json.loads(signed)
    tampered["announcement"]["endpoint"] = "https://example.invalid:9999"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(tampered))
    assert ap.main([*common, "--endpoint-record", str(bad)]) == 1
    assert "ENDPOINT_SIGNATURE_INVALID" in capsys.readouterr().out
