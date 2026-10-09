"""The attested validator digest, recomputed from the published truth and the public scorer.

Runs in the public tree. This is the check the attestation verifier makes, as a test: the
staging validator, fed the golden truth, reproduces the validator pinned digest that every
attested run records. A wrong truth changes the digest, so the match is evidence for the truth.

What the digest binds of the truth: each case's state and its defect codes. It does NOT bind
defect severity or required_refs (measured in the test below), so those fields of the published
files are checked only by the private regeneration test, not by this digest.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from golden_support import STORE, golden_truth

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_golden_test",
                                                  ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


staging = _load("staging_subnet")
va = _load("verify_attestation")
ATTESTATIONS = sorted((ROOT / "attestation").glob("SN87_TESTNET_ATTESTATION_0*.json"))


def attested_digests():
    pairs = set()
    for path in ATTESTATIONS:
        for run in json.loads(path.read_text(encoding="utf-8"))["runs"]:
            pairs.add((run["validator_seed"], run["validator_timestamp"],
                       run["validator_pinned_digest"]))
    return pairs


@pytest.fixture(scope="module")
def receipt():
    return staging.run_staging(seed=0, timestamp=staging.DEFAULT_TIMESTAMP,
                               truth_for=STORE.truth_for, truth_source="golden test")


def test_golden_truth_reproduces_the_attested_validator_digest(receipt):
    pairs = attested_digests()
    assert pairs, "the attestations hold no runs"
    for seed, stamp, digest in pairs:
        assert (seed, stamp) == (0, staging.DEFAULT_TIMESTAMP)
        assert receipt["pinned_digest"] == digest


def test_the_run_is_the_validators_sixteen_instances_with_no_network(receipt):
    pinned = receipt["pinned"]
    assert len(pinned["validator"]["instances"]) == 16
    assert receipt["volatile"]["network_attempts"] == 0
    assert receipt["volatile"]["truth_source"] == "golden test"
    assert pinned["headline"]["candidate_vs_baseline"] == "NULL_NO_HEADROOM"


def test_wrong_truth_changes_the_digest(receipt):
    """A truth file that disagreed with the real truth would not reproduce the digest."""
    flipped = copy.deepcopy(STORE.documents["ic_fixture_set.json"])
    for case in flipped["cases"]:
        if case["case_id"] == "fixture-run/000":
            assert case["truth"]["state"] == "FINDINGS"
            case["truth"] = {"state": "NO_MATERIAL_DEVIATION", "defects": []}
    flipped["set_digest"] = golden_truth.seal(flipped)
    wrong = golden_truth.GoldenTruth({"ic_fixture_set.json": flipped})
    other = staging.run_staging(seed=0, timestamp=staging.DEFAULT_TIMESTAMP,
                                truth_for=wrong.truth_for, truth_source="wrong")
    assert other["pinned_digest"] != receipt["pinned_digest"]


def test_the_source_of_truth_does_not_enter_the_digest(receipt):
    again = staging.run_staging(seed=0, timestamp=staging.DEFAULT_TIMESTAMP,
                                truth_for=STORE.truth_for, truth_source="another label")
    assert again["pinned_digest"] == receipt["pinned_digest"]


def test_other_seeds_have_no_published_truth():
    with pytest.raises(golden_truth.GoldenTruthMissing):
        staging.run_staging(seed=1, timestamp=staging.DEFAULT_TIMESTAMP,
                            truth_for=STORE.truth_for)


def test_cli_with_golden_truth_and_another_seed_fails_cleanly(tmp_path, capsys):
    assert staging.main(["--out", str(tmp_path / "o"), "--seed", "1", "--truth", "golden"]) == 1
    err = capsys.readouterr().err
    assert "STAGING RUN FAILED: NO_PUBLISHED_TRUTH_FOR_SEED_1" in err
    assert "Traceback" not in err


def test_digest_binds_state_and_defect_codes_not_severity_or_required_refs(receipt):
    """Measured: what the validator digest does and does not pin of the truth."""
    def rerun(edit):
        doc = copy.deepcopy(STORE.documents["ic_fixture_set.json"])
        for case in doc["cases"]:
            for defect in case["truth"]["defects"]:
                edit(defect)
        doc["set_digest"] = golden_truth.seal(doc)
        store = golden_truth.GoldenTruth({"ic_fixture_set.json": doc})
        return staging.run_staging(seed=0, timestamp=staging.DEFAULT_TIMESTAMP,
                                   truth_for=store.truth_for)["pinned_digest"]

    assert rerun(lambda d: d.update(severity="LOW")) == receipt["pinned_digest"]
    assert rerun(lambda d: d.update(required_refs=[])) == receipt["pinned_digest"]
    assert rerun(lambda d: d.update(code="OTHER_CODE")) != receipt["pinned_digest"]


def test_the_verifier_check_passes_from_published_truth_alone():
    """The real default validator function, with the plan tool treated as absent."""
    doc = json.loads((ROOT / "attestation/SN87_TESTNET_ATTESTATION_02.json").read_text())

    def plan_absent():
        raise va.PrivateUnavailable(va.PLAN_REASON)

    report = va.verify(doc, client=None, plan_digest_fn=plan_absent)
    assert report["integrity"]["verdict"] == va.PASS
    for run in report["runs"]:
        assert run["checks"]["validator"]["verdict"] == va.PASS
        assert run["checks"]["plan"]["verdict"] == va.UNVERIFIED
        assert va.PLAN_REASON in run["checks"]["plan"]["detail"]
    assert report["scoring"]["tally"][va.FAIL] == 0


def test_the_verifier_check_fails_when_the_attested_digest_is_wrong():
    doc = json.loads((ROOT / "attestation/SN87_TESTNET_ATTESTATION_02.json").read_text())
    doc["runs"][0]["validator_pinned_digest"] = "sha256:" + "00" * 32
    report = va.verify(doc, client=None, plan_digest_fn=lambda: doc["runs"][0]["plan_digest"])
    checks = [r["checks"]["validator"]["verdict"] for r in report["runs"]]
    assert checks[0] == va.FAIL and set(checks[1:]) == {va.PASS}
    assert report["verdict"] == va.FAIL


def test_the_verifier_check_is_unverified_for_a_seed_with_no_published_truth():
    doc = json.loads((ROOT / "attestation/SN87_TESTNET_ATTESTATION_02.json").read_text())
    doc["runs"][0]["validator_seed"] = 3
    report = va.verify(doc, client=None, plan_digest_fn=lambda: doc["runs"][0]["plan_digest"])
    first = report["runs"][0]["checks"]["validator"]
    assert first["verdict"] == va.UNVERIFIED and va.TRUTH_REASON in first["detail"]
    assert all(r["checks"]["validator"]["verdict"] == va.PASS for r in report["runs"][1:])
