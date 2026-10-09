"""A fake chain for the commit-reveal path. TEST USE ONLY. No network, no key, no SDK call.

``FakeChain`` implements ``commit_reveal_weights.Submitter`` over an in-memory model of one
subnet: blocks, tempo and epochs, a commit window, a reveal window, a weights rate limit,
rejections, injected failures, an epoch with no commit, and replayed commits.

What it models, and what it does not.

* Blocks advance only when the test says so (``advance``, ``advance_to``).
* The timelocked path: a commit is accepted with a reveal round; the fake maps a round to a
  block one to one (a stand-in for drand) and applies the row at that block, as the chain does
  at the reveal round. The fake cannot decrypt the SDK's real ciphertext, so it only accepts
  payloads made by ``FakeChain.encrypt`` and refuses any other payload (the real payload
  function is tested separately against the SDK).
* The salted path: a hash commit, then a reveal that must come in the epoch that is the commit
  epoch plus the reveal period. The hash function is ``fake_commit_digest``; it is NOT the
  chain's hash.
* Epochs use the legacy index formula in ``commit_reveal_weights.epoch_index``.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import commit_reveal_weights as crw
from commit_reveal_weights import (
    ChainState,
    CommitReceipt,
    SubmitRejected,
    Submitter,
    TimelockedCommit,
)

FAKE_PREFIX = b"FAKE-TLE:"


class SimulatedCrash(BaseException):  # not an Exception: nothing in the runner may swallow it
    """The process died at this point; the chain-side effect (if any) has happened."""


def fake_commit_digest(netuid: int, mecid: int, uids: Sequence[int], values: Sequence[int],
                       salt: Sequence[int], version_key: int) -> str:
    """Test-only stand-in for the legacy commit hash. NOT the chain's hash function."""
    body = json.dumps([netuid, mecid, list(uids), list(values), list(salt), version_key],
                      separators=(",", ":")).encode()
    return "fake-sha256:" + hashlib.sha256(body).hexdigest()


@dataclass
class _HashCommit:
    block: int
    epoch: int
    revealed: bool = False


class FakeChain(Submitter):
    def __init__(self, *, netuid: int = 582, tempo: int = 20, reveal_period_epochs: int = 1,
                 commit_reveal_enabled: bool = True, rate_limit_blocks: int = 1,
                 start_block: int = 100, block_time: float = 12.0):
        self.netuid, self.tempo = netuid, tempo
        self.reveal_period_epochs = reveal_period_epochs
        self.commit_reveal_enabled = commit_reveal_enabled
        self.rate_limit_blocks, self.block_time = rate_limit_blocks, block_time
        self.block = start_block
        self.last_update_block = 0
        self.weights: dict[int, int] | None = None
        self.weights_log: list[tuple[int, dict[int, int]]] = []
        self.empty_epochs = 0
        self._applied_in_epoch = False
        self._timelocked: dict[str, dict[str, Any]] = {}
        self._hash_commits: dict[str, _HashCommit] = {}
        self._failures: dict[str, list[BaseException]] = defaultdict(list)
        self._crash_after: set[str] = set()
        self._drop_reveals = 0
        self.calls: list[tuple[str, int]] = []

    # ---- time
    def advance(self, blocks: int = 1) -> None:
        for _ in range(blocks):
            before = crw.epoch_index(self.block, self.netuid, self.tempo)
            self.block += 1
            if crw.epoch_index(self.block, self.netuid, self.tempo) != before:
                if not self._applied_in_epoch:
                    self.empty_epochs += 1
                self._applied_in_epoch = False
            self._reveal_due()

    def advance_to(self, block: int | None) -> None:
        if block is None or block <= self.block:
            self.advance(1)
        else:
            self.advance(block - self.block)

    def _reveal_due(self) -> None:
        for item in list(self._timelocked.values()):
            if item["done"] or self.block < item["reveal_block"]:
                continue
            item["done"] = True
            if self._drop_reveals:
                self._drop_reveals -= 1
                continue
            self._apply(item["uids"], item["values"])

    def _apply(self, uids: Sequence[int], values: Sequence[int]) -> None:
        self.weights = dict(zip(uids, values, strict=True))
        self.weights_log.append((self.block, dict(self.weights)))
        self._applied_in_epoch = True

    # ---- failure injection
    def fail_next(self, operation: str, error: SubmitRejected) -> None:
        self._failures[operation].append(error)

    def crash_after(self, operation: str) -> None:
        self._crash_after.add(operation)

    def drop_next_reveal(self) -> None:
        """The next timelocked reveal does not apply (the chain failed to open the commit)."""
        self._drop_reveals += 1

    def _enter(self, operation: str) -> None:
        self.calls.append((operation, self.block))
        if self._failures[operation]:
            raise self._failures[operation].pop(0)

    def _leave(self, operation: str) -> None:
        if operation in self._crash_after:
            self._crash_after.discard(operation)
            raise SimulatedCrash(operation)

    def _check_commit_allowed(self) -> None:
        if not self.commit_reveal_enabled:
            raise SubmitRejected("COMMIT_REVEAL_DISABLED")
        if self.block - self.last_update_block < self.rate_limit_blocks:
            raise SubmitRejected("RATE_LIMITED", transient=True)

    # ---- timelock stand-in (the test passes ``encrypt=chain.encrypt``)
    def encrypt(self, **kwargs: Any) -> tuple[bytes, int]:
        index = crw.epoch_index(kwargs["current_block"], self.netuid, kwargs["tempo"])
        reveal_block = crw.epoch_bounds(index + kwargs["subnet_reveal_period_epochs"],
                                        self.netuid, kwargs["tempo"])[0]
        body = json.dumps({"uids": kwargs["uids"], "weights": kwargs["weights"],
                           "version_key": kwargs["version_key"],
                           "built_at_block": kwargs["current_block"],
                           "hotkey": bytes(kwargs["hotkey"]).hex()}, sort_keys=True)
        return FAKE_PREFIX + body.encode(), reveal_block

    # ---- Submitter
    def read_state(self, netuid: int) -> ChainState:
        index = crw.epoch_index(self.block, self.netuid, self.tempo)
        first = crw.epoch_bounds(index, self.netuid, self.tempo)[0]
        return ChainState(
            netuid=self.netuid, block=self.block, tempo=self.tempo,
            reveal_period_epochs=self.reveal_period_epochs,
            commit_reveal_enabled=self.commit_reveal_enabled,
            rate_limit_blocks=self.rate_limit_blocks, last_update_block=self.last_update_block,
            last_epoch_block=first, subnet_epoch_index=index,
            blocks_since_last_step=self.block - first, block_time=self.block_time)

    def reveal_block_for_round(self, state: ChainState, reveal_round: int) -> int:
        return reveal_round  # fake drand: one round per block

    def submit_timelocked_commit(self, commit: TimelockedCommit) -> CommitReceipt:
        self._enter("submit_timelocked_commit")
        self._check_commit_allowed()
        if not commit.commit_bytes.startswith(FAKE_PREFIX):
            raise SubmitRejected("FAKE_CHAIN_UNSUPPORTED_PAYLOAD")
        if commit.commit_id in self._timelocked:
            raise SubmitRejected("COMMIT_REPLAY")
        body = json.loads(commit.commit_bytes[len(FAKE_PREFIX):])
        self._timelocked[commit.commit_id] = {
            "block": self.block, "reveal_block": commit.reveal_round, "done": False,
            "uids": body["uids"], "values": body["weights"]}
        self.last_update_block = self.block
        self._leave("submit_timelocked_commit")
        return CommitReceipt(commit.commit_id, self.block, "fake-extrinsic")

    def submit_hash_commit(self, netuid: int, mecid: int, commit_hash: str) -> CommitReceipt:
        self._enter("submit_hash_commit")
        self._check_commit_allowed()
        if commit_hash in self._hash_commits:
            raise SubmitRejected("COMMIT_ALREADY_EXISTS")
        self._hash_commits[commit_hash] = _HashCommit(
            self.block, crw.epoch_index(self.block, self.netuid, self.tempo))
        self.last_update_block = self.block
        self._leave("submit_hash_commit")
        return CommitReceipt(commit_hash, self.block, "fake-extrinsic")

    def submit_reveal(self, netuid: int, mecid: int, uids: Sequence[int],
                      values: Sequence[int], salt: Sequence[int], version_key: int) -> str:
        self._enter("submit_reveal")
        digest = fake_commit_digest(netuid, mecid, uids, values, salt, version_key)
        commit = self._hash_commits.get(digest)
        if commit is None or commit.revealed:
            raise SubmitRejected("NO_MATCHING_COMMIT")
        now = crw.epoch_index(self.block, self.netuid, self.tempo)
        due = commit.epoch + self.reveal_period_epochs
        if now < due:
            raise SubmitRejected("REVEAL_TOO_EARLY")
        if now > due:
            raise SubmitRejected("REVEAL_EXPIRED")
        commit.revealed = True
        self._apply(uids, values)
        self._leave("submit_reveal")
        return "fake-extrinsic"

    def find_commit(self, netuid: int, commit_id: str) -> CommitReceipt | None:
        item = self._timelocked.get(commit_id)
        if item is not None:
            return CommitReceipt(commit_id, item["block"], "fake-extrinsic")
        hashed = self._hash_commits.get(commit_id)
        return None if hashed is None else CommitReceipt(commit_id, hashed.block, "fake-extrinsic")

    def read_applied_weights(self, netuid: int) -> dict[int, int] | None:
        return None if self.weights is None else dict(self.weights)

    def commit_revealed(self, netuid: int, commit_id: str) -> bool:
        hashed = self._hash_commits.get(commit_id)
        if hashed is not None:
            return hashed.revealed
        item = self._timelocked.get(commit_id)
        return bool(item and item["done"])

    def read_applied_block(self, netuid: int) -> int | None:
        return self.weights_log[-1][0] if self.weights_log else None
