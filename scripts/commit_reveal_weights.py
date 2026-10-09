#!/usr/bin/env python3
"""Commit-reveal weight submission path: payload, schedule, persisted state. No chain code.

  uv run python scripts/commit_reveal_weights.py plan --document DOCUMENT.json
  uv run python scripts/commit_reveal_weights.py status --state STATE.json

NO EXTRINSIC IS SENT BY ANYTHING IN THIS REPOSITORY. THE SUBMITTER IS AN INTERFACE.

What this is. For a target whose commit-reveal flag is on, a weight row cannot be set in one
step. This module takes the same input document the plain path takes (``target`` and
``weights``, see ``sn87_provenonce.weights_dry_run``), builds the commit, schedules the reveal,
handles epoch boundaries, rate limits and failures, and keeps its progress in a state file so a
restart between the commit and the reveal resumes instead of starting again.

Which scheme. The pinned SDK (bittensor 11.1.0, see uv.lock) submits weights for a
commit-reveal subnet as a timelock-encrypted commit (``commit_timelocked_mechanism_weights``,
commit-reveal version 4). The chain decrypts it at the drand reveal round and applies it; no
separate reveal call exists on this path. The mode ``timelocked`` is therefore the default and
the one a subnet running the current chain uses. The payload is produced by the SDK's own
function (``bittensor_core.get_encrypted_commit_v2``) with the arguments the SDK's own weight
intent passes; this module does not implement any cryptography. The SDK's intent also conforms
the weights first (max-weight clip, minimum weight count); this module encrypts the
repository's own quantized row instead, and ``dry_run`` refuses a row that would need a clip,
so the two agree only for rows the quantizer accepts. After a crash, a commit that landed
but is not yet visible to ``find_commit`` could be sent again once the confirmation wait
passes; the runner then watches the abandoned id and fails the run if it lands.

The mode ``salted`` is the older two-step scheme (a hash commit, then an explicit reveal with
the salt inside one epoch window). The SDK keeps the reveal call but has no helper that builds
the commit hash, so this module takes the hash function as an argument and never guesses it.
The salted mode is a state machine for chains that still run that scheme; it is not the mode
for the current SDK. Its epoch arithmetic is the legacy formula and must be checked against
the chain version before any use.

What is not here. There is no real submitter. ``CommitRevealRunner`` refuses to start without
an explicit ``Submitter`` object, and the module has no import of a wallet, a key file, an RPC
client or the plain-weights path. ``commit_reveal_fake_chain.FakeChain`` models the chain for
tests. The plain path (``flip_live``) still refuses a commit-reveal target; nothing here
changes that.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import sys
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sn87_provenonce.weights_dry_run import dry_run

MODE_TIMELOCKED = "timelocked"
MODE_SALTED = "salted"
MODES = (MODE_TIMELOCKED, MODE_SALTED)
SDK_VERSION = "11.1.0"
COMMIT_REVEAL_VERSION = 4  # DEFAULT_COMMIT_REVEAL_VERSION in bittensor.intents.weights 11.1.0
STATE_SCHEMA = "sn87-commit-reveal-state/0.1"
NOT_SENT = "NO EXTRINSIC IS SENT BY THIS MODULE: the submitter is an interface"

PLANNED, COMMITTING, COMMITTED, REVEALING = "PLANNED", "COMMITTING", "COMMITTED", "REVEALING"
REVEALED, EXPIRED, OVERDUE, FAILED, SKIPPED_EMPTY = (
    "REVEALED", "EXPIRED", "OVERDUE", "FAILED", "SKIPPED_EMPTY")
TERMINAL = frozenset({REVEALED, EXPIRED, OVERDUE, FAILED, SKIPPED_EMPTY})


class CommitRevealError(RuntimeError):
    """A refusal with a stable code in ``code``."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class SubmitterRequired(CommitRevealError):
    """The runner was built without an explicit submitter object."""


class SaltReused(CommitRevealError):
    """A salt that was used by an earlier commit was offered again."""


class SubmitRejected(CommitRevealError):
    """The chain (or its fake) rejected a submission. ``transient`` allows a retry."""

    def __init__(self, code: str, detail: str = "", *, transient: bool = False):
        super().__init__(code, detail)
        self.transient = transient


# ------------------------------------------------------------------------- interfaces
@dataclass(frozen=True)
class ChainState:
    """Chain values the schedule needs, read at one block (names follow the SDK's queries)."""

    netuid: int
    block: int
    tempo: int
    reveal_period_epochs: int
    commit_reveal_enabled: bool
    rate_limit_blocks: int
    last_update_block: int
    last_epoch_block: int = 0
    pending_epoch_at: int = 0
    subnet_epoch_index: int = 0
    blocks_since_last_step: int = 0
    block_time: float = 12.0


@dataclass(frozen=True)
class TimelockedCommit:
    """What the timelocked commit extrinsic carries, plus the row it commits to."""

    netuid: int
    mecid: int
    commit_bytes: bytes
    reveal_round: int
    commit_reveal_version: int
    uids: tuple[int, ...]
    values: tuple[int, ...]

    @property
    def commit_id(self) -> str:
        return "sha256:" + hashlib.sha256(self.commit_bytes).hexdigest()


@dataclass(frozen=True)
class CommitReceipt:
    commit_id: str
    block: int
    ref: str = ""


class Submitter(ABC):
    """The only object that touches a chain. This repository ships no real implementation.

    A real implementation would send the extrinsics the SDK composes
    (``commit_timelocked_mechanism_weights``, or ``commit_mechanism_weights`` and
    ``reveal_weights`` in the salted mode) and read the chain. It must raise ``SubmitRejected``
    for a rejection, with ``transient=True`` for a rate limit or a network failure.
    """

    @abstractmethod
    def read_state(self, netuid: int) -> ChainState: ...

    @abstractmethod
    def reveal_block_for_round(self, state: ChainState, reveal_round: int) -> int: ...

    @abstractmethod
    def submit_timelocked_commit(self, commit: TimelockedCommit) -> CommitReceipt: ...

    @abstractmethod
    def submit_hash_commit(self, netuid: int, mecid: int, commit_hash: str) -> CommitReceipt: ...

    @abstractmethod
    def submit_reveal(self, netuid: int, mecid: int, uids: Sequence[int],
                      values: Sequence[int], salt: Sequence[int], version_key: int) -> str: ...

    @abstractmethod
    def find_commit(self, netuid: int, commit_id: str) -> CommitReceipt | None: ...

    @abstractmethod
    def read_applied_weights(self, netuid: int) -> dict[int, int] | None: ...

    @abstractmethod
    def commit_revealed(self, netuid: int, commit_id: str) -> bool:
        """True only if the chain's record of THIS commit (by its id or hash) is revealed.
        Equality of the current row with the wanted row is not evidence of this commit."""

    @abstractmethod
    def read_applied_block(self, netuid: int) -> int | None:
        """The block at which the validator's weights were last applied, or None if never.
        A reveal is observed only when this advances past the value read before the commit,
        so a row equal to the previous row is not mistaken for a new reveal."""


# --------------------------------------------------------------------------- the row
def commit_reveal_row(document: dict[str, Any]) -> tuple[list[int], list[int]]:
    """The u16 row for a commit-reveal target, from the same quantizer the plain path uses."""
    target = document["target"]
    if target.get("commit_reveal") is not True:
        raise CommitRevealError("TARGET_NOT_COMMIT_REVEAL")
    out = dry_run(document)
    return list(out["uids"]), list(out["u16_weights"])


def plain_equivalent_row(document: dict[str, Any]) -> tuple[list[int], list[int]]:
    """What the plain path would set for the same input: the proof the row is not changed."""
    plain = {**document, "target": {**document["target"], "commit_reveal": False}}
    out = dry_run(plain)
    return list(out["uids"]), list(out["u16_weights"])


def row_digest(uids: Sequence[int], values: Sequence[int]) -> str:
    body = json.dumps({"uids": list(uids), "values": list(values)}, sort_keys=True,
                      separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------------- epoch arithmetic
def epoch_index(block: int, netuid: int, tempo: int) -> int:
    """Legacy epoch index, ``(block + netuid + 1) // (tempo + 1)``. Used by the salted mode and
    for the boundary margin; the timelocked mode leaves the reveal schedule to the SDK."""
    return (block + netuid + 1) // (tempo + 1)


def epoch_bounds(index: int, netuid: int, tempo: int) -> tuple[int, int]:
    first = index * (tempo + 1) - netuid - 1
    return first, first + tempo


def blocks_to_epoch_end(block: int, netuid: int, tempo: int) -> int:
    return epoch_bounds(epoch_index(block, netuid, tempo), netuid, tempo)[1] - block


def salted_reveal_window(commit_block: int, netuid: int, tempo: int,
                         reveal_period_epochs: int) -> tuple[int, int]:
    """First and last block in which a salted reveal is valid: the commit epoch plus the
    reveal period, exactly one epoch."""
    target = epoch_index(commit_block, netuid, tempo) + reveal_period_epochs
    return epoch_bounds(target, netuid, tempo)


# ------------------------------------------------------------------ timelocked payload
def default_encrypt(**kwargs: Any) -> tuple[bytes, int]:
    """The SDK's own payload function, called lazily so the module imports without the SDK."""
    import bittensor_core
    return bittensor_core.get_encrypted_commit_v2(**kwargs)


def encrypt_arguments(state: ChainState, uids: Sequence[int], values: Sequence[int], *,
                      version_key: int, hotkey_public_key: bytes) -> dict[str, Any]:
    """The arguments the SDK's weight intent passes (``intents.weights._build_timelocked``)."""
    if len(hotkey_public_key) != 32:
        raise CommitRevealError("HOTKEY_PUBLIC_KEY_MUST_BE_32_BYTES")
    return {
        "uids": list(uids), "weights": list(values), "version_key": version_key,
        "last_epoch_block": state.last_epoch_block, "pending_epoch_at": state.pending_epoch_at,
        "subnet_epoch_index": state.subnet_epoch_index, "tempo": state.tempo,
        "blocks_since_last_step": state.blocks_since_last_step, "current_block": state.block,
        "subnet_reveal_period_epochs": state.reveal_period_epochs,
        "block_time": state.block_time, "hotkey": hotkey_public_key,
    }


def build_timelocked_commit(state: ChainState, uids: Sequence[int], values: Sequence[int], *,
                            mecid: int = 0, version_key: int = 0, hotkey_public_key: bytes,
                            encrypt: Callable[..., tuple[bytes, int]] | None = None
                            ) -> TimelockedCommit:
    commit_bytes, reveal_round = (encrypt or default_encrypt)(
        **encrypt_arguments(state, uids, values, version_key=version_key,
                            hotkey_public_key=hotkey_public_key))
    return TimelockedCommit(state.netuid, mecid, bytes(commit_bytes), int(reveal_round),
                            COMMIT_REVEAL_VERSION, tuple(uids), tuple(values))


def drand_reveal_block(reveal_round: int, *, block: int, now_ts: float,
                       block_time: float = 12.0) -> int:
    """Estimate the chain block at which a drand round becomes available.

    Real-chain helper for a real submitter: the round's time is exact (SDK ``timelock``), the
    block is an estimate from the block time. A fake chain does not use it.
    """
    from bittensor import timelock
    reveal_ts = timelock.reveal_time(reveal_round).timestamp()
    return block + max(0, math.ceil((reveal_ts - now_ts) / block_time))


# --------------------------------------------------------------------------- state file
def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


class StateFile:
    """The run state: one JSON file, replaced atomically, mode 0600 (it holds a salt)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.salt_ledger = self.path.with_name(self.path.name + ".salts")

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CommitRevealError("STATE_FILE_UNREADABLE", type(error).__name__) from error
        if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
            raise CommitRevealError("STATE_FILE_SCHEMA")
        return state

    def save(self, state: dict[str, Any]) -> None:
        _atomic_write(self.path, json.dumps(state, indent=2, sort_keys=True) + "\n")

    def used_salts(self) -> set[str]:
        if not self.salt_ledger.exists():
            return set()
        return set(json.loads(self.salt_ledger.read_text(encoding="utf-8")))

    def remember_salt(self, digest: str) -> None:
        _atomic_write(self.salt_ledger, json.dumps(sorted(self.used_salts() | {digest})) + "\n")


def salt_digest(salt: Sequence[int]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(list(salt)).encode()).hexdigest()


def default_salt() -> list[int]:
    """A fresh salt of eight u16 values from the operating system's random source."""
    return [secrets.randbelow(65536) for _ in range(8)]


# ------------------------------------------------------------------------------- runner
@dataclass
class StepResult:
    phase: str
    action: str
    detail: str = ""
    wait_until_block: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL


class CommitRevealRunner:
    """Drives one commit-reveal run through a ``Submitter``, persisting every transition.

    ``start`` plans a run from a document; ``step`` performs at most one transition and is safe
    to call again after a restart: it reloads the state file, and a commit that was written
    ahead but not confirmed is looked up on the chain before it is sent again.
    """

    def __init__(self, *, submitter: Submitter | None, state_path: Path | str,
                 mode: str = MODE_TIMELOCKED, netuid: int, mecid: int = 0, version_key: int = 0,
                 hotkey_public_key: bytes | None = None,
                 encrypt: Callable[..., tuple[bytes, int]] | None = None,
                 commit_digest: Callable[..., str] | None = None,
                 salt_source: Callable[[], list[int]] = default_salt,
                 commit_margin_blocks: int = 3, reveal_grace_blocks: int = 10,
                 max_attempts: int = 3, commit_confirm_blocks: int = 3):
        if not isinstance(submitter, Submitter):
            raise SubmitterRequired("an explicit Submitter object is required; "
                                    "this repository ships none for a real chain")
        if mode not in MODES:
            raise CommitRevealError("MODE_UNKNOWN", mode)
        if mode == MODE_TIMELOCKED and hotkey_public_key is None:
            raise CommitRevealError("HOTKEY_PUBLIC_KEY_REQUIRED")
        if mode == MODE_SALTED and commit_digest is None:
            raise CommitRevealError("COMMIT_DIGEST_FUNCTION_REQUIRED",
                                    "the pinned SDK has no helper for the legacy commit hash")
        self.submitter, self.mode = submitter, mode
        self.netuid, self.mecid, self.version_key = netuid, mecid, version_key
        self.hotkey_public_key, self.encrypt = hotkey_public_key, encrypt
        self.commit_digest, self.salt_source = commit_digest, salt_source
        self.commit_margin_blocks, self.reveal_grace_blocks = commit_margin_blocks, \
            reveal_grace_blocks
        self.max_attempts, self.commit_confirm_blocks = max_attempts, commit_confirm_blocks
        self.store = StateFile(Path(state_path))

    # ---- planning
    def start(self, document: dict[str, Any]) -> dict[str, Any]:
        existing = self.store.load()
        if existing is not None and existing["phase"] not in TERMINAL:
            raise CommitRevealError("RUN_IN_PROGRESS", existing["phase"])
        target = document["target"]
        if target["netuid"] != self.netuid:
            raise CommitRevealError("NETUID_MISMATCH")
        row_uids, row_values = commit_reveal_row(document)
        state = {
            "schema": STATE_SCHEMA, "mode": self.mode, "netuid": self.netuid,
            "mecid": self.mecid, "version_key": self.version_key,
            "phase": SKIPPED_EMPTY if not row_uids else PLANNED,
            "row": {"uids": row_uids, "values": row_values},
            "row_digest": row_digest(row_uids, row_values),
            "commit": None, "salt": None, "attempts": {"commit": 0, "reveal": 0},
            "abandoned_commits": [], "applied_block_before": None,
            "history": [], "not_sent_statement": NOT_SENT,
        }
        self._note(state, state["phase"], None, "planned" if row_uids else "empty row")
        self.store.save(state)
        return state

    @staticmethod
    def _note(state: dict[str, Any], phase: str, block: int | None, note: str) -> None:
        state["history"].append({"phase": phase, "block": block, "note": note})
        state["phase"] = phase

    def _save(self, state: dict[str, Any]) -> None:
        self.store.save(state)

    # ---- stepping
    def step(self) -> StepResult:
        state = self.store.load()
        if state is None:
            raise CommitRevealError("NO_RUN")
        if state["mode"] != self.mode or state["netuid"] != self.netuid:
            raise CommitRevealError("STATE_DOES_NOT_MATCH_RUNNER")
        phase = state["phase"]
        if phase in TERMINAL:
            return StepResult(phase, "TERMINAL")
        chain = self.submitter.read_state(self.netuid)
        for abandoned in state.get("abandoned_commits", []):
            if self.submitter.find_commit(self.netuid, abandoned) is not None:
                self._note(state, FAILED, chain.block, "an abandoned commit landed later")
                self._save(state)
                return StepResult(FAILED, "DOUBLE_COMMIT_DETECTED", abandoned)
        if phase == PLANNED:
            return self._plan_commit(state, chain)
        if phase == COMMITTING:
            return self._resolve_committing(state, chain)
        if phase == COMMITTED:
            return self._after_commit(state, chain)
        if phase == REVEALING:
            return self._resolve_revealing(state, chain)
        raise CommitRevealError("STATE_PHASE_UNKNOWN", phase)

    def run_until_terminal(self, advance: Callable[[int | None], None], max_steps: int = 200
                           ) -> StepResult:
        """Step until terminal; ``advance(wait_until_block)`` lets the caller move time on."""
        result = self.step()
        for _ in range(max_steps):
            if result.terminal:
                return result
            advance(result.wait_until_block)
            result = self.step()
        raise CommitRevealError("MAX_STEPS_EXCEEDED")

    # ---- PLANNED
    def _plan_commit(self, state: dict[str, Any], chain: ChainState) -> StepResult:
        if not chain.commit_reveal_enabled:
            raise CommitRevealError("CHAIN_COMMIT_REVEAL_NOT_ENABLED",
                                    "use the plain path for a target with commit-reveal off")
        ready = chain.last_update_block + chain.rate_limit_blocks
        if chain.block < ready:
            return StepResult(PLANNED, "WAIT_RATE_LIMIT", wait_until_block=ready)
        left = blocks_to_epoch_end(chain.block, chain.netuid, chain.tempo)
        if left < self.commit_margin_blocks:
            return StepResult(PLANNED, "WAIT_EPOCH_BOUNDARY",
                              wait_until_block=chain.block + left + 1)
        uids, values = state["row"]["uids"], state["row"]["values"]
        state["applied_block_before"] = self.submitter.read_applied_block(self.netuid)
        if self.mode == MODE_TIMELOCKED:
            commit = build_timelocked_commit(
                chain, uids, values, mecid=self.mecid, version_key=self.version_key,
                hotkey_public_key=self.hotkey_public_key or b"", encrypt=self.encrypt)
            state["commit"] = {
                "commit_id": commit.commit_id, "payload_hex": commit.commit_bytes.hex(),
                "reveal_round": commit.reveal_round,
                "reveal_block": self.submitter.reveal_block_for_round(chain, commit.reveal_round),
                "planned_block": chain.block, "landed_block": None}
        else:
            salt = self.salt_source()
            digest = salt_digest(salt)
            if digest in self.store.used_salts():
                raise SaltReused("SALT_REUSED", "a salt may be used for one commit only")
            commit_hash = self.commit_digest(self.netuid, self.mecid, uids, values, salt,
                                             self.version_key)
            self.store.remember_salt(digest)  # recorded before it can be sent
            state["salt"] = list(salt)
            state["commit"] = {"commit_id": commit_hash, "planned_block": chain.block,
                               "landed_block": None, "reveal_window": None}
        self._note(state, COMMITTING, chain.block, "write-ahead before submission")
        self._save(state)
        return self._submit_commit(state, chain)

    # ---- COMMITTING
    def _submit_commit(self, state: dict[str, Any], chain: ChainState) -> StepResult:
        commit = state["commit"]
        try:
            if self.mode == MODE_TIMELOCKED:
                receipt = self.submitter.submit_timelocked_commit(TimelockedCommit(
                    self.netuid, self.mecid, bytes.fromhex(commit["payload_hex"]),
                    commit["reveal_round"], COMMIT_REVEAL_VERSION,
                    tuple(state["row"]["uids"]), tuple(state["row"]["values"])))
            else:
                receipt = self.submitter.submit_hash_commit(self.netuid, self.mecid,
                                                            commit["commit_id"])
        except SubmitRejected as error:
            state["attempts"]["commit"] += 1
            if not error.transient or state["attempts"]["commit"] >= self.max_attempts:
                self._note(state, FAILED, chain.block, f"commit rejected: {error.code}")
                self._save(state)
                return StepResult(FAILED, "COMMIT_REJECTED", error.code)
            self._note(state, COMMITTING, chain.block, f"transient: {error.code}")
            self._save(state)
            return StepResult(COMMITTING, "RETRY_COMMIT", error.code,
                              wait_until_block=chain.block + 1)
        return self._landed(state, chain, receipt)

    def _landed(self, state: dict[str, Any], chain: ChainState, receipt: CommitReceipt
                ) -> StepResult:
        commit = state["commit"]
        commit["landed_block"] = receipt.block
        if self.mode == MODE_SALTED:
            commit["reveal_window"] = list(salted_reveal_window(
                receipt.block, chain.netuid, chain.tempo, chain.reveal_period_epochs))
        self._note(state, COMMITTED, receipt.block, "commit landed")
        self._save(state)
        return StepResult(COMMITTED, "COMMITTED", wait_until_block=self._due_block(state))

    @staticmethod
    def _due_block(state: dict[str, Any]) -> int:
        commit = state["commit"]
        return commit["reveal_block"] if state["mode"] == MODE_TIMELOCKED \
            else commit["reveal_window"][0]

    def _resolve_committing(self, state: dict[str, Any], chain: ChainState) -> StepResult:
        """After a restart: the commit may have landed before the crash."""
        found = self.submitter.find_commit(self.netuid, state["commit"]["commit_id"])
        if found is not None:
            return self._landed(state, chain, found)
        planned = state["commit"]["planned_block"]
        if epoch_index(chain.block, chain.netuid, chain.tempo) != epoch_index(
                planned, chain.netuid, chain.tempo):
            if chain.block < planned + self.commit_confirm_blocks:
                # an index that lags the chain must not cause a second commit
                return StepResult(COMMITTING, "WAIT_COMMIT_CONFIRMATION",
                                  wait_until_block=planned + self.commit_confirm_blocks)
            # the epoch moved on without the commit: the payload's schedule is stale
            self._note(state, PLANNED, chain.block, "commit not found, epoch changed: replan")
            state["abandoned_commits"].append(state["commit"]["commit_id"])
            state["commit"], state["salt"] = None, None
            self._save(state)
            return self._plan_commit(state, chain)
        return self._submit_commit(state, chain)

    # ---- COMMITTED
    def _after_commit(self, state: dict[str, Any], chain: ChainState) -> StepResult:
        return self._timelocked_wait(state, chain) if self.mode == MODE_TIMELOCKED \
            else self._salted_reveal(state, chain)

    def _timelocked_wait(self, state: dict[str, Any], chain: ChainState) -> StepResult:
        """The chain reveals; this only watches for the row and flags an overdue reveal."""
        reveal_block = state["commit"]["reveal_block"]
        if chain.block < reveal_block:
            return StepResult(COMMITTED, "WAIT_FOR_CHAIN_REVEAL", wait_until_block=reveal_block)
        applied = self.submitter.read_applied_weights(self.netuid)
        before = state.get("applied_block_before")
        applied_block = self.submitter.read_applied_block(self.netuid)
        advanced = applied_block is not None and (before is None or applied_block > before)
        if applied is not None and advanced and self._applied_equals(state, applied):
            self._note(state, REVEALED, chain.block, "chain applied the committed row")
            self._save(state)
            return StepResult(REVEALED, "REVEAL_OBSERVED")
        deadline = reveal_block + self.reveal_grace_blocks
        if chain.block <= deadline:
            return StepResult(COMMITTED, "WAIT_FOR_CHAIN_REVEAL", wait_until_block=chain.block + 1)
        self._note(state, OVERDUE, chain.block, "reveal not observed within the grace period")
        self._save(state)
        return StepResult(OVERDUE, "REVEAL_OVERDUE", "operator attention needed")

    @staticmethod
    def _applied_equals(state: dict[str, Any], applied: dict[int, int]) -> bool:
        row = dict(zip(state["row"]["uids"], state["row"]["values"], strict=True))
        return {int(k): int(v) for k, v in applied.items()} == row

    def _salted_reveal(self, state: dict[str, Any], chain: ChainState) -> StepResult:
        first, last = state["commit"]["reveal_window"]
        if chain.block < first:
            return StepResult(COMMITTED, "WAIT_REVEAL_WINDOW", wait_until_block=first)
        if chain.block > last:
            self._note(state, EXPIRED, chain.block, "reveal window passed without a reveal")
            self._save(state)
            return StepResult(EXPIRED, "REVEAL_WINDOW_MISSED")
        self._note(state, REVEALING, chain.block, "write-ahead before reveal")
        self._save(state)
        return self._send_reveal(state, chain, last)

    def _send_reveal(self, state: dict[str, Any], chain: ChainState, last: int) -> StepResult:
        try:
            self.submitter.submit_reveal(self.netuid, self.mecid, state["row"]["uids"],
                                         state["row"]["values"], state["salt"],
                                         self.version_key)
        except SubmitRejected as error:
            state["attempts"]["reveal"] += 1
            if error.transient and chain.block < last:
                self._note(state, COMMITTED, chain.block, f"transient: {error.code}")
                self._save(state)
                return StepResult(COMMITTED, "RETRY_REVEAL", error.code,
                                  wait_until_block=chain.block + 1)
            phase = EXPIRED if error.transient else FAILED
            self._note(state, phase, chain.block, f"reveal rejected: {error.code}")
            self._save(state)
            return StepResult(phase, "REVEAL_REJECTED", error.code)
        applied = self.submitter.read_applied_weights(self.netuid)
        if applied is not None and not self._applied_equals(state, applied):
            self._note(state, FAILED, chain.block, "applied row differs from the committed row")
            self._save(state)
            return StepResult(FAILED, "APPLIED_ROW_MISMATCH")
        self._note(state, REVEALED, chain.block, "reveal accepted")
        self._save(state)
        return StepResult(REVEALED, "REVEALED")

    def _resolve_revealing(self, state: dict[str, Any], chain: ChainState) -> StepResult:
        """After a restart during a reveal: the reveal landed only if the chain's record of this
        commit says so. A current row equal to the wanted row proves nothing."""
        if self.submitter.commit_revealed(self.netuid, state["commit"]["commit_id"]):
            self._note(state, REVEALED, chain.block, "chain record of this commit is revealed")
            self._save(state)
            return StepResult(REVEALED, "REVEAL_OBSERVED")
        first, last = state["commit"]["reveal_window"]
        if chain.block > last:
            self._note(state, EXPIRED, chain.block, "reveal window passed")
            self._save(state)
            return StepResult(EXPIRED, "REVEAL_WINDOW_MISSED")
        return self._send_reveal(state, chain, last)


# ------------------------------------------------------------------------------- CLI
def plan_summary(document: dict[str, Any]) -> dict[str, Any]:
    """Offline: the row the commit would carry, and proof it equals the plain path's row."""
    uids, values = commit_reveal_row(document)
    plain_uids, plain_values = plain_equivalent_row(document)
    return {"statement": NOT_SENT, "mode_for_sdk": f"{MODE_TIMELOCKED} (bittensor {SDK_VERSION})",
            "commit_reveal_version": COMMIT_REVEAL_VERSION, "uids": uids, "u16_weights": values,
            "row_digest": row_digest(uids, values),
            "equals_plain_path_row": (uids, values) == (plain_uids, plain_values)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="offline: the row a commit would carry")
    plan.add_argument("--document", type=Path, required=True)
    status = sub.add_parser("status", help="print a state file")
    status.add_argument("--state", type=Path, required=True)
    sub.add_parser("submit", help="not implemented here: refuses")
    args = parser.parse_args(argv)
    try:
        if args.command == "submit":
            print("REFUSED: this repository has no submitter; no extrinsic is sent by it",
                  file=sys.stderr)
            return 2
        if args.command == "plan":
            print(json.dumps(plan_summary(json.loads(args.document.read_text("utf-8"))),
                             indent=2, sort_keys=True))
            return 0
        state = StateFile(args.state).load()
        if state is None:
            print("no state file", file=sys.stderr)
            return 1
        shown = {k: v for k, v in state.items() if k != "salt"}  # never print the salt
        print(json.dumps(shown, indent=2, sort_keys=True))
        return 0
    except (CommitRevealError, ValueError, OSError, KeyError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
