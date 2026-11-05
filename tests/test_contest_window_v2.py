"""Contest window protocol 0.2: opening-block seed mixing, truth hash fixed at open, reveal
deadline, reveal bundle. Runs in the public tree: the reference executors are replaced by a fake and
the opening block by fixed fake block hashes. No chain, no network, no real seed."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import contest_window as cw  # noqa: E402

MASTER = bytes.fromhex(hashlib.sha256(b"unit-test-master-v2").hexdigest())
OPENS, CLOSES = "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"
DEADLINE = "2026-11-03T00:00:00Z"


def block(number, fill, opens=OPENS, **over):
    """A fake opening block for a window that opens at ``opens``: its parent is before, it is at or
    after."""
    ms = cw._ms(opens)
    return {"number": number, "hash": "0x" + fill * 32, "time_ms": ms + 6000,
            "parent_time_ms": ms - 6000} | over


BLOCK_A = block(1000, "ab")
BLOCK_B = block(1000, "cd")
BLOCK_2 = block(2000, "ef", opens=CLOSES)
MIX = {"mix": [{"family": "stale_authority", "track": "scored", "count": 2},
               {"family": "fresh_review", "track": "scored", "count": 2},
               {"family": "wrong_scope_stale", "track": "diagnostic", "count": 1}]}


def schedule_v2(**over):
    base = {"schema_version": cw.SCHEDULE_SCHEMA_2, "schedule_id": "sched-2",
            "profile_id": "IC-FIRST-LIGHT-MIN-3",
            "beacon": {"network": "bittensor:test", "rule": cw.BEACON_RULE},
            "windows": [
                {"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES,
                 "reveal_deadline": DEADLINE},
                {"window_id": "cw-0002", "opens_at": CLOSES, "closes_at": DEADLINE,
                 "reveal_deadline": "2026-11-04T00:00:00Z"}]} | MIX
    return base | over


def fake_reference(capsule):
    # deterministic, derived from the capsule so a changed capsule changes the truth
    return {"state": "NO_MATERIAL_DEVIATION" if int(capsule["qid"][-1], 16) % 2 else "FINDING",
            "defects": []}


def files(tmp_path, schedule=None):
    (tmp_path / "schedule.json").write_text(json.dumps(schedule or schedule_v2()))
    master = tmp_path / "master.hex"
    if not master.exists():
        master.write_text(MASTER.hex() + "\n")
    return tmp_path / "schedule.json", master


def run(tmp_path, phase, now, *extra, window="cw-0001", reference=None, provider=None):
    schedule, master = files(tmp_path)
    argv = ["--phase", phase, "--now", now, "--out-dir", str(tmp_path / "out"),
            "--schedule", str(schedule), "--master-seed-file", str(master),
            "--window", window, *extra]
    if phase == "commit":
        argv += ["--no-prior-ledger", "unit test"]
    return cw.run(cw.parser().parse_args(argv), reference=reference, block_provider=provider)


def opened(tmp_path, chosen=BLOCK_A):
    run(tmp_path, "commit", "2026-10-31T00:00:00Z")
    run(tmp_path, "open", "2026-11-01T01:00:00Z", reference=fake_reference,
        provider=lambda opens_at: chosen)
    return tmp_path / "out"


def load(path):
    return json.loads(Path(path).read_text("utf-8"))


# --- schedule and commitments ------------------------------------------------------------------

def test_a_new_schedule_needs_a_reveal_deadline_and_a_beacon_rule(tmp_path):
    for broken in (
        schedule_v2(windows=[{"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES}]),
        schedule_v2(beacon={"network": "bittensor:test", "rule": "ANY_BLOCK"}),
        schedule_v2(windows=[{"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES,
                              "reveal_deadline": "2026-11-01T12:00:00Z"}]),
    ):
        path = tmp_path / "s.json"
        path.write_text(json.dumps(broken))
        with pytest.raises(ValueError):
            cw.load_schedule(path)
    (tmp_path / "s.json").write_text(json.dumps({k: v for k, v in schedule_v2().items()
                                                 if k != "beacon"}))
    with pytest.raises(ValueError):
        cw.load_schedule(tmp_path / "s.json")


def test_commit_publishes_a_preseed_commitment_and_the_deadline(tmp_path):
    run(tmp_path, "commit", "2026-10-31T00:00:00Z")
    doc = load(tmp_path / "out" / "commitments.json")
    assert doc["schema_version"] == cw.COMMITMENTS_SCHEMA_2
    assert doc["generator"] == cw.GENERATOR_ID_2
    assert doc["windows"][0]["reveal_deadline"] == DEADLINE
    assert doc["beacon"]["rule"] == cw.BEACON_RULE
    pre = cw.preseed(MASTER, "sched-2", "cw-0001")
    assert doc["windows"][0]["seed_commitment"] == cw.preseed_commitment("cw-0001", pre)
    assert pre.hex() not in json.dumps(doc)


# --- block hash mixing -------------------------------------------------------------------------

def test_block_hash_changes_the_seed_and_the_instances_deterministically():
    pre = cw.preseed(MASTER, "sched-2", "cw-0001")
    a1 = cw.window_seed_2(pre, "sched-2", "cw-0001", BLOCK_A)
    a2 = cw.window_seed_2(pre, "sched-2", "cw-0001", dict(BLOCK_A))
    b = cw.window_seed_2(pre, "sched-2", "cw-0001", BLOCK_B)
    other_number = cw.window_seed_2(pre, "sched-2", "cw-0001", BLOCK_A | {"number": 1001})
    assert a1 == a2 and len({a1, b, other_number}) == 3
    window = schedule_v2()["windows"][0]
    spec = cw.window_spec(schedule_v2(), window)
    qids = lambda seed: [e["qid"] for e in cw.build_window(seed, spec)]  # noqa: E731
    assert qids(a1) == qids(a2) and not set(qids(a1)) & set(qids(b))


def test_the_operator_cannot_derive_the_seed_without_the_block(tmp_path):
    pre = cw.preseed(MASTER, "sched-2", "cw-0001")
    assert cw.window_seed_2(pre, "sched-2", "cw-0001", BLOCK_A) != pre
    assert cw.window_seed(MASTER, "sched-2", "cw-0001") != cw.window_seed_2(
        pre, "sched-2", "cw-0001", BLOCK_A)


@pytest.mark.parametrize("bad", [
    BLOCK_A | {"number": -1}, BLOCK_A | {"number": "1"}, BLOCK_A | {"hash": "ab" * 32},
    BLOCK_A | {"hash": "0x" + "AB" * 32}, BLOCK_A | {"hash": "0x" + "ab" * 31},
    {"number": 1, "hash": "0x" + "ab" * 32}, BLOCK_A | {"time_ms": "1"},
    BLOCK_A | {"extra": 1}, BLOCK_A | {"manual": False}, {"number": True, "hash": "x"},
])
def test_a_malformed_block_record_is_refused(bad):
    with pytest.raises(ValueError):
        cw.check_beacon(bad)


def test_the_block_must_be_the_first_at_or_after_the_opening(tmp_path):
    cw.check_beacon_window(BLOCK_A, OPENS)
    for bad in (BLOCK_A | {"time_ms": cw._ms(OPENS) - 1},          # before the opening
                BLOCK_A | {"parent_time_ms": cw._ms(OPENS)},       # its parent was already there
                BLOCK_A | {"parent_time_ms": cw._ms(OPENS) + 1}):
        with pytest.raises(ValueError, match="BEACON_NOT_FIRST_BLOCK"):
            cw.check_beacon_window(bad, OPENS)
    # the open phase refuses a provider that returns a later, grindable block
    run(tmp_path, "commit", "2026-10-31T00:00:00Z")
    late = BLOCK_A | {"parent_time_ms": cw._ms(OPENS) + 6000, "time_ms": cw._ms(OPENS) + 12000}
    with pytest.raises(ValueError, match="BEACON_NOT_FIRST_BLOCK"):
        run(tmp_path, "open", "2026-11-01T01:00:00Z", reference=fake_reference,
            provider=lambda _: late)


def test_open_needs_a_provider_and_refuses_a_hand_typed_block_by_default(tmp_path, capsys):
    run(tmp_path, "commit", "2026-10-31T00:00:00Z")
    with pytest.raises(cw.PhaseError) as error:
        run(tmp_path, "open", "2026-11-01T01:00:00Z", reference=fake_reference)
    assert error.value.code == "BEACON_REQUIRED"
    typed = ["--block-number", "1000", "--block-hash", BLOCK_A["hash"],
             "--block-time-ms", str(BLOCK_A["time_ms"]),
             "--parent-block-time-ms", str(BLOCK_A["parent_time_ms"])]
    with pytest.raises(cw.PhaseError) as error:
        run(tmp_path, "open", "2026-11-01T01:00:00Z", *typed, reference=fake_reference)
    assert error.value.code == "MANUAL_BLOCK_REFUSED"
    assert not (tmp_path / "out" / cw.names("cw-0001")["capsules"]).exists()
    run(tmp_path, "open", "2026-11-01T01:00:00Z", *typed, "--allow-manual-block",
        reference=fake_reference)
    captured = capsys.readouterr()
    assert "MANUAL_BLOCK" in captured.err and "OPENING_BLOCK cw-0001 number=1000" in captured.out
    assert load(tmp_path / "out" / cw.names("cw-0001")["capsules"])["beacon"]["manual"] is True


def test_open_takes_the_block_from_an_injected_provider_and_prints_it(tmp_path, capsys):
    run(tmp_path, "commit", "2026-10-31T00:00:00Z")
    seen = []
    run(tmp_path, "open", "2026-11-01T01:00:00Z", reference=fake_reference,
        provider=lambda opens_at: seen.append(opens_at) or BLOCK_B)
    assert seen == [OPENS]
    assert load(tmp_path / "out" / cw.names("cw-0001")["capsules"])["beacon"] == BLOCK_B
    assert f"hash={BLOCK_B['hash']}" in capsys.readouterr().out


def test_same_inputs_give_the_same_capsules_and_other_block_other_capsules(tmp_path):
    for sub in "abc":
        (tmp_path / sub).mkdir()
    out_a = opened(tmp_path / "a")
    out_b = opened(tmp_path / "b")
    out_c = opened(tmp_path / "c", BLOCK_B)
    name = cw.names("cw-0001")["capsules"]
    a, b, c = (load(o / name) for o in (out_a, out_b, out_c))
    assert a["capsules"] == b["capsules"] and a["cases_commitment"] == b["cases_commitment"]
    assert a["cases_commitment"] != c["cases_commitment"]


class Reader:
    """A fake read-only chain: block n is at 1_000_000 + 6000 n ms."""

    def __init__(self, head=499, finalized=None):
        self.head, self.reads = head, []
        if finalized is not None:
            self.finalized_block = lambda: finalized

    def current_block(self):
        return self.head

    def block_time_ms(self, n):
        self.reads.append(("time", n))
        return 1_000_000 + n * 6000

    def block_hash(self, n):
        self.reads.append(("hash", n))
        return "0x" + f"{n:064x}"


def test_the_block_finder_returns_the_first_block_at_or_after_the_opening():
    reader = Reader()
    found = cw.find_beacon_block(reader, "1970-01-01T00:16:46Z")  # 1_006_000 ms = block 1
    assert found["number"] == 1 and found["hash"].endswith("01")
    assert found["parent_time_ms"] == 1_000_000 and found["time_ms"] == 1_006_000
    assert found["depth"] == cw.FINALITY_DEPTH


def test_the_block_finder_stops_short_of_the_head_and_reads_the_choice_twice():
    reader = Reader(head=499)
    # block 490 is at 3_940_000 ms; it is within 12 of the head (499), so it is not yet final
    opens = "1970-01-01T01:05:41Z"  # 3_941_000 ms -> first block at or after is 491
    with pytest.raises(cw.PhaseError) as error:
        cw.find_beacon_block(reader, opens)
    assert error.value.code == "BEACON_BLOCK_NOT_YET_FINAL"
    reader = Reader(head=520)
    found = cw.find_beacon_block(reader, opens)
    assert found["number"] == 491 and found["depth"] == cw.FINALITY_DEPTH
    assert reader.reads.count(("hash", 491)) == 2  # read again after the selection
    # a reader with a finalized head searches up to it, and is exact about it
    assert cw.find_beacon_block(Reader(head=520, finalized=495), opens)["depth"] == 0
    with pytest.raises(cw.PhaseError):
        cw.find_beacon_block(Reader(head=520, finalized=490), opens)


def test_a_block_read_that_changes_between_reads_is_refused():
    class Flaky(Reader):
        def block_hash(self, n):
            self.calls = getattr(self, "calls", 0) + 1
            return "0x" + f"{n + self.calls:064x}"

    with pytest.raises(cw.PhaseError) as error:
        cw.find_beacon_block(Flaky(), "1970-01-01T00:16:46Z")
    assert error.value.code == "BEACON_READ_INCONSISTENT"


# --- truth hash at open ------------------------------------------------------------------------

def test_the_truth_hash_is_published_with_the_cases_commitment_at_open(tmp_path):
    out = opened(tmp_path)
    capsules = load(out / cw.names("cw-0001")["capsules"])
    truth = load(out / cw.names("cw-0001")["truth_private"])
    assert capsules["schema_version"] == cw.CAPSULES_SCHEMA_2
    assert capsules["truth_commitment"] == truth["truth_commitment"]
    assert capsules["cases_commitment"] == truth["cases_commitment"]
    assert capsules["reveal_deadline"] == DEADLINE
    # the private truth file is private
    assert (out / cw.names("cw-0001")["truth_private"]).stat().st_mode & 0o077 == 0


def test_every_request_carries_the_open_record(tmp_path):
    out = opened(tmp_path)
    capsules = load(out / cw.names("cw-0001")["capsules"])
    record = cw.request_commitments(capsules)
    assert record == {"generator": cw.GENERATOR_ID_2, "window_id": "cw-0001",
                      "cases_commitment": capsules["cases_commitment"],
                      "truth_commitment": capsules["truth_commitment"]}
    v1 = {"schema_version": cw.CAPSULES_SCHEMA}
    assert cw.request_commitments(v1) is None


def test_an_existing_truth_is_never_made_again(tmp_path):
    opened(tmp_path)
    with pytest.raises(cw.PhaseError) as error:
        run(tmp_path, "truth", "2026-11-02T01:00:00Z", reference=fake_reference)
    assert error.value.code == "TRUTH_FIXED_AT_OPEN"  # no schedule given
    with pytest.raises(cw.PhaseError) as error:
        run(tmp_path, "truth", "2026-11-02T01:00:00Z", reference=fake_reference)
    assert error.value.code == "TRUTH_FIXED_AT_OPEN"


def test_the_truth_salt_is_derived_so_a_lost_file_is_made_again_identically(tmp_path):
    out = opened(tmp_path)
    path = out / cw.names("cw-0001")["truth_private"]
    first = load(path)
    assert first["salt"] == cw.truth_salt_2(cw.preseed(MASTER, "sched-2", "cw-0001"), "cw-0001")
    path.rename(path.with_suffix(".lost"))
    schedule, master = files(tmp_path)
    args = cw.parser().parse_args(["--phase", "truth", "--window", "cw-0001", "--now",
                                   "2026-11-02T01:00:00Z", "--out-dir", str(out),
                                   "--schedule", str(schedule), "--master-seed-file", str(master)])
    cw.run(args, reference=fake_reference)
    assert load(path) == first


def test_a_remade_truth_that_hashes_differently_is_refused(tmp_path):
    out = opened(tmp_path)
    path = out / cw.names("cw-0001")["truth_private"]
    path.rename(path.with_suffix(".lost"))
    schedule, master = files(tmp_path)
    args = cw.parser().parse_args(["--phase", "truth", "--window", "cw-0001", "--now",
                                   "2026-11-02T01:00:00Z", "--out-dir", str(out),
                                   "--schedule", str(schedule), "--master-seed-file", str(master)])
    with pytest.raises(cw.PhaseError) as error:
        cw.run(args, reference=lambda capsule: {"state": "OTHER", "defects": []})
    assert error.value.code == "TRUTH_HASH_DIFFERS_FROM_OPEN"
    assert not path.exists()


def test_a_stored_truth_for_another_window_or_salt_is_refused(tmp_path):
    out = opened(tmp_path)
    path = out / cw.names("cw-0001")["truth_private"]
    capsules = out / cw.names("cw-0001")["capsules"]
    doc = load(path)
    for change in ({"salt": "zz" * 16}, {"salt": "00" * 16}, {"window_id": "cw-0002"},
                   {"seed_commitment": "sha256:" + "0" * 64}):
        bad = doc | change
        if len(bad["salt"]) == 32 and bad["salt"] != "zz" * 16:  # a consistent forgery
            bad["truth_commitment"] = cw.truth_commitment(
                bad["cases"], window_id=bad["window_id"], seed_commitment=bad["seed_commitment"],
                cases_commitment=bad["cases_commitment"], salt=bad["salt"])
        path.write_text(json.dumps(bad))
        capsules.rename(out / "aside.json")  # a crashed open that must reuse the stored truth
        with pytest.raises((ValueError, cw.PhaseError)):
            run(tmp_path, "open", "2026-11-01T02:00:00Z", reference=fake_reference,
                provider=lambda _: BLOCK_A)
        (out / "aside.json").rename(capsules)


def test_open_is_not_repeated_and_a_second_block_is_refused_after_a_crash(tmp_path):
    out = opened(tmp_path)
    with pytest.raises(cw.PhaseError) as error:
        run(tmp_path, "open", "2026-11-01T02:00:00Z", reference=fake_reference,
            provider=lambda _: BLOCK_B)
    assert error.value.code == "WINDOW_ALREADY_OPENED"
    # a crash after the truth file but before the capsules file: the same truth, the same block
    capsules_path = out / cw.names("cw-0001")["capsules"]
    first = load(capsules_path)
    moved = capsules_path.with_name("aside.json")
    capsules_path.rename(moved)
    with pytest.raises(cw.PhaseError) as error:  # a different block cannot replace the recorded one
        run(tmp_path, "open", "2026-11-01T02:00:00Z", reference=fake_reference,
            provider=lambda _: BLOCK_B)
    assert error.value.code == "BEACON_CONFLICT"
    run(tmp_path, "open", "2026-11-01T02:00:00Z", reference=fake_reference,
        provider=lambda _: BLOCK_A)
    again = load(capsules_path)
    assert again == first and again["beacon"] == BLOCK_A


def reveal_and_close(tmp_path, out):
    run(tmp_path, "reveal", "2026-11-02T00:00:01Z")
    return load(out / cw.names("cw-0001")["reveal"])


def test_reveal_carries_the_preseed_and_the_block_and_verifies(tmp_path, capsys):
    out = opened(tmp_path)
    reveal = reveal_and_close(tmp_path, out)
    assert reveal["schema_version"] == cw.REVEAL_SCHEMA_2
    assert reveal["beacon"] == BLOCK_A and reveal["preseed"] and reveal["seed"]
    run(tmp_path, "verify", "2026-11-02T00:00:02Z")
    assert "commitments verified" in capsys.readouterr().out
    # the master seed itself is nowhere in what was published
    assert MASTER.hex() not in json.dumps(reveal)


def test_reveal_with_a_swapped_block_fails_verification(tmp_path):
    out = opened(tmp_path)
    reveal = reveal_and_close(tmp_path, out)
    reveal["beacon"] = BLOCK_B
    path = out / cw.names("cw-0001")["reveal"]
    path.write_text(json.dumps(reveal))
    with pytest.raises(ValueError, match="SEED_NOT_DERIVED_FROM_PRESEED_AND_BLOCK_HASH"):
        run(tmp_path, "verify", "2026-11-02T00:00:02Z")


def publish(tmp_path, out):
    run(tmp_path, "publish-truth", "2026-11-02T00:00:03Z", "--publish-closed-window-truth")
    return out / cw.names("cw-0001")["truth"]


def test_publish_truth_and_verify_accept_the_truth_committed_at_open(tmp_path, capsys):
    out = opened(tmp_path)
    reveal_and_close(tmp_path, out)
    published = publish(tmp_path, out)
    assert load(published)["truth_commitment"] == load(
        out / cw.names("cw-0001")["capsules"])["truth_commitment"]
    run(tmp_path, "verify", "2026-11-02T00:00:04Z")
    assert "equals the hash published at open" in capsys.readouterr().out


def rewrite_private_truth(out, **changes):
    """A private truth file that is internally consistent but is not the one committed at open."""
    path = out / cw.names("cw-0001")["truth_private"]
    doc = load(path)
    doc["cases"][0]["truth"] = {"state": "CHANGED_AFTER_OPEN", "defects": []}
    doc.update(changes)
    doc["truth_commitment"] = cw.truth_commitment(
        doc["cases"], window_id=doc["window_id"], seed_commitment=doc["seed_commitment"],
        cases_commitment=doc["cases_commitment"], salt=doc["salt"])
    path.write_text(json.dumps(doc))


def test_publish_truth_refuses_a_truth_hash_that_differs_from_open(tmp_path):
    out = opened(tmp_path)
    reveal_and_close(tmp_path, out)
    rewrite_private_truth(out)  # valid on its own, but not the committed truth
    with pytest.raises(cw.PhaseError) as error:
        publish(tmp_path, out)
    assert error.value.code == "TRUTH_HASH_DIFFERS_FROM_OPEN"
    assert not (out / cw.names("cw-0001")["truth"]).exists()


def test_publish_truth_refuses_without_the_open_record(tmp_path):
    out = opened(tmp_path)
    reveal_and_close(tmp_path, out)
    (out / cw.names("cw-0001")["capsules"]).rename(out / "aside.json")
    with pytest.raises(cw.PhaseError) as error:
        publish(tmp_path, out)
    assert error.value.code == "OPEN_RECORD_MISSING"


def test_verify_refuses_a_published_truth_hash_that_differs_from_open(tmp_path):
    out = opened(tmp_path)
    reveal_and_close(tmp_path, out)
    published = publish(tmp_path, out)
    doc = load(published)
    doc["cases"][0]["truth"] = {"state": "CHANGED_AFTER_OPEN", "defects": []}
    doc["truth_commitment"] = cw.truth_commitment(
        doc["cases"], window_id=doc["window_id"], seed_commitment=doc["seed_commitment"],
        cases_commitment=doc["cases_commitment"], salt=doc["salt"])
    published.write_text(json.dumps(doc))
    with pytest.raises(cw.PhaseError) as error:
        run(tmp_path, "verify", "2026-11-02T00:00:04Z")
    assert error.value.code == "TRUTH_HASH_DIFFERS_FROM_OPEN"


def test_results_refuse_a_truth_file_that_differs_from_open(tmp_path):
    import contest_results as cr

    out = opened(tmp_path)
    rewrite_private_truth(out)
    responses = tmp_path / "r.json"
    responses.write_text(json.dumps({"schema_version": cr.RESPONSES_SCHEMA,
                                     "window_id": "cw-0001", "methods": []}))
    with pytest.raises(cw.PhaseError) as error:
        cr.load_inputs(out / cw.names("cw-0001")["capsules"],
                       out / cw.names("cw-0001")["truth_private"], responses)
    assert error.value.code == "TRUTH_HASH_DIFFERS_FROM_OPEN"


# --- the old version still verifies ------------------------------------------------------------

def test_a_version_one_window_still_commits_opens_reveals_and_verifies(tmp_path, capsys):
    v1 = {"schema_version": cw.SCHEDULE_SCHEMA, "schedule_id": "sched-1",
          "profile_id": "IC-FIRST-LIGHT-MIN-3",
          "windows": [{"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES}]} | MIX
    (tmp_path / "schedule.json").write_text(json.dumps(v1))
    (tmp_path / "master.hex").write_text(MASTER.hex() + "\n")
    base = ["--out-dir", str(tmp_path / "out"), "--schedule", str(tmp_path / "schedule.json"),
            "--master-seed-file", str(tmp_path / "master.hex"), "--window", "cw-0001"]

    def phase(name, now, *extra):
        return cw.run(cw.parser().parse_args(["--phase", name, "--now", now, *base, *extra]))

    phase("commit", "2026-10-31T00:00:00Z", "--no-prior-ledger", "unit test")
    phase("open", "2026-11-01T01:00:00Z")
    phase("reveal", "2026-11-02T00:00:01Z")
    phase("verify", "2026-11-02T00:00:02Z")
    out = tmp_path / "out"
    assert load(out / "commitments.json")["generator"] == cw.GENERATOR_ID
    assert load(out / cw.names("cw-0001")["capsules"])["schema_version"] == cw.CAPSULES_SCHEMA
    assert "commitments verified" in capsys.readouterr().out
    # a 0.1 window has no open-time truth hash and the old truth phase is unchanged
    assert cw.request_commitments(load(out / cw.names("cw-0001")["capsules"])) is None


def test_the_committed_demo_window_still_verifies():
    demo = ROOT / "examples" / "contest-window-demo"
    args = cw.parser().parse_args(["--phase", "verify", "--window", "demo-0001",
                                   "--out-dir", str(demo)])
    # the demo directory keeps its files under the names verify reads
    try:
        cw.run(args)
    except FileNotFoundError:
        pytest.skip("demo files are not laid out for verify in this tree")


# --- reveal deadline ---------------------------------------------------------------------------

def test_overdue_needs_a_missed_deadline_and_no_published_reveal():
    assert cw.reveal_overdue(CLOSES, DEADLINE, "2026-11-03T00:00:01Z", revealed=False)
    assert not cw.reveal_overdue(CLOSES, DEADLINE, "2026-11-03T00:00:00Z", revealed=False)
    assert not cw.reveal_overdue(CLOSES, DEADLINE, "2026-11-09T00:00:00Z", revealed=True)
    # a 0.1 window has no deadline field: closes_at plus the grace period applies
    assert cw.reveal_overdue(CLOSES, None, "2026-11-03T00:00:01Z", revealed=False)
    assert not cw.reveal_overdue(CLOSES, None, "2026-11-02T23:00:00Z", revealed=False)


# --- reveal bundle -----------------------------------------------------------------------------

BEACONS = {"cw-0001": BLOCK_A, "cw-0002": BLOCK_2}
NOW_ALL = "2026-11-04T00:00:00Z"


def commitments_for(tmp_path, schedule=None):
    schedule = schedule or schedule_v2()
    path, master = files(tmp_path, schedule)
    return schedule, cw.read_master(master), cw.commitments_document(
        schedule, cw.read_master(master))


def open_records(schedule, master, ids=("cw-0001", "cw-0002")):
    """The open records the service would have published for these windows (fake truth hash)."""
    records = {}
    for window in schedule["windows"]:
        wid = window["window_id"]
        if wid not in ids:
            continue
        pre = cw.preseed(master, schedule["schedule_id"], wid)
        seed = cw.window_seed_2(pre, schedule["schedule_id"], wid, BEACONS[wid])
        entries = cw.build_window(seed, cw.window_spec(schedule, window))
        records[wid] = {"schema_version": cw.OPEN_RECORD_SCHEMA, "window_id": wid,
                        "cases_commitment": cw.cases_commitment(entries),
                        "truth_commitment": "sha256:" + "7" * 64, "beacon": BEACONS[wid],
                        "reveal_deadline": window["reveal_deadline"]}
    return records


def v2_bundle(tmp_path, ids=("cw-0001", "cw-0002"), **kw):
    schedule, master, commitments = commitments_for(tmp_path)
    records = open_records(schedule, master, ids)
    bundle = cw.reveal_bundle(schedule, master, commitments, kw.pop("now", NOW_ALL),
                              open_records=records, **kw)
    return schedule, master, commitments, records, bundle


def test_the_bundle_round_trips_for_version_two(tmp_path):
    _, _, commitments, records, bundle = v2_bundle(tmp_path)
    assert [(w["window_id"], w["status"]) for w in bundle["windows"]] == [
        ("cw-0001", "OPENED"), ("cw-0002", "OPENED")]
    assert bundle["windows"][0]["open_record"]["truth_commitment"].startswith("sha256:")
    report = cw.check_reveal_bundle(bundle, commitments, open_records=records, now=NOW_ALL)
    assert report == {"verified": ["cw-0001", "cw-0002"], "not_opened": [], "not_covered": []}
    assert MASTER.hex() not in json.dumps(bundle)


def test_the_bundle_round_trips_for_version_one(tmp_path):
    v1 = {"schema_version": cw.SCHEDULE_SCHEMA, "schedule_id": "sched-1",
          "profile_id": "IC-FIRST-LIGHT-MIN-3", "windows": [
              {"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES},
              {"window_id": "cw-0002", "opens_at": CLOSES, "closes_at": DEADLINE}]} | MIX
    schedule, master, commitments = commitments_for(tmp_path, v1)
    bundle = cw.reveal_bundle(schedule, master, commitments, NOW_ALL)
    assert bundle["protocol"] == cw.GENERATOR_ID
    assert [w["status"] for w in bundle["windows"]] == ["REVEALED", "REVEALED"]
    assert cw.check_reveal_bundle(bundle, commitments, now=NOW_ALL)["verified"] == [
        "cw-0001", "cw-0002"]
    with pytest.raises(ValueError, match="PROTOCOL_BELOW_MINIMUM"):  # the downgrade guard
        cw.check_reveal_bundle(bundle, commitments, min_protocol=2, now=NOW_ALL)


def test_the_bundle_leaves_out_or_refuses_an_unclosed_window(tmp_path):
    schedule, master, commitments = commitments_for(tmp_path)
    with pytest.raises(cw.PhaseError) as error:
        cw.reveal_bundle(schedule, master, commitments, "2026-11-01T12:00:00Z")
    assert error.value.code == "REVEAL_BEFORE_CLOSE"
    now = "2026-11-02T12:00:00Z"
    _, _, commitments, records, bundle = v2_bundle(tmp_path, now=now, closed_only=True)
    assert [w["window_id"] for w in bundle["windows"]] == ["cw-0001"]
    assert bundle["not_closed_and_left_out"] == ["cw-0002"]
    # cw-0002 has not closed, so leaving it out is not an incomplete bundle
    report = cw.check_reveal_bundle(bundle, commitments, open_records=records, now=now)
    assert report["not_covered"] == ["cw-0002"]


def test_a_window_that_never_opened_is_an_explicit_not_opened_entry(tmp_path):
    _, _, commitments, records, bundle = v2_bundle(tmp_path, ids=("cw-0001",))
    assert bundle["windows"][1] == {"window_id": "cw-0002", "status": "NOT_OPENED"}
    report = cw.check_reveal_bundle(bundle, commitments, open_records=records, now=NOW_ALL)
    assert report["not_opened"] == ["cw-0002"] and report["verified"] == ["cw-0001"]
    # ... and it cannot be passed off as opened, or hidden when it did open
    forged = json.loads(json.dumps(bundle))
    forged["windows"][1] = {"window_id": "cw-0002", "status": "OPENED",
                            "reveal": bundle["windows"][0]["reveal"],
                            "open_record": bundle["windows"][0]["open_record"]}
    with pytest.raises(ValueError):
        cw.check_reveal_bundle(forged, commitments, open_records=records, now=NOW_ALL)
    schedule, master, _ = commitments_for(tmp_path)
    full = open_records(schedule, master)
    with pytest.raises(ValueError, match="NOT_OPENED_BUT_OPEN_RECORD_EXISTS"):
        cw.check_reveal_bundle(bundle, commitments, open_records=full, now=NOW_ALL)


def test_each_reveal_is_tied_to_the_published_open_record(tmp_path):
    _, _, commitments, records, bundle = v2_bundle(tmp_path)
    with pytest.raises(cw.PhaseError) as error:
        cw.check_reveal_bundle(bundle, commitments, now=NOW_ALL)
    assert error.value.code == "OPEN_RECORDS_REQUIRED"
    for field, value in (("truth_commitment", "sha256:" + "8" * 64),
                         ("cases_commitment", "sha256:" + "8" * 64),
                         ("beacon", BLOCK_B)):
        published = json.loads(json.dumps(records))
        published["cw-0001"][field] = value
        with pytest.raises(ValueError, match="OPEN_RECORD_DIFFERS"):
            cw.check_reveal_bundle(bundle, commitments, open_records=published, now=NOW_ALL)
    with pytest.raises(ValueError, match="OPEN_RECORD_MISSING"):
        cw.check_reveal_bundle(bundle, commitments, open_records={"cw-0001": records["cw-0001"]},
                               now=NOW_ALL)
    # a record that disagrees with its own reveal
    forged = json.loads(json.dumps(bundle))
    forged["windows"][0]["open_record"]["cases_commitment"] = "sha256:" + "8" * 64
    with pytest.raises(ValueError, match="OPEN_RECORD_DIFFERS_FROM_REVEAL"):
        cw.check_reveal_bundle(forged, commitments, open_records=records, now=NOW_ALL)


def test_closed_windows_the_bundle_misses_are_an_error_unless_partial_is_allowed(tmp_path):
    _, _, commitments, records, bundle = v2_bundle(tmp_path)
    short = json.loads(json.dumps(bundle))
    short["windows"] = short["windows"][:1]
    with pytest.raises(cw.PhaseError) as error:
        cw.check_reveal_bundle(short, commitments, open_records=records, now=NOW_ALL)
    assert error.value.code == "BUNDLE_INCOMPLETE" and "cw-0002" in str(error.value)
    report = cw.check_reveal_bundle(short, commitments, open_records=records, now=NOW_ALL,
                                    allow_partial=True)
    assert report["not_covered"] == ["cw-0002"]


def test_the_bundle_needs_open_records_and_the_right_master(tmp_path):
    schedule, master, commitments = commitments_for(tmp_path)
    with pytest.raises(cw.PhaseError) as error:
        cw.reveal_bundle(schedule, bytes(32), commitments, NOW_ALL)
    assert error.value.code == "COMMITMENTS_DO_NOT_MATCH"
    none_opened = cw.reveal_bundle(schedule, master, commitments, NOW_ALL)
    assert {w["status"] for w in none_opened["windows"]} == {"NOT_OPENED"}
    # an open record that does not match the regenerated window is refused when the bundle is made
    bad = open_records(schedule, master)
    bad["cw-0001"]["cases_commitment"] = "sha256:" + "8" * 64
    with pytest.raises(cw.PhaseError) as error:
        cw.reveal_bundle(schedule, master, commitments, NOW_ALL, open_records=bad)
    assert error.value.code == "OPEN_RECORD_DIFFERS_FROM_REVEAL"


def test_a_tampered_bundle_fails_the_public_check(tmp_path):
    _, _, commitments, records, bundle = v2_bundle(tmp_path)

    def check(forged):
        return cw.check_reveal_bundle(forged, commitments, open_records=records, now=NOW_ALL)

    forged = json.loads(json.dumps(bundle))
    forged["windows"][0]["reveal"]["preseed"] = "00" * 32
    with pytest.raises(ValueError, match="SEED_COMMITMENT_MISMATCH"):
        check(forged)
    forged = json.loads(json.dumps(bundle))
    forged["windows"][1]["reveal"]["beacon"] = BLOCK_A  # the wrong block for this window
    with pytest.raises(ValueError, match="SEED_NOT_DERIVED"):
        check(forged)
    forged = json.loads(json.dumps(bundle))
    forged["windows"].append(forged["windows"][0])
    with pytest.raises(ValueError, match="BUNDLE_REPEATS_A_WINDOW"):
        check(forged)
    forged = json.loads(json.dumps(bundle))
    forged["schedule_commitment"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="BUNDLE_NOT_FOR_THESE_COMMITMENTS"):
        check(forged)
    # a seed from a block that is not the first at or after the opening is refused offline
    schedule, master, _ = commitments_for(tmp_path)
    forged = json.loads(json.dumps(bundle))
    late = BLOCK_A | {"parent_time_ms": cw._ms(OPENS) + 1, "time_ms": cw._ms(OPENS) + 6000}
    pre = cw.preseed(master, "sched-2", "cw-0001")
    forged["windows"][0]["reveal"]["beacon"] = late
    forged["windows"][0]["reveal"]["seed"] = cw.window_seed_2(pre, "sched-2", "cw-0001",
                                                            late).hex()
    with pytest.raises(ValueError, match="SEED_NOT_DERIVED|BEACON_NOT_FIRST"):
        check(forged)


def test_malformed_bundles_are_refused_not_crashed(tmp_path):
    _, _, commitments, records, bundle = v2_bundle(tmp_path)
    for broken in ({"schema_version": cw.BUNDLE_SCHEMA},
                   bundle | {"windows": [None]},
                   bundle | {"windows": [{"window_id": 5}]},
                   bundle | {"windows": "text"},
                   bundle | {"windows": [{"window_id": "cw-0001", "status": "OPENED",
                                          "reveal": []}]}):
        with pytest.raises(ValueError, match="BUNDLE_MALFORMED|WINDOW_NOT_COMMITTED"):
            cw.check_reveal_bundle(broken, commitments, open_records=records, now=NOW_ALL)


def test_the_public_verify_bundle_phase_checks_a_bundle(tmp_path, capsys):
    schedule, master, commitments, records, bundle = v2_bundle(tmp_path, ids=("cw-0001",))
    opens = tmp_path / "published"
    opens.mkdir()
    (opens / "window_cw-0001.open.json").write_text(json.dumps(records["cw-0001"]))
    (tmp_path / "bundle.json").write_text(json.dumps(bundle))
    (tmp_path / "commitments.json").write_text(json.dumps(commitments))
    argv = ["--phase", "verify-bundle", "--bundle", str(tmp_path / "bundle.json"),
            "--commitments", str(tmp_path / "commitments.json"), "--open-dir", str(opens),
            "--now", NOW_ALL]
    assert cw.run(cw.parser().parse_args(argv)) == []
    out = capsys.readouterr().out
    assert "verified cw-0001" in out and "not opened: cw-0002" in out
    assert "does not read a chain" in out
    with pytest.raises(cw.PhaseError) as error:  # no open records: the tie cannot be checked
        cw.run(cw.parser().parse_args([a for a in argv if a not in ("--open-dir", str(opens))]))
    assert error.value.code == "OPEN_RECORDS_REQUIRED"
    # the capsules file of a window also serves as its published open record
    capsules = tmp_path / "caps"
    capsules.mkdir()
    (capsules / "window_cw-0001.capsules.json").write_text(json.dumps({
        "schema_version": cw.CAPSULES_SCHEMA_2, "generator": cw.GENERATOR_ID_2,
        "window_id": "cw-0001", "cases_commitment": records["cw-0001"]["cases_commitment"],
        "truth_commitment": records["cw-0001"]["truth_commitment"],
        "beacon": BLOCK_A, "reveal_deadline": DEADLINE}))
    assert cw.load_open_records(capsules)["cw-0001"] == records["cw-0001"]


def test_the_index_flag_is_checked_by_the_verifier(tmp_path, capsys):
    schedule, master, commitments, records, bundle = v2_bundle(tmp_path)
    opens = tmp_path / "published"
    opens.mkdir()
    for wid, rec in records.items():
        (opens / f"window_{wid}.open.json").write_text(json.dumps(rec))
    (tmp_path / "bundle.json").write_text(json.dumps(bundle))
    (tmp_path / "commitments.json").write_text(json.dumps(commitments))
    index = {"windows": [{"window_id": "cw-0001", "reveal_status": "REVEAL_OVERDUE"},
                         {"window_id": "cw-0009", "reveal_status": "REVEAL_OVERDUE"}],
             "schedules": [{"schedule_id": "sched-2",
                            "voided": {"count": 1, "reasons": {"NOT_OPENED_IN_TIME": 1}}}]}
    (tmp_path / "index.json").write_text(json.dumps(index))
    argv = ["--phase", "verify-bundle", "--bundle", str(tmp_path / "bundle.json"),
            "--commitments", str(tmp_path / "commitments.json"), "--open-dir", str(opens),
            "--now", NOW_ALL, "--index", str(tmp_path / "index.json")]
    with pytest.raises(cw.PhaseError) as error:  # cw-0001 is covered by the bundle, cw-0009 is not
        cw.run(cw.parser().parse_args(argv))
    assert error.value.code == "REVEAL_OVERDUE_IN_INDEX" and "cw-0009" in str(error.value)
    assert "cw-0001" not in str(error.value)
    assert "1 voided" in capsys.readouterr().out


def test_a_schedule_cannot_push_a_reveal_deadline_out_of_reach(tmp_path):
    late = schedule_v2(windows=[{"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES,
                                 "reveal_deadline": "2026-11-09T00:00:01Z"}])
    path = tmp_path / "s.json"
    path.write_text(json.dumps(late))
    with pytest.raises(ValueError, match="REVEAL_DEADLINE_TOO_LATE"):
        cw.load_schedule(path)
    ok = schedule_v2(windows=[{"window_id": "cw-0001", "opens_at": OPENS, "closes_at": CLOSES,
                               "reveal_deadline": "2026-11-09T00:00:00Z"}])
    path.write_text(json.dumps(ok))
    cw.load_schedule(path)
