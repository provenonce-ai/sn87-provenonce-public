"""Contest window generator: commitments, derivation, phases and the disclosure guards.

Runs in the public tree. Only the test of the private `truth` phase needs the reference executors.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contest_window as cw  # noqa: E402

from sn87_provenonce import miners  # noqa: E402
from sn87_provenonce.baselines import BASELINES  # noqa: E402
from sn87_provenonce.institutional_v02 import contracts as ic  # noqa: E402
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable  # noqa: E402

DEMO = ROOT / "examples" / "contest-window-demo"
MASTER = bytes.fromhex(hashlib.sha256(b"unit-test-master").hexdigest())
OPENS, CLOSES = "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"
SCHEDULE = {
    "schema_version": cw.SCHEDULE_SCHEMA, "schedule_id": "sched-1",
    "profile_id": "IC-FIRST-LIGHT-MIN-3",
    "mix_preset": "messy",
    "windows": [{"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES},
                {"window_id": "cw-0002", "opens_at": CLOSES, "closes_at": "2026-11-03T00:00:00Z"}]}
TINY = {"mix": [{"family": "stale_authority", "track": "scored", "count": 2},
                {"family": "wrong_scope_stale", "track": "scored", "count": 2},
                {"family": "wrong_scope_clear", "track": "diagnostic", "count": 2},
                {"family": "incomplete", "track": "diagnostic", "count": 1},
                {"family": "fresh_review", "track": "scored", "count": 2}]}


def spec_for(schedule, window_id="cw-0001"):
    window = next(w for w in schedule["windows"] if w["window_id"] == window_id)
    return cw.window_spec(schedule, window)


def tiny():
    return SCHEDULE | TINY


@pytest.fixture(scope="module")
def built():
    spec = spec_for(tiny())
    return spec, cw.build_window(cw.window_seed(MASTER, "sched-1", "cw-0001"), spec)


def schedule_file(tmp_path, schedule=None):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(schedule or tiny()))
    return path


def master_file(tmp_path):
    path = tmp_path / "master.hex"
    if not path.exists():
        path.write_text(MASTER.hex() + "\n")
    return path


def command(tmp_path, phase, now, *extra, window="cw-0001"):
    out = tmp_path / "out"
    argv = ["--phase", phase, "--now", now, "--out-dir", str(out),
            "--schedule", str(schedule_file(tmp_path)),
            "--master-seed-file", str(master_file(tmp_path)), "--window", window, *extra]
    if phase == "commit" and not master_file(tmp_path).with_name(cw.LEDGER_NAME).exists():
        argv += ["--no-prior-ledger", "unit test: first commit"]
    return cw.run(cw.parser().parse_args(argv))


# --- primitives --------------------------------------------------------------------------------

def test_hkdf_expand_matches_rfc5869_case_1():
    prk = bytes.fromhex("077709362c2e32df0ddc3f0dc47bba6390b6c73bb50f9c3122ec844ad7c2b3e5")
    okm = cw.hkdf_expand(prk, bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42)
    assert okm.hex() == ("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
                         "34007208d5b887185865")


def test_framing_is_unambiguous():
    assert cw.frame(b"ab", b"c") != cw.frame(b"a", b"bc")
    assert cw.digest(b"d", "w", b"s") != cw.digest(b"d", "ws", b"")


def test_seed_commitment_binds_domain_window_and_seed():
    seed = cw.window_seed(MASTER, "sched-1", "cw-0001")
    c = cw.seed_commitment("cw-0001", seed)
    assert c == "sha256:" + hashlib.sha256(
        cw.frame(cw.COMMIT_DOMAIN, "cw-0001", seed)).hexdigest()
    assert c != cw.seed_commitment("cw-0002", seed)
    assert c != cw.seed_commitment("cw-0001", cw.window_seed(MASTER, "sched-1", "cw-0002"))
    assert cw.window_seed(MASTER, "sched-1", "cw-0001") != cw.window_seed(
        MASTER, "sched-1", "cw-0002")
    assert seed != MASTER and len(seed) == 32


# --- schedule and specification ----------------------------------------------------------------

def test_default_mix_is_the_sizing_profiles_assignment():
    spec = cw.window_spec(SCHEDULE | {"mix_preset": "profile"}, SCHEDULE["windows"][0])
    counts = {(m["family"], m["track"]): m["count"] for m in spec["mix"]}
    assert counts == {("stale_authority", "scored"): 16, ("fresh_review", "scored"): 8,
                      ("incomplete", "diagnostic"): 8}


def test_schedule_validation(tmp_path):
    def load(doc, **kw):
        path = tmp_path / "s.json"
        path.write_text(json.dumps(doc))
        return cw.load_schedule(path, **kw)

    assert load(tiny())["windows"]
    with pytest.raises(ValueError, match="DEMO_WINDOW_ID_RESERVED"):
        load(tiny() | {"windows": [dict(SCHEDULE["windows"][0], window_id="demo-0001")]})
    with pytest.raises(ValueError, match="demo schedules"):
        load(tiny(), allow_demo=True)
    overlap = [SCHEDULE["windows"][0], dict(SCHEDULE["windows"][1], opens_at=OPENS)]
    with pytest.raises(ValueError, match="overlap"):
        load(tiny() | {"windows": overlap})
    with pytest.raises(ValueError):
        load(tiny() | {"profile_id": "NOT-A-PROFILE"})
    with pytest.raises(ValueError, match="invalid mix"):
        cw.check_mix([{"family": "nonsense", "track": "scored", "count": 1}])


# --- derivation --------------------------------------------------------------------------------

def test_window_is_a_pure_function_of_seed_and_spec(built):
    spec, entries = built
    again = cw.build_window(cw.window_seed(MASTER, "sched-1", "cw-0001"), spec)
    assert cw.dumps(cw.capsules_document(spec, entries)) == cw.dumps(
        cw.capsules_document(spec, again))


def test_instances_are_fresh_across_windows_and_seeds(built):
    spec, entries = built
    other_window = cw.build_window(cw.window_seed(MASTER, "sched-1", "cw-0002"),
                                   spec_for(tiny(), "cw-0002"))
    other_master = cw.build_window(cw.window_seed(bytes(32), "sched-1", "cw-0001"), spec)

    def ids(window):
        found = set()
        for e in window:
            found |= {e["qid"], e["capsule"]["nonce"], e["capsule"]["pipeline_id"],
                      *(ev["event_id"] for ev in e["capsule"]["events"])}
        return found

    assert not ids(entries) & ids(other_window)
    assert not ids(entries) & ids(other_master)
    assert len({e["qid"] for e in entries}) == len(entries)


def test_mix_counts_and_order_hide_the_family(built):
    spec, entries = built
    got = {}
    for e in entries:
        got[(e["family"], e["track"])] = got.get((e["family"], e["track"]), 0) + 1
    assert got == {(m["family"], m["track"]): m["count"] for m in spec["mix"]}
    unshuffled = [(m["family"], m["track"]) for m in spec["mix"] for _ in range(m["count"])]
    assert [(e["family"], e["track"]) for e in entries] != unshuffled
    assert [e["position"] for e in entries] == list(range(len(entries)))


def test_capsules_validate_and_carry_the_window_time(built):
    spec, entries = built
    for e in entries:
        ic.validate_capsule(e["capsule"])
        assert e["capsule"]["timestamp"] == spec["opens_at"]


def test_miner_facing_document_leaks_nothing(built):
    spec, entries = built
    text = cw.dumps(cw.capsules_document(spec, entries))
    seed = cw.window_seed(MASTER, "sched-1", "cw-0001")
    for secret in (seed.hex(), MASTER.hex(), "stale_authority", "wrong_scope", "diagnostic",
                   "scored", '"truth"', '"family"', '"track"'):
        assert secret not in text, secret
    assert set(json.loads(text)) == {"schema_version", "window_id", "opens_at", "closes_at",
                                     "cases_commitment", "capsules"}


def test_wrong_scope_cases_overclaim_for_the_baseline_and_not_for_the_candidate(built):
    """The headroom the families exist for, shown with public code only (no truth needed)."""
    _, entries = built
    candidate = miners.for_class("IC-APPROVAL-APPLICABILITY")["approval_witness"]
    baseline = BASELINES["IC-APPROVAL-APPLICABILITY"]
    abstain = "INSUFFICIENT_EVIDENCE_ABSTAIN"
    seen = set()
    for e in entries:
        if not e["family"].startswith("wrong_scope"):
            continue
        assert e["wrong_scope_variant"]["dimension"] in cw.SCOPE_DIMENSIONS
        assert candidate(e["capsule"])["state"] == abstain
        naive = baseline(e["capsule"])["state"]
        assert naive == ("FINDINGS" if e["family"] == "wrong_scope_stale"
                         else "NO_MATERIAL_DEVIATION")
        seen.add(e["family"])
    assert seen == {"wrong_scope_stale", "wrong_scope_clear"}


def test_wrong_scope_variants_cover_all_three_dimensions():
    spec = spec_for(tiny() | {"mix": [{"family": "wrong_scope_clear", "track": "scored",
                                       "count": 48}]})
    entries = cw.build_window(cw.window_seed(MASTER, "sched-1", "cw-0001"), spec)
    assert {e["wrong_scope_variant"]["dimension"] for e in entries} == set(cw.SCOPE_DIMENSIONS)


# --- phases and guards -------------------------------------------------------------------------

def test_full_lifecycle_and_public_verification(tmp_path):
    out = tmp_path / "out"
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    command(tmp_path, "open", OPENS)
    (tmp_path / "out" / "window_cw-0001.cases.private.json").stat()
    command(tmp_path, "reveal", "2026-11-02T00:00:01Z")
    # A public reader needs only the public files.
    public = tmp_path / "public"
    public.mkdir()
    for name in ("commitments.json", "window_cw-0001.reveal.json", "window_cw-0001.capsules.json"):
        (public / name).write_bytes((out / name).read_bytes())
    args = cw.parser().parse_args(["--phase", "verify", "--window", "cw-0001",
                                   "--out-dir", str(public)])
    assert cw.run(args) == []
    private = oct((out / "window_cw-0001.cases.private.json").stat().st_mode & 0o777)
    assert private == "0o600"


def test_commit_is_refused_once_a_window_opened(tmp_path):
    with pytest.raises(cw.PhaseError, match="COMMIT_AFTER_OPEN"):
        command(tmp_path, "commit", OPENS)


def test_open_needs_the_commitments_and_they_must_match(tmp_path):
    with pytest.raises(cw.PhaseError, match="WINDOW_NOT_COMMITTED"):
        command(tmp_path, "open", OPENS)
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    master_file(tmp_path).write_text(bytes(32).hex() + "\n")  # another master seed
    with pytest.raises(cw.PhaseError, match="COMMITMENTS_DO_NOT_MATCH"):
        command(tmp_path, "open", OPENS)


def test_open_is_refused_after_close(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    with pytest.raises(cw.PhaseError, match="OPEN_AFTER_CLOSE"):
        command(tmp_path, "open", CLOSES)


def test_reveal_is_refused_until_the_window_closes(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    for now in (OPENS, "2026-11-01T23:59:59Z"):
        with pytest.raises(cw.PhaseError, match="REVEAL_BEFORE_CLOSE"):
            command(tmp_path, "reveal", now)
    assert not (tmp_path / "out" / "window_cw-0001.reveal.json").exists()
    command(tmp_path, "reveal", CLOSES)


def test_a_second_commit_over_the_same_windows_is_refused(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    with pytest.raises(cw.PhaseError, match="WINDOW_OR_SEED_REUSED"):
        command(tmp_path, "commit", "2026-10-30T00:00:00Z")


def test_truth_publication_guards(tmp_path):
    window = SCHEDULE["windows"][0]
    with pytest.raises(cw.PhaseError, match="TRUTH_PUBLICATION_BEFORE_CLOSE"):
        cw.guard("publish-truth", window, OPENS, revealed=True, publish_policy=True)
    with pytest.raises(cw.PhaseError, match="TRUTH_PUBLICATION_BEFORE_REVEAL"):
        cw.guard("publish-truth", window, CLOSES, revealed=False, publish_policy=True)
    with pytest.raises(cw.PhaseError, match="TRUTH_PUBLICATION_NOT_AUTHORIZED"):
        cw.guard("publish-truth", window, CLOSES, revealed=True, publish_policy=False)
    cw.guard("publish-truth", window, CLOSES, revealed=True, publish_policy=True)
    with pytest.raises(cw.PhaseError, match="RESULTS_BEFORE_CLOSE"):
        cw.guard("results", window, OPENS)


def fake_truth(tmp_path, wid="cw-0001"):
    """A private truth file for the tiny window, with hand-written truth and a fixed salt."""
    out = tmp_path / "out"
    commitments = json.loads((out / "commitments.json").read_text())
    capsules = json.loads((out / f"window_{wid}.capsules.json").read_text())
    spec = spec_for(tiny(), wid)
    rows = [{"position": e["position"], "qid": e["qid"], "family": e["family"],
             "track": e["track"], "wrong_scope_variant": e["wrong_scope_variant"],
             "capsule_commitment": e["capsule_commitment"], "truth": {"state": "X"},
             "reference_failure": None}
            for e in cw.build_window(cw.window_seed(MASTER, "sched-1", wid), spec)]
    row = next(w for w in commitments["windows"] if w["window_id"] == wid)
    document = cw.truth_document(wid, row["seed_commitment"], capsules["cases_commitment"],
                                 "ab" * 16, rows)
    (out / f"window_{wid}.truth.private.json").write_text(cw.dumps(document))
    return document


def test_publish_truth_never_writes_a_public_name_before_policy(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    command(tmp_path, "open", OPENS)
    command(tmp_path, "reveal", CLOSES)
    fake_truth(tmp_path)
    with pytest.raises(cw.PhaseError, match="TRUTH_PUBLICATION_NOT_AUTHORIZED"):
        command(tmp_path, "publish-truth", CLOSES)
    assert not (tmp_path / "out" / "window_cw-0001.truth.json").exists()
    command(tmp_path, "publish-truth", CLOSES, "--publish-closed-window-truth")
    published = json.loads((tmp_path / "out" / "window_cw-0001.truth.json").read_text())
    assert published["salt"] == "ab" * 16  # the salt is revealed only here
    cw.check_truth_document(published, json.loads(
        (tmp_path / "out" / "commitments.json").read_text()))


def test_publish_truth_checks_the_reveal_contents_not_its_existence(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    command(tmp_path, "open", OPENS)
    command(tmp_path, "reveal", CLOSES)
    fake_truth(tmp_path)
    reveal_path = tmp_path / "out" / "window_cw-0001.reveal.json"
    reveal = json.loads(reveal_path.read_text())
    reveal["seed"] = bytes(32).hex()
    reveal_path.write_text(json.dumps(reveal))
    with pytest.raises(ValueError, match="SEED_COMMITMENT_MISMATCH"):
        command(tmp_path, "publish-truth", CLOSES, "--publish-closed-window-truth")
    assert not (tmp_path / "out" / "window_cw-0001.truth.json").exists()


def test_open_has_a_lower_bound(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    with pytest.raises(cw.PhaseError, match="OPEN_BEFORE_WINDOW"):
        command(tmp_path, "open", "2026-10-31T00:00:00Z")


@pytest.mark.parametrize("bad", ["../x", "CW-1", "a/b", "cw 1", "", "x" * 60])
def test_window_argument_is_validated_before_it_reaches_a_file_name(tmp_path, bad):
    with pytest.raises(ValueError, match="invalid window id"):
        command(tmp_path, "open", OPENS, window=bad)


def test_cli_reports_a_refusal_with_exit_code_2(tmp_path, capsys):
    argv = ["--phase", "reveal", "--now", OPENS, "--out-dir", str(tmp_path / "o"),
            "--schedule", str(schedule_file(tmp_path)),
            "--master-seed-file", str(master_file(tmp_path)), "--window", "cw-0001"]
    assert cw.main(argv) == 2
    assert "REVEAL_BEFORE_CLOSE" in capsys.readouterr().err


# --- verification catches tampering ------------------------------------------------------------

def committed_pair(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    command(tmp_path, "reveal", CLOSES)
    out = tmp_path / "out"
    return (json.loads((out / "commitments.json").read_text()),
            json.loads((out / "window_cw-0001.reveal.json").read_text()))


def test_check_reveal_accepts_the_honest_pair_and_regenerates(tmp_path):
    commitments, reveal = committed_pair(tmp_path)
    assert len(cw.check_reveal(commitments, reveal)) == sum(m["count"] for m in TINY["mix"])


@pytest.mark.parametrize("tamper,error", [
    (lambda c, r: r.update(seed=bytes(32).hex()), "SEED_COMMITMENT_MISMATCH"),
    (lambda c, r: r["spec"]["mix"][0].update(count=3), "SPEC_COMMITMENT_MISMATCH"),
    (lambda c, r: r["spec"].update(closes_at="2026-11-02T00:00:01Z"), "SPEC_COMMITMENT_MISMATCH"),
    (lambda c, r: c["windows"][0].update(seed_commitment="sha256:" + "0" * 64),
     "SCHEDULE_COMMITMENT_MISMATCH"),
    (lambda c, r: r.update(window_id="cw-0009"), "WINDOW_NOT_COMMITTED"),
])
def test_check_reveal_rejects_tampering(tmp_path, tamper, error):
    commitments, reveal = committed_pair(tmp_path)
    tamper(commitments, reveal)
    with pytest.raises(ValueError, match=error):
        cw.check_reveal(commitments, reveal)


# --- truth is private --------------------------------------------------------------------------

def test_truth_phase_needs_the_private_executors_and_says_so(built):
    from conftest import executors_available
    if executors_available():
        pytest.skip("this tree has the reference executors")
    _, entries = built
    with pytest.raises(PrivateReferenceExecutorUnavailable):
        cw.derive_truth(entries)


def test_a_reference_that_raises_is_a_recorded_failure_not_a_retry(built):
    _, entries = built
    calls = []

    def flaky(capsule):
        calls.append(capsule["qid"])
        if len(calls) == 2:
            raise RuntimeError("boom")
        return {"state": "FINDINGS", "defects": []}

    rows = cw.derive_truth(entries, reference=flaky)
    assert len(calls) == len(entries)  # one call per instance, none repeated
    assert [r["reference_failure"] for r in rows].count("RuntimeError") == 1
    assert rows[1]["truth"] is None


@pytest.mark.requires_private_executors
def test_reference_truth_agrees_with_the_family_on_a_full_window(built):
    _, entries = built
    rows = cw.derive_truth(entries)
    expected = {"stale_authority": "FINDINGS", "fresh_review": "NO_MATERIAL_DEVIATION",
                "incomplete": "INSUFFICIENT_EVIDENCE_ABSTAIN",
                "wrong_scope_stale": "INSUFFICIENT_EVIDENCE_ABSTAIN",
                "wrong_scope_clear": "INSUFFICIENT_EVIDENCE_ABSTAIN"}
    assert all(r["reference_failure"] is None for r in rows)
    assert all(r["truth"]["state"] == expected[r["family"]] for r in rows)


# --- the committed demonstration window --------------------------------------------------------

def test_committed_demo_window_verifies_and_matches_its_truth():
    commitments = json.loads((DEMO / "commitments.json").read_text())
    reveal = json.loads((DEMO / "window_demo-0001.reveal.json").read_text())
    truth = json.loads((DEMO / "window_demo-0001.truth.json").read_text())
    entries = cw.check_reveal(commitments, reveal)
    assert [(e["qid"], e["family"], e["track"], e["capsule_commitment"]) for e in entries] == [
        (c["qid"], c["family"], c["track"], c["capsule_commitment"]) for c in truth["cases"]]
    cw.check_truth_document(truth, commitments)
    assert reveal["window_id"].startswith(cw.DEMO_PREFIX)


@pytest.mark.requires_private_executors
def test_committed_demo_truth_is_what_the_reference_executors_say():
    commitments = json.loads((DEMO / "commitments.json").read_text())
    reveal = json.loads((DEMO / "window_demo-0001.reveal.json").read_text())
    truth = json.loads((DEMO / "window_demo-0001.truth.json").read_text())
    rows = cw.derive_truth(cw.check_reveal(commitments, reveal))
    again = cw.truth_document("demo-0001", truth["seed_commitment"], truth["cases_commitment"],
                              truth["salt"], rows)
    assert cw.dumps(again) == cw.dumps(truth)


# --- hiding, salting and schedule binding ------------------------------------------------------

def test_spec_commitment_is_hiding_and_bound_to_the_seed():
    spec = spec_for(tiny())
    seed = cw.window_seed(MASTER, "sched-1", "cw-0001")
    c = cw.spec_commitment(spec, seed)
    assert c != cw.digest(cw.SPEC_DOMAIN, cw.canonical_bytes(spec))  # not a bare hash of the spec
    assert c != cw.spec_commitment(spec, bytes(32))
    # A guesser who tries candidate mixes without the seed cannot confirm one.
    other = dict(spec, mix=[{"family": "stale_authority", "track": "scored", "count": 2}])
    assert cw.spec_commitment(other, seed) != c


def test_truth_commitment_is_salted_and_bound_to_earlier_commitments():
    rows = [{"qid": "q1", "truth": {"state": "FINDINGS"}, "reference_failure": None}]
    kw = {"window_id": "w", "seed_commitment": "sha256:" + "1" * 64,
          "cases_commitment": "sha256:" + "2" * 64}
    a = cw.truth_commitment(rows, salt="00" * 16, **kw)
    assert a != cw.truth_commitment(rows, salt="01" * 16, **kw)
    assert a != cw.truth_commitment(rows, salt="00" * 16, **(kw | {"window_id": "x"}))
    assert a != cw.truth_commitment(rows, salt="00" * 16,
                                    **(kw | {"seed_commitment": "sha256:" + "3" * 64}))
    assert a != cw.truth_commitment(rows, salt="00" * 16,
                                    **(kw | {"cases_commitment": "sha256:" + "4" * 64}))
    # Same truth, no way to confirm a guess without the salt: only the salted form verifies.
    guess = cw.digest(cw.TRUTH_DOMAIN, cw.canonical_bytes([["q1", rows[0]["truth"], None]]))
    assert guess != a


def test_truth_document_must_match_the_published_commitments(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    command(tmp_path, "open", OPENS)
    document = fake_truth(tmp_path)
    commitments = json.loads((tmp_path / "out" / "commitments.json").read_text())
    cw.check_truth_document(document, commitments)
    other = dict(document, seed_commitment="sha256:" + "9" * 64)
    other["truth_commitment"] = cw.truth_commitment(
        other["cases"], window_id="cw-0001", seed_commitment=other["seed_commitment"],
        cases_commitment=other["cases_commitment"], salt=other["salt"])
    with pytest.raises(ValueError, match="TRUTH_NOT_BOUND_TO_PUBLISHED_COMMITMENT"):
        cw.check_truth_document(other, commitments)
    with pytest.raises(ValueError, match="TRUTH_COMMITMENT_MISMATCH"):
        cw.check_truth_document(dict(document, salt="cd" * 16))


def test_same_master_and_window_id_in_another_schedule_gives_other_instances():
    spec = spec_for(tiny())
    one = cw.build_window(cw.window_seed(MASTER, "sched-1", "cw-0001"), spec)
    two = cw.build_window(cw.window_seed(MASTER, "sched-2", "cw-0001"),
                          dict(spec, schedule_id="sched-2"))
    assert not {e["qid"] for e in one} & {e["qid"] for e in two}
    assert cw.window_seed(MASTER, "sched-1", "cw-0001") != cw.window_seed(
        MASTER, "sched-2", "cw-0001")


def test_reuse_ledger_is_on_by_default(tmp_path):
    argv = ["--phase", "commit", "--now", "2026-10-30T00:00:00Z", "--out-dir", str(tmp_path / "o"),
            "--schedule", str(schedule_file(tmp_path)),
            "--master-seed-file", str(master_file(tmp_path))]
    with pytest.raises(cw.PhaseError, match="PRIOR_LEDGER_REQUIRED"):
        cw.run(cw.parser().parse_args(argv))
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")  # first commit, with a stated reason
    ledger = json.loads(master_file(tmp_path).with_name(cw.LEDGER_NAME).read_text())
    assert len(ledger["entries"]) == len(SCHEDULE["windows"])
    # The ledger is now found next to the schedule: a second commit of the same windows is refused.
    again = [*argv[:5], str(tmp_path / "second"), *argv[6:]]
    with pytest.raises(cw.PhaseError, match="WINDOW_OR_SEED_REUSED"):
        cw.run(cw.parser().parse_args(again))
    assert not (tmp_path / "second" / "commitments.json").exists()


def test_commit_refuses_reuse_from_a_prior_commitments_file(tmp_path):
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    prior = tmp_path / "out" / "commitments.json"
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "schedule.json").write_text(json.dumps(tiny()))
    argv = ["--phase", "commit", "--now", "2026-10-30T00:00:00Z", "--out-dir", str(other / "o"),
            "--schedule", str(other / "schedule.json"), "--no-prior-ledger", "other directory",
            "--master-seed-file", str(master_file(tmp_path)), "--prior-commitments", str(prior)]
    with pytest.raises(cw.PhaseError, match="WINDOW_OR_SEED_REUSED"):
        cw.run(cw.parser().parse_args(argv))


def test_schedule_profile_must_be_for_the_generators_class(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(tiny() | {"profile_id": "GRA-W03-3"}))
    with pytest.raises(ValueError, match="PROFILE_CLASS_MISMATCH"):
        cw.load_schedule(path)


def test_truth_on_an_uncommitted_or_unopened_window_is_a_clean_refusal(tmp_path, capsys):
    with pytest.raises(cw.PhaseError, match="WINDOW_NOT_COMMITTED"):
        command(tmp_path, "truth", CLOSES)
    command(tmp_path, "commit", "2026-10-30T00:00:00Z")
    with pytest.raises(cw.PhaseError, match="WINDOW_NOT_OPENED"):
        command(tmp_path, "truth", CLOSES)
    with pytest.raises(cw.PhaseError, match="WINDOW_NOT_COMMITTED"):
        command(tmp_path, "truth", CLOSES, window="cw-0009")
    argv = ["--phase", "truth", "--out-dir", str(tmp_path / "none"), "--window", "cw-0001"]
    assert cw.main(argv) == 2 and "WINDOW_NOT_COMMITTED" in capsys.readouterr().err
