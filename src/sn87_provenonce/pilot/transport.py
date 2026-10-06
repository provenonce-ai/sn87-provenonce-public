"""Exact-byte SDK authentication and shared fail-closed replay admission."""
from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass
from typing import Any

from bittensor import http_auth
from valkey import Valkey
from valkey.backoff import NoBackoff
from valkey.exceptions import ResponseError
from valkey.retry import Retry

VERSION = "gra-transport/0.1"
PATH = "/v1/assurance"
MAX_AGE = 10.0
ALLOWED_SKEW = 2.0
MAX_DEADLINE_MS = 15_000


class BoundaryError(Exception):
    """A stable public error code; never carry underlying adapter exceptions."""


# Every new store process is quarantined for a complete freshness window. This also
# protects against a replay after loss of volatile nonce keys on store restart.
_ADMIT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1])*1000 + math.floor(tonumber(clock[2])/1000)
local generation = redis.call('GET', KEYS[2])
local prefix = ARGV[3] .. ':'
if not generation or string.sub(generation,1,string.len(prefix)) ~= prefix then
  redis.call('SET', KEYS[2], prefix .. tostring(now + tonumber(ARGV[1])))
  return -1
end
local ready_at = tonumber(string.sub(generation,string.len(prefix)+1))
if now < ready_at then return -1 end
if ARGV[4] == 'probe' then
  if redis.call('SET', KEYS[1], '1', 'NX', 'PX', ARGV[1]) then return 1 end
  return 0
end
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
local count = tonumber(redis.call('GET', KEYS[3]) or '0')
if count >= tonumber(ARGV[2]) then return -2 end
local accepted = redis.call('SET', KEYS[1], '1', 'NX', 'PX', ARGV[1])
if not accepted then return 0 end
if redis.call('INCR', KEYS[3]) == 1 then redis.call('PEXPIRE', KEYS[3], 60000) end
return 1
"""


@dataclass(frozen=True)
class TransportConfig:
    receiver_ss58: str
    max_body_bytes: int = 262_144
    max_age: float = MAX_AGE
    allowed_skew: float = ALLOWED_SKEW
    max_deadline_ms: int = MAX_DEADLINE_MS
    body_timeout_seconds: float = 3.0
    max_inflight: int = 8

    def __post_init__(self) -> None:
        if not self.receiver_ss58 or not 1 <= self.max_body_bytes <= 262_144:
            raise ValueError("invalid transport limits")
        if not all(math.isfinite(v) and v > 0 for v in (
            self.max_age, self.allowed_skew, self.body_timeout_seconds,
        )) or self.max_deadline_ms < 1 or self.max_inflight < 1:
            raise ValueError("invalid transport limits")


class SharedReplayStore:
    """Atomic Valkey-compatible admission shared across workers and restarts.

    Keys contain only digests and non-secret domains. The SDK calls this adapter
    after verifying the signature. A connection error, unexpected reply, store
    generation change, rate limit, insufficient retention, or any eviction policy
    other than ``noeviction`` (including one that CONFIG GET cannot confirm) fails
    closed.
    """

    def __init__(
        self, client: Any, *, receiver: str, domain: str,
        retention: float = 13.0, max_age: float = MAX_AGE,
        allowed_skew: float = ALLOWED_SKEW, per_minute: int = 120,
    ) -> None:
        if not math.isfinite(retention) or retention < max_age + allowed_skew:
            raise ValueError("replay retention is shorter than accepted freshness")
        if not receiver or domain not in {"request", "response"} or per_minute < 1:
            raise ValueError("invalid replay configuration")
        self.client, self.receiver, self.domain = client, receiver, domain
        self.retention = retention
        self.retention_ms = math.ceil(retention * 1000)
        self.per_minute = per_minute
        self.prefix = "sn87:gra:replay:" + hashlib.sha256(
            (domain + "\0" + receiver).encode()
        ).hexdigest()

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> SharedReplayStore:
        # Disable automatic retries: a timeout after an accepted SET is ambiguous.
        client = Valkey.from_url(
            url, socket_timeout=0.5, socket_connect_timeout=0.5,
            retry=Retry(NoBackoff(), 0), retry_on_timeout=False,
            max_connections=16, decode_responses=True,
        )
        return cls(client, **kwargs)

    def _admit(self, sender: str, nonce: int, *, probe: bool = False) -> bool:
        digest = hashlib.sha256(
            (self.domain + "\0" + self.receiver + "\0" + sender + "\0" + str(nonce)).encode()
        ).hexdigest()
        sender_digest = hashlib.sha256(sender.encode()).hexdigest()
        try:
            run_id = self.client.info("server")["run_id"]
            if not isinstance(run_id, str) or not run_id:
                raise BoundaryError("REPLAY_STORE_UNAVAILABLE")
            self._require_noeviction()
            result = self.client.eval(
                _ADMIT, 3, self.prefix + ":" + digest, self.prefix + ":generation",
                self.prefix + ":rate:" + sender_digest,
                self.retention_ms, self.per_minute, run_id, "probe" if probe else "admit",
            )
        except BoundaryError:
            raise
        except Exception:
            raise BoundaryError("REPLAY_STORE_UNAVAILABLE") from None
        if type(result) is not int:
            raise BoundaryError("REPLAY_STORE_UNAVAILABLE")
        if result == -1:
            raise BoundaryError("REPLAY_STORE_WARMING")
        if result == -2:
            raise BoundaryError("RATE_LIMITED")
        if result not in {0, 1}:
            raise BoundaryError("REPLAY_STORE_UNAVAILABLE")
        return result == 1

    def _require_noeviction(self) -> None:
        """Nonce keys carry TTLs, so any eviction policy could silently drop a live
        nonce under memory pressure and re-admit a replay. Only ``noeviction`` (the
        store refuses writes instead) is acceptable. Checked on every admission since
        CONFIG SET can change the policy without a restart."""
        try:
            config = self.client.config_get("maxmemory-policy")
        except ResponseError:
            # CONFIG disabled/renamed or denied by ACL: the policy cannot be proven.
            raise BoundaryError("REPLAY_STORE_EVICTION_POLICY_UNVERIFIABLE") from None
        if not isinstance(config, dict) or "maxmemory-policy" not in config:
            raise BoundaryError("REPLAY_STORE_EVICTION_POLICY_UNVERIFIABLE")
        if config["maxmemory-policy"] != "noeviction":
            raise BoundaryError("REPLAY_STORE_EVICTION_POLICY_UNSAFE")

    def check_and_store(self, hotkey_ss58: str, nonce_ns: int) -> bool:
        return self._admit(hotkey_ss58, nonce_ns)

    def ready(self) -> bool:
        return self._admit("readiness", secrets.randbits(128), probe=True)


def verify_bytes(
    headers: Any, body: bytes, *, method: str, path: str,
    config: TransportConfig, store: SharedReplayStore, now_ns: int | None = None,
) -> Any:
    try:
        return http_auth.verify(
            headers, body, method=method, path=path,
            self_hotkey_ss58=config.receiver_ss58, max_age=config.max_age,
            allowed_skew=config.allowed_skew, require_receiver=True,
            nonce_store=store, now_ns=now_ns,
        )
    except http_auth.ReplayedRequest:
        raise BoundaryError("REPLAYED_REQUEST") from None
    except http_auth.AuthError:
        raise BoundaryError("AUTHENTICATION_FAILED") from None
    except BoundaryError:
        raise
    except Exception:
        raise BoundaryError("AUTHENTICATION_UNAVAILABLE") from None
