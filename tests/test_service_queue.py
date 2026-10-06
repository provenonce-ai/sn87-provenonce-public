"""The durable bounded queue: bound, idempotency, fencing, expiry, crash recovery."""

import json

import pytest

from sn87_provenonce.service import queue as q


def make(tmp_path, size=3, attempts=2):
    return q.WorkQueue.create(tmp_path / "queue", max_size=size, max_attempts=attempts)


def test_bound_refuses_and_duplicate_key_returns_existing(tmp_path):
    work = make(tmp_path, size=2)
    first = work.submit({"n": 1}, "k1")
    work.submit({"n": 2}, "k2")
    with pytest.raises(q.QueueFull):
        work.submit({"n": 3}, "k3")
    again = work.submit({"n": 1}, "k1")  # dedup is checked before the bound
    assert again.item_id == first.item_id and len(work.entries) == 2
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REUSED"):
        work.submit({"n": 9}, "k1")
    stats = work.stats()
    assert (stats["submitted"], stats["deduplicated"], stats["refused_full"]) == (2, 1, 1)


def test_bound_counts_outstanding_only(tmp_path):
    work = make(tmp_path, size=1)
    work.submit("a", "a")
    lease = work.lease("w", now=0, ttl=2)
    assert work.complete(lease, "ok", now=1).accepted
    work.submit("b", "b")  # the accepted item no longer occupies the bound


def test_fencing_rejects_a_late_worker_and_keeps_the_newer_result(tmp_path):
    work = make(tmp_path)
    work.submit("a", "a")
    old = work.lease("slow", now=0, ttl=2)
    assert work.expire(now=2) == [old.item_id]
    new = work.lease("fast", now=2, ttl=2)
    assert new.token > old.token
    assert work.complete(old, "late", now=3) == q.Completion(old.item_id, False, q.STALE)
    assert work.complete(new, "fresh", now=3).accepted
    assert work.complete(old, "late", now=3).reason == q.STALE
    assert work.complete(new, "twice", now=3).reason == q.DONE
    assert work.entries[new.item_id].result == "fresh"
    saved = json.loads((work.path / "accepted" / f"{new.item_id}.json").read_text())
    assert saved["result"] == "fresh" and saved["token"] == new.token


def test_expired_lease_cannot_complete_even_before_expire_runs(tmp_path):
    work = make(tmp_path)
    work.submit("a", "a")
    lease = work.lease("w", now=0, ttl=2)
    assert work.complete(lease, "x", now=2).reason == q.LATE


def test_expiry_retries_then_becomes_terminal_and_is_recorded(tmp_path):
    work = make(tmp_path, attempts=2)
    item = work.submit("a", "a")
    work.lease("w1", now=0, ttl=1)
    work.expire(now=1)
    assert work.entries[item.item_id].status == q.PENDING
    work.lease("w2", now=1, ttl=1)
    work.expire(now=2)
    assert work.entries[item.item_id].status == q.EXPIRED
    assert work.lease("w3", now=2, ttl=1) is None
    stats = work.stats()
    assert (stats["attempts"], stats["retries"], stats["expiries"], stats["terminal_expired"]) == (
        2, 1, 2, 1)
    assert q.recover(work.path).entries[item.item_id].status == q.EXPIRED


def test_recover_rebuilds_state_and_tolerates_a_torn_last_line(tmp_path):
    work = make(tmp_path)
    work.submit("a", "a")
    work.submit("b", "b")
    lease = work.lease("w", now=0, ttl=5)
    work.complete(lease, {"r": 1}, now=1)
    pending = work.lease("w", now=1, ttl=5)
    with (work.path / "journal.jsonl").open("ab") as handle:
        handle.write(b'{"op":"lease","item_')
    back = q.recover(work.path)
    assert back.recovery["torn_tail"]["bytes"] == 20
    assert back.recovery["events"] == 5
    assert {i: (e.status, e.token, e.result) for i, e in back.entries.items()} == {
        i: (e.status, e.token, e.result) for i, e in work.entries.items()}
    assert back.next_token == pending.token + 1  # fencing stays monotonic across restarts
    assert back.complete(pending, "after restart", now=2).accepted
    assert q.recover(work.path).recovery["torn_tail"] is None


def test_recover_rejects_mid_journal_corruption_and_repairs_a_lost_completion(tmp_path):
    work = make(tmp_path)
    work.submit("a", "a")
    lease = work.lease("w", now=0, ttl=5)
    work.complete(lease, "r", now=1)
    journal = work.path / "journal.jsonl"
    lines = journal.read_bytes().splitlines(keepends=True)
    journal.write_bytes(b"".join(lines[:-1]))  # crash between the commit file and the journal
    back = q.recover(work.path)
    assert back.recovery["repaired_accepted"] == [lease.item_id]
    assert back.entries[lease.item_id].result == "r"
    journal.write_bytes(b"not json\n" + journal.read_bytes())
    with pytest.raises(q.JournalCorrupt):
        q.recover(work.path)


def test_create_is_create_only_and_docs_make_no_exactly_once_claim(tmp_path):
    make(tmp_path)
    with pytest.raises(FileExistsError):
        make(tmp_path)
    assert q.SEMANTICS["exactly_once"] is False
    doc = q.__doc__.lower()
    assert "no exactly-once claim" in doc and "at-least-once" in doc


def test_recover_validates_before_touching_disk_and_cleans_stray_temp_files(tmp_path):
    work = make(tmp_path)
    work.submit("a", "a")
    journal = work.path / "journal.jsonl"
    (work.path / ".tmp-meta.json-999").write_bytes(b"{}")
    (work.path / "accepted" / ".tmp-item-000000.json-999").write_bytes(b"{}")
    journal.write_bytes(b"not json\n" + journal.read_bytes() + b'{"op":"le')
    before = {p: p.read_bytes() for p in work.path.rglob("*") if p.is_file()}
    with pytest.raises(q.JournalCorrupt):
        q.recover(work.path)
    assert {p: p.read_bytes() for p in work.path.rglob("*") if p.is_file()} == before
    journal.write_bytes(journal.read_bytes()[len(b"not json\n"):])
    back = q.recover(work.path)
    assert back.recovery["torn_tail"]["bytes"] == 9
    assert not list(work.path.rglob(".tmp-*"))
