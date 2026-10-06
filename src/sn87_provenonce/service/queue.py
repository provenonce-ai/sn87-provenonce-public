"""A file-backed, bounded work queue for assignments, with leases and fencing tokens.

Layout of a queue directory: ``meta.json`` (bounds; created once, create-only), ``journal.jsonl``
(append-only, one JSON event per line, fsync'ed before the call returns) and
``accepted/<item_id>.json`` (one create-only file per accepted result: the commit point).
State is never written in place; it is the replay of the journal (``recover``).

Delivery semantics, precisely:

* **At-least-once attempts.** An item is leased until it is accepted or terminally EXPIRED. A
  lease that is not completed before it expires returns the item to the queue (``expire``), so
  the same item may be executed more than once. Execution must be harmless to repeat.
* **At most one accepted result per item.** ``complete`` accepts only the item's current lease:
  its fencing token must be the newest one issued for the item and the lease must be unexpired at
  the queue's clock. A late worker holding an older token is rejected and cannot overwrite a
  newer lease's result. The accepted file is written create-only (atomic hard link), so even a
  second writer racing on the same directory cannot accept twice.
* **No exactly-once claim.** Work may run several times; only acceptance is unique. An item that
  exhausts ``max_attempts`` becomes terminal EXPIRED with no result; it is recorded, never
  silently dropped, and its consumer must count it as missing.
* **Bounded.** At most ``max_size`` items are outstanding (pending or leased); ``submit`` refuses
  with ``QueueFull`` beyond that. A repeated idempotency key returns the existing entry and never
  creates a second item (checked before the bound).

Limits: one process owns a directory at a time (no file locking; concurrent owners are not
qualified). Time is an injected integer clock. ``os.fsync`` is used without ``F_FULLFSYNC``, so
durability is claimed against process crashes, not power loss. A torn last journal line (a
crash mid-append) is an uncommitted event: ``recover`` truncates and reports it.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "sn87-work-queue/0.1"
PENDING, LEASED, ACCEPTED, EXPIRED = "PENDING", "LEASED", "ACCEPTED", "EXPIRED"
STALE, LATE, DONE = "STALE_FENCING_TOKEN", "LEASE_EXPIRED", "ALREADY_ACCEPTED"
SEMANTICS = {
    "attempts": "AT_LEAST_ONCE",
    "accepted_results_per_item": "AT_MOST_ONE_BY_FENCING_TOKEN",
    "exactly_once": False,
    "terminal_expired": "RECORDED_AS_MISSING_NEVER_DROPPED",
    "durability": "FSYNC_PER_EVENT_PROCESS_CRASH_ONLY",
    "owners": "SINGLE_PROCESS_PER_DIRECTORY",
}


class QueueFull(RuntimeError):
    pass


class JournalCorrupt(ValueError):
    pass


def _dumps(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_dumps(value)).hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _create_only(path: Path, value: Any) -> None:
    """Atomic create-only write: fsync a temporary file, then hard-link it into place."""
    tmp = path.with_name(f".tmp-{path.name}-{os.getpid()}")
    with tmp.open("wb") as handle:
        handle.write(_dumps(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(tmp, path)  # raises FileExistsError: never overwrites
    finally:
        tmp.unlink()
    _fsync_dir(path.parent)


@dataclass(frozen=True)
class Lease:
    item_id: str
    worker_id: str
    token: int
    attempt: int
    expires_at: int
    item: Any


@dataclass(frozen=True)
class Completion:
    item_id: str
    accepted: bool
    reason: str | None = None


@dataclass
class Entry:
    item_id: str
    key: str
    item: Any
    item_digest: str
    status: str = PENDING
    attempts: int = 0
    token: int | None = None
    expires_at: int | None = None
    result: Any = None


@dataclass
class WorkQueue:
    path: Path
    max_size: int
    max_attempts: int
    entries: dict[str, Entry] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    next_token: int = 1
    counts: Counter = field(default_factory=Counter)
    recovery: dict[str, Any] | None = None

    @classmethod
    def create(cls, path: Path, *, max_size: int, max_attempts: int) -> WorkQueue:
        if max_size < 1 or max_attempts < 1:
            raise ValueError("bounds must be positive")
        path = Path(path)
        (path / "accepted").mkdir(parents=True, exist_ok=True)
        _create_only(path / "meta.json", {"schema": SCHEMA, "max_size": max_size,
                                          "max_attempts": max_attempts})
        (path / "journal.jsonl").open("xb").close()
        _fsync_dir(path)
        return cls(path, max_size, max_attempts)

    # -- journal -------------------------------------------------------------------------------

    def _append(self, event: dict[str, Any]) -> None:
        """Write-ahead: the event is durable before it changes state."""
        with (self.path / "journal.jsonl").open("ab") as handle:
            handle.write(_dumps(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._apply(event)

    def _apply(self, e: dict[str, Any]) -> None:
        op = e["op"]
        self.counts[op] += 1
        if op == "submit":
            self.entries[e["item_id"]] = Entry(e["item_id"], e["key"], e["item"], e["digest"])
            self.keys[e["key"]] = e["item_id"]
            return
        if op in ("dedup", "refuse"):
            return
        entry = self.entries[e["item_id"]]
        if op == "lease":
            entry.status, entry.token, entry.expires_at = LEASED, e["token"], e["expires_at"]
            entry.attempts = e["attempt"]
            self.next_token = e["token"] + 1
        elif op == "complete":
            entry.status, entry.result = ACCEPTED, e["result"]
        elif op == "expire":
            entry.status = EXPIRED if e["terminal"] else PENDING
            self.counts["terminal_expired"] += e["terminal"]
        elif op == "reject":
            self.counts["reject:" + e["reason"]] += 1

    # -- operations ----------------------------------------------------------------------------

    def outstanding(self) -> int:
        return sum(e.status in (PENDING, LEASED) for e in self.entries.values())

    def submit(self, item: Any, idempotency_key: str, *, now: int = 0) -> Entry:
        item_digest = digest(item)
        if idempotency_key in self.keys:
            entry = self.entries[self.keys[idempotency_key]]
            if entry.item_digest != item_digest:
                raise ValueError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_ITEM")
            self._append({"op": "dedup", "key": idempotency_key, "item_id": entry.item_id,
                          "at": now})
            return entry
        if self.outstanding() >= self.max_size:
            self._append({"op": "refuse", "key": idempotency_key, "at": now})
            raise QueueFull(f"QUEUE_FULL: {self.max_size} outstanding")
        item_id = f"item-{len(self.entries):06d}"
        self._append({"op": "submit", "item_id": item_id, "key": idempotency_key, "item": item,
                      "digest": item_digest, "at": now})
        return self.entries[item_id]

    def lease(self, worker_id: str, now: int, ttl: int) -> Lease | None:
        """Lease the oldest pending item with a fresh, strictly increasing fencing token."""
        if ttl < 1:
            raise ValueError("ttl must be positive")
        entry = next((e for e in self.entries.values() if e.status == PENDING), None)
        if entry is None:
            return None
        token = self.next_token
        self._append({"op": "lease", "item_id": entry.item_id, "worker": worker_id,
                      "token": token, "attempt": entry.attempts + 1, "expires_at": now + ttl,
                      "at": now})
        return Lease(entry.item_id, worker_id, token, entry.attempts, now + ttl, entry.item)

    def complete(self, lease: Lease, result: Any, now: int) -> Completion:
        entry = self.entries.get(lease.item_id)
        if entry is None:
            raise KeyError(lease.item_id)
        reason = (STALE if lease.token != entry.token else DONE if entry.status == ACCEPTED
                  else LATE if entry.status != LEASED or now >= entry.expires_at else None)
        if reason is None:
            try:  # the commit point: create-only, so a second acceptance is impossible
                _create_only(self.path / "accepted" / f"{entry.item_id}.json",
                             {"item_id": entry.item_id, "token": lease.token, "result": result})
            except FileExistsError:
                reason = DONE
        if reason is not None:
            self._append({"op": "reject", "item_id": entry.item_id, "token": lease.token,
                          "worker": lease.worker_id, "reason": reason, "at": now})
            return Completion(entry.item_id, False, reason)
        self._append({"op": "complete", "item_id": entry.item_id, "token": lease.token,
                      "result": result, "at": now})
        return Completion(entry.item_id, True)

    def expire(self, now: int) -> list[str]:
        """Return expired leases to the queue; past ``max_attempts`` they become EXPIRED."""
        expired = []
        for entry in self.entries.values():
            if entry.status == LEASED and now >= entry.expires_at:
                self._append({"op": "expire", "item_id": entry.item_id, "token": entry.token,
                              "attempt": entry.attempts,
                              "terminal": entry.attempts >= self.max_attempts, "at": now})
                expired.append(entry.item_id)
        return expired

    def stats(self) -> dict[str, Any]:
        c = self.counts
        retries = sum(max(0, e.attempts - 1) for e in self.entries.values())
        return {
            "submitted": c["submit"], "deduplicated": c["dedup"], "refused_full": c["refuse"],
            "attempts": c["lease"], "retries": retries, "expiries": c["expire"],
            "terminal_expired": c["terminal_expired"], "accepted": c["complete"],
            "rejections": {k[7:]: v for k, v in sorted(c.items()) if k.startswith("reject:")},
            "status": dict(sorted(Counter(e.status for e in self.entries.values()).items())),
            "max_attempts_used": max((e.attempts for e in self.entries.values()), default=0),
        }


def recover(path: Path) -> WorkQueue:
    """Rebuild a queue from its journal after a crash.

    Validate first, then repair: nothing on disk changes until the whole journal and every
    accepted file have been checked, so a ``JournalCorrupt`` leaves the directory as found.
    A torn last line (no trailing newline) is an uncommitted append: it is truncated and
    reported. A malformed complete line is corruption and raises. An accepted file whose
    completion event was lost (crash between commit and journal) is re-journaled and reported.
    Stray ``.tmp-*`` files from an interrupted create-only write are removed.
    """
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    if meta.get("schema") != SCHEMA:
        raise JournalCorrupt("unknown queue schema")
    queue = WorkQueue(path, meta["max_size"], meta["max_attempts"])
    journal = path / "journal.jsonl"
    data = journal.read_bytes()
    cut = data.rfind(b"\n") + 1
    body, torn = data[:cut], data[cut:]
    lines = body.splitlines()
    for number, line in enumerate(lines, 1):  # validate: replay in memory only
        try:
            event = json.loads(line)
        except ValueError as error:
            raise JournalCorrupt(f"journal line {number} is not JSON") from error
        queue._apply(event)
    lost = []
    for file in sorted((path / "accepted").glob("item-*.json")):
        record = json.loads(file.read_text())
        entry = queue.entries.get(record["item_id"])
        if entry is None or entry.token != record["token"]:
            raise JournalCorrupt(f"accepted file {file.name} matches no journaled lease")
        if entry.status != ACCEPTED:
            lost.append(record)
    for entry in queue.entries.values():
        if entry.status == ACCEPTED and not (path / "accepted" / f"{entry.item_id}.json").exists():
            raise JournalCorrupt(f"journaled completion of {entry.item_id} has no accepted file")
    # repair: only after everything above has been validated
    torn_report = None
    if torn:
        torn_report = {"bytes": len(torn), "sha256": "sha256:" + hashlib.sha256(torn).hexdigest()}
        with journal.open("r+b") as handle:
            handle.truncate(len(body))
            handle.flush()
            os.fsync(handle.fileno())
    for stray in [*path.glob(".tmp-*"), *(path / "accepted").glob(".tmp-*")]:
        stray.unlink()
    for record in lost:
        queue._append({"op": "complete", "item_id": record["item_id"], "token": record["token"],
                       "result": record["result"], "at": None, "repaired": True})
    queue.recovery = {"events": len(lines), "torn_tail": torn_report,
                      "repaired_accepted": [r["item_id"] for r in lost]}
    return queue
