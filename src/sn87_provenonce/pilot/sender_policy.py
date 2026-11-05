"""Who may send to a miner: the sender allowlist, and a global rate limit behind it.

The signed endpoint authenticates a request (``btauth/1``: signature, freshness, receiver) but
a signature only proves that SOME key sent it: anyone can mint a key. This module decides
whether that key may send at all.

* ``SenderPolicy`` accepts a signing hotkey only if it held ``validator_permit`` on the
  configured netuid in the most recent metagraph snapshot, or it is the one probe hotkey the
  operator named. The snapshot comes from a ``PermitSnapshotProvider`` (a read-only chain
  read in production, a fake in tests) and is refreshed at most once per refresh interval
  (one epoch by default); a revoked permit stops working at the next refresh.
* A per-sender token bucket then keeps one permitted sender (or the probe key) from using up the
  allowance of the others, and a global token bucket limits all of them as a group. The check
  order matters: the permit check comes first, so a key nobody vouches for cannot drain either
  bucket.
* ``AllowAnySender`` is the explicit, logged opt-out for local and development use. It keeps
  the global rate limit and drops only the permit check.

``PolicyAdmission`` plugs a policy in front of the replay store. The SDK calls the store only
AFTER the signature has verified, so the sender is authenticated when the policy sees it, and a
rejected sender never writes a replay key. A rejection is a ``BoundaryError`` with a stable
code, raised before the request body is parsed, so a rejected request never reaches the miner
method or any scoring.

This module imports no chain or web library. Nothing here writes to a chain.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .transport import BoundaryError

LOG = logging.getLogger("sn87.miner.sender_policy")

# One epoch on a subnet with the default tempo (360 blocks of 12 seconds).
DEFAULT_REFRESH_SECONDS = 4320.0
MIN_REFRESH_SECONDS = 60.0
MAX_REFRESH_SECONDS = 6 * DEFAULT_REFRESH_SECONDS     # a longer interval keeps revoked permits
MAX_STALE_SECONDS = 2 * MAX_REFRESH_SECONDS
# A failed refresh is not retried sooner than this (the chain is not hammered).
DEFAULT_RETRY_SECONDS = 30.0
# One read (all its chain queries) gets this long; a hung read is abandoned after it.
DEFAULT_FETCH_TIMEOUT_SECONDS = 60.0
DEFAULT_RATE_PER_SECOND = 20.0
# A validator's round is 16 instances, so a burst must hold a few rounds.
DEFAULT_BURST = 128
DEFAULT_SENDER_RATE_PER_SECOND = 5.0
DEFAULT_SENDER_BURST = 32
# Trusted senders skip only the permit check; the list stays short so it stays reviewable.
MAX_TRUSTED_SENDERS = 8


class SnapshotError(Exception):
    """A snapshot provider could not produce a snapshot. Carries a stable code only."""


@dataclass(frozen=True)
class PermitSnapshot:
    """The hotkeys holding validator_permit on one netuid at one point in the chain."""

    netuid: int
    permitted: frozenset[str]
    block: int | None = None


class PermitSnapshotProvider(Protocol):
    def fetch(self, netuid: int) -> PermitSnapshot: ...


@dataclass(frozen=True)
class SenderPolicyConfig:
    netuid: int
    refresh_seconds: float = DEFAULT_REFRESH_SECONDS
    # A snapshot older than this is not trusted even if refreshes keep failing (fail closed).
    max_stale_seconds: float | None = None
    retry_seconds: float = DEFAULT_RETRY_SECONDS
    fetch_timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS
    rate_per_second: float = DEFAULT_RATE_PER_SECOND
    burst: int = DEFAULT_BURST
    sender_rate_per_second: float = DEFAULT_SENDER_RATE_PER_SECOND
    sender_burst: int = DEFAULT_SENDER_BURST
    probe_hotkey: str | None = None
    trusted_senders: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.netuid) is not int or not 0 <= self.netuid <= 65535:
            raise ValueError("netuid")
        if (not math.isfinite(self.refresh_seconds)
                or not MIN_REFRESH_SECONDS <= self.refresh_seconds <= MAX_REFRESH_SECONDS):
            raise ValueError("refresh_seconds")
        if not math.isfinite(self.retry_seconds) or self.retry_seconds <= 0:
            raise ValueError("retry_seconds")
        if (not math.isfinite(self.fetch_timeout_seconds) or self.fetch_timeout_seconds <= 0
                or self.fetch_timeout_seconds > self.refresh_seconds):
            raise ValueError("fetch_timeout_seconds")
        stale = self.max_stale_seconds
        if stale is not None and (not math.isfinite(stale) or stale < self.refresh_seconds
                                  or stale > MAX_STALE_SECONDS):
            raise ValueError("max_stale_seconds")
        _check_rate(self.rate_per_second, self.burst)
        _check_rate(self.sender_rate_per_second, self.sender_burst)
        if (type(self.trusted_senders) is not tuple
                or not all(isinstance(k, str) and k for k in self.trusted_senders)
                or len(self.trusted) > MAX_TRUSTED_SENDERS):
            raise ValueError("trusted_senders")

    @property
    def trusted(self) -> tuple[str, ...]:
        """Every sender that skips the permit check (the probe hotkey included), in order."""
        found = [*self.trusted_senders, *([self.probe_hotkey] if self.probe_hotkey else [])]
        return tuple(dict.fromkeys(found))

    @property
    def stale_limit(self) -> float:
        return self.max_stale_seconds if self.max_stale_seconds is not None \
            else 2 * self.refresh_seconds


def _check_rate(rate: float, burst: int) -> None:
    if not math.isfinite(rate) or rate <= 0 or type(burst) is not int or burst < 1:
        raise ValueError("rate")


class TokenBucket:
    """A thread-safe token bucket: ``burst`` tokens, refilled at ``rate`` per second."""

    def __init__(self, rate: float, burst: int, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        _check_rate(rate, burst)
        self.rate, self.burst, self._clock = rate, burst, clock
        self._tokens = float(burst)
        self._at = clock()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = self._clock()
            self._tokens = min(float(self.burst), self._tokens + (now - self._at) * self.rate)
            self._at = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class SenderPolicy:
    """Permit-based sender allowlist with a per-epoch snapshot and two rate limits.

    The snapshot is read on a background thread started by ``admit`` when it is due; ``admit``
    itself never waits for the chain. Only keys that hold a permit (or the probe key) get a
    per-sender bucket, so that dictionary is bounded by the subnet size."""

    mode = "permit-allowlist"

    def __init__(self, provider: PermitSnapshotProvider, config: SenderPolicyConfig, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._provider, self.config, self._clock = provider, config, clock
        self._bucket = TokenBucket(config.rate_per_second, config.burst, clock=clock)
        self._sender_buckets: dict[str, TokenBucket] = {}
        self._trusted = frozenset(config.trusted)
        if self._trusted:
            LOG.warning("sender policy: %d trusted sender(s) skip the permit check: %s",
                        len(self._trusted), ", ".join(config.trusted))
        self._lock = threading.Lock()
        self._snapshot: PermitSnapshot | None = None
        self._started_at = 0.0           # when the read behind the current snapshot began
        self._next_attempt = 0.0
        self._inflight_since: float | None = None
        self._worker: threading.Thread | None = None
        self.refreshes = 0
        self.refresh_failures = 0
        self.rejected = 0

    # ------------------------------------------------------------------ the snapshot
    def _read(self, started: float, box: dict) -> None:
        """One provider read, on a worker thread. Never raises; stores the outcome."""
        try:
            snapshot = self._provider.fetch(self.config.netuid)
            if snapshot.netuid != self.config.netuid:
                raise SnapshotError("SENDER_SNAPSHOT_WRONG_NETUID")
            box["snapshot"] = snapshot
        except Exception as error:  # noqa: BLE001 - a provider fault is a code, never a message
            box["error"] = str(error) if isinstance(error, SnapshotError) \
                else type(error).__name__
        finally:
            self._finish(started, box)

    def _finish(self, started: float, box: dict) -> None:
        with self._lock:
            if self._inflight_since == started:
                self._inflight_since = None
            snapshot = box.get("snapshot")
            if snapshot is None:
                self.refresh_failures += 1
                self._next_attempt = self._clock() + self.config.retry_seconds
                LOG.warning("sender policy: snapshot refresh failed (%s)",
                            box.get("error", "UNKNOWN"))
            elif self._snapshot is None or started >= self._started_at:
                self._snapshot, self._started_at, self._next_attempt = snapshot, started, 0.0
                self.refreshes += 1
                LOG.info("sender policy: %d permitted hotkeys on netuid %d (block %s)",
                         len(snapshot.permitted), snapshot.netuid, snapshot.block)
                if not snapshot.permitted:
                    LOG.warning("sender policy: NO hotkey holds validator_permit on netuid %d; "
                                "every sender except the probe key is refused", snapshot.netuid)
        box["done"].set()

    def _start_read(self, now: float) -> dict:
        box: dict = {"done": threading.Event()}
        self._inflight_since = now
        thread = threading.Thread(target=self._read, args=(now, box), daemon=True,
                                  name="sn87-sender-snapshot")
        self._worker = thread
        thread.start()
        return box

    def load(self) -> PermitSnapshot:
        """Take the first snapshot (start-up), waiting at most ``fetch_timeout_seconds``.
        Raises ``SnapshotError`` if it cannot be read, so a miner never starts with an
        allowlist it cannot fill."""
        with self._lock:
            box = self._start_read(self._clock())
        if not box["done"].wait(self.config.fetch_timeout_seconds):
            raise SnapshotError("SENDER_SNAPSHOT_TIMEOUT")
        with self._lock:
            if self._snapshot is None:
                raise SnapshotError(box.get("error", "SENDER_SNAPSHOT_READ_FAILED"))
            return self._snapshot

    def wait_idle(self, timeout: float = 5.0) -> None:
        """Wait for a read in progress (for tests and orderly shutdown)."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def _current(self) -> PermitSnapshot:
        """The snapshot to decide with. Takes the lock only briefly and never reads the chain;
        a due refresh is handed to a background thread."""
        now = self._clock()
        with self._lock:
            snapshot = self._snapshot
            due = snapshot is None or now - self._started_at >= self.config.refresh_seconds
            hung = (self._inflight_since is not None
                    and now - self._inflight_since > self.config.fetch_timeout_seconds)
            if due and now >= self._next_attempt and (self._inflight_since is None or hung):
                self._start_read(now)        # a hung read is abandoned, not waited for
            if snapshot is None or now - self._started_at > self.config.stale_limit:
                raise BoundaryError("SENDER_POLICY_UNAVAILABLE")
            return snapshot

    # ------------------------------------------------------------------ the decision
    def _sender_bucket(self, hotkey: str) -> TokenBucket:
        with self._lock:
            bucket = self._sender_buckets.get(hotkey)
            if bucket is None:
                bucket = TokenBucket(self.config.sender_rate_per_second,
                                     self.config.sender_burst, clock=self._clock)
                self._sender_buckets[hotkey] = bucket
            return bucket

    def admit(self, hotkey_ss58: str) -> None:
        """Return if ``hotkey_ss58`` (already signature-verified) may send now; else raise a
        ``BoundaryError`` with ``SENDER_NOT_PERMITTED``, ``SENDER_POLICY_UNAVAILABLE``,
        ``SENDER_RATE_LIMITED`` or ``GLOBAL_RATE_LIMITED``."""
        if hotkey_ss58 not in self._trusted and hotkey_ss58 not in self._current().permitted:
            self.rejected += 1
            raise BoundaryError("SENDER_NOT_PERMITTED")
        if not self._sender_bucket(hotkey_ss58).take():
            raise BoundaryError("SENDER_RATE_LIMITED")
        if not self._bucket.take():
            raise BoundaryError("GLOBAL_RATE_LIMITED")

    def describe(self) -> str:
        trusted = self.config.trusted
        probe = (f"; trusted senders (skip the permit check only): {', '.join(trusted)}"
                 if trusted else "")
        where = getattr(self._provider, "describe", None)
        chain = f"; chain {where()}" if callable(where) else ""
        snapshot = self._snapshot
        empty = (" WARNING: no hotkey holds validator_permit on this netuid, so every sender "
                 "except the probe key is refused." if snapshot is not None
                 and not snapshot.permitted else "")
        return (f"sender policy: validator_permit allowlist on netuid {self.config.netuid}"
                f"{probe}{chain}; refresh {self.config.refresh_seconds:g}s; per sender "
                f"{self.config.sender_rate_per_second:g}/s burst {self.config.sender_burst}; "
                f"global {self.config.rate_per_second:g}/s burst {self.config.burst}.{empty}")

    @property
    def snapshot_size(self) -> int | None:
        return None if self._snapshot is None else len(self._snapshot.permitted)


class AllowAnySender:
    """The opt-out: any key whose signature verifies may send (global rate limit only).
    For local and development use. Constructing it logs a warning."""

    mode = "allow-any-sender"

    def __init__(self, *, rate_per_second: float = DEFAULT_RATE_PER_SECOND,
                 burst: int = DEFAULT_BURST, clock: Callable[[], float] = time.monotonic) -> None:
        self._bucket = TokenBucket(rate_per_second, burst, clock=clock)
        self.rate_per_second, self.burst = rate_per_second, burst
        LOG.warning("sender policy: ALLOWLIST DISABLED (--allow-any-sender): any key with a "
                    "valid signature may send; local and development use only")

    def load(self) -> None:
        return None

    def admit(self, hotkey_ss58: str) -> None:
        if not self._bucket.take():
            raise BoundaryError("GLOBAL_RATE_LIMITED")

    def describe(self) -> str:
        return ("sender policy: ALLOWLIST DISABLED (--allow-any-sender); local and development "
                f"use only; global limit {self.rate_per_second:g}/s burst {self.burst}")


class PolicyAdmission:
    """A nonce store that asks the sender policy before the real replay store.

    The SDK calls ``check_and_store`` after the signature has verified, so ``hotkey_ss58`` is
    the authenticated sender. A refusal raises before anything is written to the store."""

    def __init__(self, store: Any, policy: SenderPolicy | AllowAnySender) -> None:
        self._store, self._policy = store, policy

    def check_and_store(self, hotkey_ss58: str, nonce_ns: int) -> bool:
        self._policy.admit(hotkey_ss58)
        return self._store.check_and_store(hotkey_ss58, nonce_ns)
