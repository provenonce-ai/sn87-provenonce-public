#!/usr/bin/env python3
"""Contest window generator: commit a seed, open fresh instances, reveal the seed after close.

SHADOW TOOLING. Nothing here reads or writes a weight, a chain, or the active scoring profile.
Testnet weights are unchanged by anything this script produces.

  contest_window.py --phase init-master --master-seed-file F
  contest_window.py --phase commit --schedule S --master-seed-file F --out-dir D
  contest_window.py --phase open --window ID --schedule S --master-seed-file F --out-dir D
  contest_window.py --phase truth --window ID --out-dir D                     (private only)
  contest_window.py --phase reveal --window ID --schedule S --master-seed-file F --out-dir D
  contest_window.py --phase publish-truth --window ID --schedule S --out-dir D \
                    --publish-closed-window-truth
  contest_window.py --phase verify --window ID --out-dir D

(run each as ``uv run python scripts/contest_window.py ...``)

Protocol (full text in docs/protocol/contest-windows.md):

* COMMIT, before a window opens. The operator holds a master seed. The window seed is
  ``HMAC-SHA256(master, frame(WINDOW_SEED_DOMAIN, window_id))``. The public record holds
  ``seed_commitment = sha256(frame(COMMIT_DOMAIN, window_id, seed))`` and a ``spec_commitment``
  over the window specification (profile, family mix, times, generator id). Neither discloses
  the seed or the mix.
* OPEN, while the window runs. Instance ``i`` gets its own key by HKDF-Expand from the window
  seed, with the window id and the position in the info string, and builds its capsule with
  ``institutional_v02.fixtures.build_case`` through its ``identifier`` hook. Miners receive
  capsules only: no family, no track, no truth.
* TRUTH, private. The private reference executors derive truth per instance. The public tree
  has no executor, so this phase fails there with an explicit message.
* REVEAL, after the window closes. The seed and the specification are published. Anyone
  recomputes every instance and checks both commitments (``verify``).
* PUBLISH-TRUTH, after reveal, and only under an explicit policy flag. Per-case truth of a
  CLOSED window is the open decision recorded in ADR-0020; the default is to refuse.

Protocol versions. ``sn87-contest-generator/0.1`` (schemas ``/0.1``) is the original protocol and
stays readable and verifiable. ``/0.2`` adds, for every new schedule:

* the opening block hash is mixed into the window seed (the master seed alone no longer fixes the
  instances, so they are unpredictable to the operator as well as to miners until the window opens);
* the truth commitment is made at OPEN, published with ``cases_commitment`` in the capsules file and
  carried in every request to a miner; ``publish-truth`` and ``verify`` refuse a truth hash that
  differs from it;
* every window has a ``reveal_deadline`` that the shadow service enforces.
The block hash is an input (``--block-number`` and ``--block-hash``, or an injected read-only
provider); nothing here reads a chain.

Every phase checks the clock against the window's times (``--now`` overrides the clock for tests
and replays; it is a guard against operator mistakes, not against an operator who lies about it).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import struct
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sn87_provenonce import profile as profiles
from sn87_provenonce.canonical import canonical_bytes, check_timestamp, evidence_commitment
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable

GENERATOR_ID = "sn87-contest-generator/0.1"
GENERATOR_ID_2 = "sn87-contest-generator/0.2"
GENERATOR_CLASS = "IC-APPROVAL-APPLICABILITY"
LEDGER_NAME = "commitments-ledger.json"
SCHEDULE_SCHEMA = "sn87-contest-schedule/0.1"
COMMITMENTS_SCHEMA = "sn87-contest-commitments/0.1"
CAPSULES_SCHEMA = "sn87-contest-capsules/0.1"
CASES_SCHEMA = "sn87-contest-cases/0.1"
REVEAL_SCHEMA = "sn87-contest-reveal/0.1"
SCHEDULE_SCHEMA_2 = "sn87-contest-schedule/0.2"
COMMITMENTS_SCHEMA_2 = "sn87-contest-commitments/0.2"
CAPSULES_SCHEMA_2 = "sn87-contest-capsules/0.2"
CASES_SCHEMA_2 = "sn87-contest-cases/0.2"
REVEAL_SCHEMA_2 = "sn87-contest-reveal/0.2"
BUNDLE_SCHEMA = "sn87-reveal-bundle/0.1"
BEACON_RULE = "FIRST_BLOCK_AT_OR_AFTER_OPENS_AT"
CLAIM = "SHADOW_TOOLING_NOT_WIRED_TO_WEIGHTS"
WINDOW_SEED_DOMAIN = b"SN87:CONTEST:WINDOW_SEED/v1"
COMMIT_DOMAIN = b"SN87:CONTEST:SEED_COMMITMENT/v1"
PRESEED_DOMAIN = b"SN87:CONTEST:PRESEED/v2"
PRESEED_COMMIT_DOMAIN = b"SN87:CONTEST:PRESEED_COMMITMENT/v2"
WINDOW_SEED_DOMAIN_2 = b"SN87:CONTEST:WINDOW_SEED_WITH_BLOCK/v2"
SPEC_DOMAIN = b"SN87:CONTEST:SPEC_COMMITMENT/v1"
SPEC_SALT_DOMAIN = b"SN87:CONTEST:SPEC_SALT/v1"
SCHEDULE_DOMAIN = b"SN87:CONTEST:SCHEDULE_COMMITMENT/v1"
INSTANCE_DOMAIN = b"SN87:CONTEST:INSTANCE/v1"
ORDER_DOMAIN = b"SN87:CONTEST:ORDER/v1"
VARIANT_DOMAIN = b"SN87:CONTEST:WRONG_SCOPE_VARIANT/v1"
CASES_DOMAIN = b"SN87:CONTEST:CASES_COMMITMENT/v1"
TRUTH_DOMAIN = b"SN87:CONTEST:TRUTH_COMMITMENT/v1"
DEMO_PREFIX = "demo-"
WINDOW_ID = r"[a-z0-9][a-z0-9-]{2,47}"
TRACKS = ("scored", "diagnostic")
# Existing families come from build_case. The two wrong-scope families build a fresh_review
# (clear) or stale_authority (finding) record and then move one action's approval out of scope
# (mission, recipient or artifact); the references abstain on them and a naive method does not.
BASE_FAMILIES = ("stale_authority", "fresh_review", "incomplete")
WRONG_SCOPE = {"wrong_scope_stale": "stale_authority", "wrong_scope_clear": "fresh_review"}
FAMILIES = (*BASE_FAMILIES, *WRONG_SCOPE)
SCOPE_DIMENSIONS = ("recipient", "mission", "artifact")
# Phases, in the order of a window's life. Each maps to the error code raised when the clock
# or the policy forbids it.
PHASES = ("init-master", "commit", "open", "truth", "reveal", "publish-truth", "verify",
          "verify-bundle")


class PhaseError(RuntimeError):
    """A phase was requested at a time or under a policy that forbids it."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# --- framing, HKDF, commitments ---------------------------------------------------------------

def frame(*parts: bytes | str) -> bytes:
    """Length-prefixed concatenation, so no two part lists produce the same bytes."""
    out = b""
    for part in parts:
        data = part.encode() if isinstance(part, str) else part
        out += struct.pack(">I", len(data)) + data
    return out


def digest(domain: bytes, *parts: bytes | str) -> str:
    return "sha256:" + hashlib.sha256(frame(domain, *parts)).hexdigest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF-Expand with HMAC-SHA256; the window seed is the pseudorandom key."""
    if not 1 <= length <= 255 * 32:
        raise ValueError("invalid HKDF length")
    out, block = b"", b""
    for counter in range(1, -(-length // 32) + 1):
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
    return out[:length]


def window_seed(master: bytes, schedule_id: str, window_id: str) -> bytes:
    """Bound to the schedule id as well as the window id, so the same master seed and window id in
    a second schedule give different seeds and different instances."""
    return hmac.new(master, frame(WINDOW_SEED_DOMAIN, schedule_id, window_id),
                    hashlib.sha256).digest()


def seed_commitment(window_id: str, seed: bytes) -> str:
    return digest(COMMIT_DOMAIN, window_id, seed)


# --- protocol versions ------------------------------------------------------------------------

_VERSIONS = {SCHEDULE_SCHEMA: 1, SCHEDULE_SCHEMA_2: 2, COMMITMENTS_SCHEMA: 1,
             COMMITMENTS_SCHEMA_2: 2, CAPSULES_SCHEMA: 1, CAPSULES_SCHEMA_2: 2,
             CASES_SCHEMA: 1, CASES_SCHEMA_2: 2, REVEAL_SCHEMA: 1, REVEAL_SCHEMA_2: 2}


def version_of(document: Any) -> int:
    """The protocol version (1 or 2) a schedule, commitments, capsules, cases or reveal document
    belongs to. An unknown schema is refused."""
    version = _VERSIONS.get(document.get("schema_version")) if isinstance(document, dict) else None
    if version is None:
        raise ValueError("unknown contest protocol schema")
    return version


BLOCK_HASH = re.compile(r"0x[0-9a-f]{64}")
NETWORK = re.compile(r"[a-z0-9][a-z0-9:._-]{2,95}")
MAX_REVEAL_DELAY = timedelta(days=7)  # a schedule may not push a reveal deadline further out
TRUTH_SALT_DOMAIN = b"SN87:CONTEST:TRUTH_SALT/v2"
SALT = re.compile(r"[0-9a-f]{32}")
OPEN_RECORD_SCHEMA = "sn87-contest-open-record/0.1"


def check_beacon_rule(beacon: Any) -> dict[str, str]:
    if (not isinstance(beacon, dict) or set(beacon) != {"network", "rule"}
            or beacon["rule"] != BEACON_RULE or not isinstance(beacon["network"], str)
            or NETWORK.fullmatch(beacon["network"]) is None):
        raise ValueError("invalid beacon rule")
    return {"network": beacon["network"], "rule": beacon["rule"]}


def _ms(stamp: str) -> int:
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


def check_beacon(beacon: Any) -> dict[str, Any]:
    """The opening block: number, hash, its timestamp and its parent's timestamp (ms), and
    optionally ``depth`` (blocks between it and the head when it was read) and ``manual`` (typed
    in by an operator instead of read through a provider). An input, never read from a chain
    here."""
    required = {"number", "hash", "time_ms", "parent_time_ms"}
    if (not isinstance(beacon, dict) or not required <= set(beacon)
            or set(beacon) - required - {"depth", "manual"}):
        raise ValueError("invalid opening block record")
    ints = [beacon[k] for k in ("number", "time_ms", "parent_time_ms")]
    if (any(type(v) is not int or v < 0 for v in ints)
            or not isinstance(beacon["hash"], str) or BLOCK_HASH.fullmatch(beacon["hash"]) is None
            or ("depth" in beacon and (type(beacon["depth"]) is not int or beacon["depth"] < 0))
            or ("manual" in beacon and beacon["manual"] is not True)):
        raise ValueError("invalid opening block record")
    return dict(beacon)


def check_beacon_window(beacon: dict[str, Any], opens_at: str) -> None:
    """Offline check that the block is the first at or after ``opens_at``: its parent is before
    and it is at or after. The one block this holds for is the one the rule names."""
    if not beacon["parent_time_ms"] < _ms(opens_at) <= beacon["time_ms"]:
        raise ValueError("BEACON_NOT_FIRST_BLOCK_AT_OR_AFTER_OPENS_AT")


def preseed(master: bytes, schedule_id: str, window_id: str) -> bytes:
    """Protocol 0.2: the part of the window seed the operator can compute before the window opens.
    It is committed at commit time; the window seed also needs the opening block hash."""
    return hmac.new(master, frame(PRESEED_DOMAIN, schedule_id, window_id), hashlib.sha256).digest()


def truth_salt_2(pre: bytes, window_id: str) -> str:
    """Protocol 0.2: the truth salt is derived from the pre-seed, so the truth file can be made
    again identically (given the same reference) and a lost file does not lose the commitment."""
    return hmac.new(pre, frame(TRUTH_SALT_DOMAIN, window_id), hashlib.sha256).digest()[:16].hex()


def preseed_commitment(window_id: str, pre: bytes) -> str:
    return digest(PRESEED_COMMIT_DOMAIN, window_id, pre)


def window_seed_2(pre: bytes, schedule_id: str, window_id: str, beacon: dict[str, Any]) -> bytes:
    """Protocol 0.2 window seed: the pre-seed mixed with the opening block hash. Unknown to the
    operator until that block exists; a pure function of public inputs once the pre-seed is
    revealed."""
    b = check_beacon(beacon)
    return hmac.new(pre, frame(WINDOW_SEED_DOMAIN_2, schedule_id, window_id, str(b["number"]),
                               bytes.fromhex(b["hash"][2:])), hashlib.sha256).digest()


FINALITY_DEPTH = 12  # blocks behind the head the opening block must be, when no finalized head


def find_beacon_block(reader: Any, opens_at: str, *, depth: int = FINALITY_DEPTH) -> dict[str, Any]:
    """The first block whose timestamp is at or after ``opens_at`` (ISO Z), by bisection over a
    read-only ``reader`` with ``block_time_ms(n)`` and ``block_hash(n)`` and either
    ``finalized_block()`` or ``current_block()``. The search stops at the finalized head, else at
    ``head - depth`` (``FINALITY_DEPTH``), so a block that can still be replaced is never chosen.
    After the choice the hash and the two times are read again and must agree. The record carries
    ``depth``: blocks between it and the head used."""
    target_ms = _ms(opens_at)
    if hasattr(reader, "finalized_block"):
        high, margin = reader.finalized_block(), 0
    else:
        margin = depth
        high = reader.current_block() - margin
    if high < 1 or reader.block_time_ms(high) < target_ms:
        raise PhaseError("BEACON_BLOCK_NOT_YET_FINAL", "no final block yet at or after opening")
    low = 0
    while low < high:
        mid = (low + high) // 2
        if reader.block_time_ms(mid) >= target_ms:
            high = mid
        else:
            low = mid + 1
    number = low
    first = (reader.block_hash(number), reader.block_time_ms(number),
             reader.block_time_ms(number - 1) if number else 0)
    again = (reader.block_hash(number), reader.block_time_ms(number),
             reader.block_time_ms(number - 1) if number else 0)
    if first != again:
        raise PhaseError("BEACON_READ_INCONSISTENT", "the opening block read differently twice")
    beacon = check_beacon({"number": number, "hash": first[0], "time_ms": first[1],
                           "parent_time_ms": first[2], "depth": margin or 0})
    check_beacon_window(beacon, opens_at)
    return beacon


def spec_commitment(spec: dict[str, Any], seed: bytes) -> str:
    """Hiding: the specification (including the family mix) is committed together with a salt
    derived from the secret window seed, so the commitment cannot be guessed from candidate mixes
    before reveal."""
    salt = hmac.new(seed, frame(SPEC_SALT_DOMAIN, spec["window_id"]), hashlib.sha256).digest()
    return digest(SPEC_DOMAIN, canonical_bytes(spec), salt)


def cases_commitment(entries: list[dict[str, Any]]) -> str:
    """Binds the ordered (qid, capsule commitment) pairs of a window."""
    return digest(CASES_DOMAIN, canonical_bytes(
        [[e["qid"], e["capsule_commitment"]] for e in entries]))


def truth_commitment(entries: list[dict[str, Any]], *, window_id: str, seed_commitment: str,
                     cases_commitment: str, salt: str) -> str:
    """Salted commitment to the ordered per-case truth. The salt is random, made at truth time
    and kept private until publish-truth, so the commitment hides the truth (the states of a window
    have few possible values). It is bound to the window's seed commitment (published before the
    window) and to the capsule-set commitment (published at open), so it is not a free-standing
    hash that any file could satisfy."""
    return digest(TRUTH_DOMAIN, window_id, seed_commitment, cases_commitment, bytes.fromhex(salt),
                  canonical_bytes([[e["qid"], e.get("truth"), e.get("reference_failure")]
                                   for e in entries]))


# --- schedule and specification ---------------------------------------------------------------

def _mix_from_profile(profile_id: str) -> list[dict[str, Any]]:
    document = profiles.load(profile_id).document
    scored = [{"family": f, "track": "scored", "count": n}
              for f, n in document["assignment"].items()]
    diagnostic = [{"family": f, "track": "diagnostic", "count": n}
                  for f, n in document["diagnostics"].items()]
    return scored + diagnostic


# Presets other than "profile" are shadow experiments. "messy" puts the abstain-truth families
# (incomplete record, wrong scope) in the scored track, which is the open decision in ADR-0019.
PRESETS = {
    "profile": _mix_from_profile,
    "messy": lambda _profile_id: [
        {"family": "stale_authority", "track": "scored", "count": 10},
        {"family": "fresh_review", "track": "scored", "count": 6},
        {"family": "wrong_scope_stale", "track": "scored", "count": 3},
        {"family": "wrong_scope_clear", "track": "scored", "count": 3},
        {"family": "incomplete", "track": "scored", "count": 2},
        {"family": "incomplete", "track": "diagnostic", "count": 4},
        {"family": "wrong_scope_stale", "track": "diagnostic", "count": 2},
        {"family": "wrong_scope_clear", "track": "diagnostic", "count": 2},
    ],
}


def check_mix(mix: Any) -> list[dict[str, Any]]:
    if not isinstance(mix, list) or not mix:
        raise ValueError("mix must be a non-empty list")
    out = []
    for item in mix:
        if (not isinstance(item, dict) or set(item) != {"family", "track", "count"}
                or item["family"] not in FAMILIES or item["track"] not in TRACKS
                or type(item["count"]) is not int or not 1 <= item["count"] <= 64):
            raise ValueError(f"invalid mix entry: {item!r}")
        out.append({"family": item["family"], "track": item["track"], "count": item["count"]})
    if sum(i["count"] for i in out) > 256 or not any(i["track"] == "scored" for i in out):
        raise ValueError("mix needs scored cases and at most 256 in total")
    return out


def load_schedule(path: Path, *, allow_demo: bool = False) -> dict[str, Any]:
    schedule = json.loads(path.read_text("utf-8"))
    if (not isinstance(schedule, dict)
            or schedule.get("schema_version") not in (SCHEDULE_SCHEMA, SCHEDULE_SCHEMA_2)):
        raise ValueError("schedule schema")
    version = version_of(schedule)
    allowed = {"schema_version", "schedule_id", "profile_id", "mix_preset", "mix", "windows"}
    if version == 2:
        allowed.add("beacon")
    if (not {"schedule_id", "profile_id", "windows"} <= set(schedule)
            or (version == 2 and "beacon" not in schedule) or set(schedule) - allowed):
        raise ValueError("schedule schema")
    if version == 2:
        check_beacon_rule(schedule["beacon"])
    if not isinstance(schedule["schedule_id"], str) or re.fullmatch(
            WINDOW_ID, schedule["schedule_id"]) is None:
        raise ValueError("invalid schedule id")
    # An unregistered or altered profile fails closed; so does a profile of another class.
    if profiles.load(schedule["profile_id"]).class_id != GENERATOR_CLASS:
        raise ValueError(f"PROFILE_CLASS_MISMATCH: the generator builds {GENERATOR_CLASS}")
    windows = schedule["windows"]
    if not isinstance(windows, list) or not windows:
        raise ValueError("schedule needs at least one window")
    seen = set()
    previous_close = ""
    for w in windows:
        fields = {"window_id", "opens_at", "closes_at"} | (
            {"reveal_deadline"} if version == 2 else set())
        if not isinstance(w, dict) or set(w) != fields:
            raise ValueError("window fields")
        wid = w["window_id"]
        if not isinstance(wid, str) or re.fullmatch(WINDOW_ID, wid) is None or wid in seen:
            raise ValueError(f"invalid or repeated window id: {wid!r}")
        if wid.startswith(DEMO_PREFIX) and not allow_demo:
            raise ValueError("DEMO_WINDOW_ID_RESERVED")
        if not wid.startswith(DEMO_PREFIX) and allow_demo:
            raise ValueError("demo schedules use the demo- prefix only")
        seen.add(wid)
        check_timestamp(w["opens_at"])
        check_timestamp(w["closes_at"])
        if not w["opens_at"] < w["closes_at"] or w["opens_at"] < previous_close:
            raise ValueError("windows must be ordered and must not overlap")
        if version == 2:
            check_timestamp(w["reveal_deadline"])
            if w["reveal_deadline"] < w["closes_at"]:
                raise ValueError("REVEAL_DEADLINE_BEFORE_CLOSE")
            if (_ms(w["reveal_deadline"]) - _ms(w["closes_at"])
                    > MAX_REVEAL_DELAY.total_seconds() * 1000):
                raise ValueError("REVEAL_DEADLINE_TOO_LATE")
        previous_close = w["closes_at"]
    return schedule


def window_spec(schedule: dict[str, Any], window: dict[str, str]) -> dict[str, Any]:
    pid = schedule["profile_id"]
    if "mix" in schedule:
        mix = check_mix(schedule["mix"])
        preset = "explicit"
    else:
        preset = schedule.get("mix_preset", "profile")
        if preset not in PRESETS:
            raise ValueError(f"unknown mix preset {preset!r}")
        mix = check_mix(PRESETS[preset](pid))
    spec = {"generator": GENERATOR_ID, "schedule_id": schedule["schedule_id"],
            "window_id": window["window_id"],
            "opens_at": window["opens_at"], "closes_at": window["closes_at"],
            "profile_id": pid, "profile_commitment": profiles.load(pid).commitment,
            "mix_preset": preset, "mix": mix}
    if version_of(schedule) == 2:
        spec |= {"generator": GENERATOR_ID_2, "beacon": check_beacon_rule(schedule["beacon"]),
                 "reveal_deadline": window["reveal_deadline"]}
    return spec


def read_master(path: Path) -> bytes:
    text = path.read_text("ascii").strip()
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ValueError("master seed file must hold 64 lowercase hex characters")
    return bytes.fromhex(text)


# --- instances --------------------------------------------------------------------------------

def _stream(key: bytes):
    counter = 0

    def next_identifier() -> str:
        nonlocal counter
        counter += 1
        return hmac.new(key, struct.pack(">I", counter), hashlib.sha256).hexdigest()[:32]

    return next_identifier


def _order(seed: bytes, spec: dict[str, Any]) -> list[tuple[str, str]]:
    """The (family, track) of each position: the mix expanded, then shuffled by seeded keys."""
    flat = [(i["family"], i["track"]) for i in spec["mix"] for _ in range(i["count"])]
    keyed = sorted((hkdf_expand(seed, frame(ORDER_DOMAIN, spec["window_id"], struct.pack(">I", n)),
                                8), n) for n in range(len(flat)))
    return [flat[n] for _, n in keyed]


def build_instance(seed: bytes, spec: dict[str, Any], position: int, family: str) -> dict[str, Any]:
    wid = spec["window_id"]
    identifier = _stream(hkdf_expand(
        seed, frame(INSTANCE_DOMAIN, wid, struct.pack(">I", position)), 32))
    capsule = build_case(WRONG_SCOPE.get(family, family), identifier=identifier,
                         timestamp=spec["opens_at"])
    variant = None
    if family in WRONG_SCOPE:
        pick = hkdf_expand(seed, frame(VARIANT_DOMAIN, wid, struct.pack(">I", position)), 2)
        dimension, index = SCOPE_DIMENSIONS[pick[0] % 3], pick[1] % 3
        action = [e for e in capsule["events"] if e["kind"] == "ACTION"][index]
        if dimension == "artifact":
            action["artifact_commitment"] = "sha256:" + hashlib.sha256(
                identifier().encode()).hexdigest()
        else:
            action["scope"] = dict(action["scope"], **{dimension: identifier()})
        capsule["evidence_commitment"] = evidence_commitment(capsule)
        variant = {"dimension": dimension, "action_episode": index + 1}
    return {"capsule": capsule, "variant": variant}


def build_window(seed: bytes, spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Every instance of a window, in position order. A pure function of seed and spec."""
    entries = []
    for position, (family, track) in enumerate(_order(seed, spec)):
        built = build_instance(seed, spec, position, family)
        capsule = built["capsule"]
        entries.append({"position": position, "qid": capsule["qid"], "family": family,
                        "track": track, "wrong_scope_variant": built["variant"],
                        "capsule_commitment": capsule["evidence_commitment"],
                        "capsule": capsule})
    if len({e["qid"] for e in entries}) != len(entries):
        raise ValueError("DUPLICATE_QID")
    return entries


def capsules_document(spec: dict[str, Any], entries: list[dict[str, Any]], *,
                      truth_commitment: str | None = None,
                      beacon: dict[str, Any] | None = None) -> dict[str, Any]:
    """What miners receive: capsules in position order, with nothing about family or track.

    Protocol 0.2 also carries the truth commitment (fixed at open, salted, so it hides the truth),
    the opening block and the reveal deadline."""
    document = {"schema_version": CAPSULES_SCHEMA, "window_id": spec["window_id"],
                "opens_at": spec["opens_at"], "closes_at": spec["closes_at"],
                "cases_commitment": cases_commitment(entries),
                "capsules": [e["capsule"] for e in entries]}
    if spec["generator"] == GENERATOR_ID_2:
        if truth_commitment is None or beacon is None:
            raise ValueError("protocol 0.2 capsules need the truth commitment and the block")
        document |= {"schema_version": CAPSULES_SCHEMA_2, "generator": GENERATOR_ID_2,
                     "truth_commitment": truth_commitment, "beacon": check_beacon(beacon),
                     "reveal_deadline": spec["reveal_deadline"]}
    return document


def request_commitments(capsules: dict[str, Any]) -> dict[str, str] | None:
    """The window record carried in every request to a miner (protocol 0.2); None for 0.1."""
    if version_of(capsules) != 2:
        return None
    return {"generator": capsules["generator"], "window_id": capsules["window_id"],
            "cases_commitment": capsules["cases_commitment"],
            "truth_commitment": capsules["truth_commitment"]}


def check_truth_against_open(truth: dict[str, Any], capsules: dict[str, Any] | None) -> None:
    """Protocol 0.2: the truth hash must be the one published at open (in the capsules file and in
    every request). A 0.1 window has no such hash. A missing open record is a refusal, not a
    pass."""
    if capsules is None:
        raise PhaseError("OPEN_RECORD_MISSING", "the capsules file published at open is needed")
    if version_of(capsules) == 1:
        return
    if (truth["truth_commitment"] != capsules["truth_commitment"]
            or truth["cases_commitment"] != capsules["cases_commitment"]):
        raise PhaseError("TRUTH_HASH_DIFFERS_FROM_OPEN",
                         "the truth is not the one committed when the window opened")


def cases_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("position", "qid", "family", "track", "wrong_scope_variant", "capsule_commitment")
    return [{k: e[k] for k in keys} for e in entries]


# --- phase guard ------------------------------------------------------------------------------

def guard(phase: str, window: dict[str, str], now: str, *, revealed: bool = False,
          publish_policy: bool = False) -> None:
    """Raise ``PhaseError`` unless ``phase`` is allowed for ``window`` at ``now`` (ISO Z)."""
    check_timestamp(now)
    opens, closes = window["opens_at"], window["closes_at"]
    if phase == "commit" and now >= opens:
        raise PhaseError("COMMIT_AFTER_OPEN", "seeds are committed before the window opens")
    if phase == "open" and now < opens:
        raise PhaseError("OPEN_BEFORE_WINDOW", "capsules are not generated before the window opens")
    if phase == "open" and now >= closes:
        raise PhaseError("OPEN_AFTER_CLOSE", "the window has closed")
    if phase == "reveal" and now < closes:
        raise PhaseError("REVEAL_BEFORE_CLOSE", "the seed stays hidden until the window closes")
    if phase == "results" and now < closes:
        raise PhaseError("RESULTS_BEFORE_CLOSE", "per-window results are published after close")
    if phase == "results-truth-derived":
        # Truth-derived aggregates (agreement, confusion, failures, truth state counts) follow the
        # same rule as per-case truth: closed, revealed and explicitly authorized.
        guard("publish-truth", window, now, revealed=revealed, publish_policy=publish_policy)
    if phase == "publish-truth":
        if now < closes:
            raise PhaseError("TRUTH_PUBLICATION_BEFORE_CLOSE",
                             "hidden-window truth is never published while the window is open")
        if not revealed:
            raise PhaseError("TRUTH_PUBLICATION_BEFORE_REVEAL", "reveal the seed first")
        if not publish_policy:
            raise PhaseError("TRUTH_PUBLICATION_NOT_AUTHORIZED",
                             "closed-window truth publication is an open decision (ADR-0020); "
                             "pass --publish-closed-window-truth only once it is decided")


# --- files ------------------------------------------------------------------------------------

def dumps(document: Any) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_new(path: Path, text: str, *, mode: int = 0o644) -> None:
    """Create-only: an existing file is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def names(window_id: str) -> dict[str, str]:
    stem = f"window_{window_id}"
    return {"capsules": f"{stem}.capsules.json", "cases": f"{stem}.cases.private.json",
            "truth_private": f"{stem}.truth.private.json", "reveal": f"{stem}.reveal.json",
            "truth": f"{stem}.truth.json"}


def commitments_document(schedule: dict[str, Any], master: bytes) -> dict[str, Any]:
    version = version_of(schedule)
    rows = []
    for w in schedule["windows"]:
        spec = window_spec(schedule, w)
        if version == 1:
            key = window_seed(master, schedule["schedule_id"], w["window_id"])
            commitment = seed_commitment(w["window_id"], key)
        else:
            # 0.2: the commitment is to the pre-seed; the window seed also needs the opening block
            key = preseed(master, schedule["schedule_id"], w["window_id"])
            commitment = preseed_commitment(w["window_id"], key)
        row = {"window_id": w["window_id"], "opens_at": w["opens_at"],
               "closes_at": w["closes_at"], "seed_commitment": commitment,
               "spec_commitment": spec_commitment(spec, key)}
        if version == 2:
            row["reveal_deadline"] = w["reveal_deadline"]
        rows.append(row)
    document = {"schema_version": COMMITMENTS_SCHEMA, "claim": CLAIM, "generator": GENERATOR_ID,
                "schedule_id": schedule["schedule_id"], "profile_id": schedule["profile_id"],
                "profile_commitment": profiles.load(schedule["profile_id"]).commitment,
                "windows": rows,
                "schedule_commitment": digest(SCHEDULE_DOMAIN, canonical_bytes(rows))}
    if version == 2:
        document |= {"schema_version": COMMITMENTS_SCHEMA_2, "generator": GENERATOR_ID_2,
                     "beacon": check_beacon_rule(schedule["beacon"])}
    return document


def reveal_document(schedule: dict[str, Any], window: dict[str, str], master: bytes,
                    beacon: dict[str, Any] | None = None) -> dict[str, Any]:
    if version_of(schedule) == 1:
        return {"schema_version": REVEAL_SCHEMA, "window_id": window["window_id"],
                "seed": window_seed(master, schedule["schedule_id"], window["window_id"]).hex(),
                "spec": window_spec(schedule, window)}
    if beacon is None:
        raise PhaseError("BEACON_REQUIRED", "a 0.2 reveal needs the opening block record")
    pre = preseed(master, schedule["schedule_id"], window["window_id"])
    return {"schema_version": REVEAL_SCHEMA_2, "window_id": window["window_id"],
            "preseed": pre.hex(), "beacon": check_beacon(beacon),
            "seed": window_seed_2(pre, schedule["schedule_id"], window["window_id"], beacon).hex(),
            "spec": window_spec(schedule, window)}


def check_reveal(commitments: dict[str, Any], reveal: dict[str, Any]) -> list[dict[str, Any]]:
    """The commitment checks a public reader runs. Returns the instances it regenerated."""
    version = version_of(commitments)
    if reveal.get("schema_version") != (REVEAL_SCHEMA, REVEAL_SCHEMA_2)[version - 1]:
        raise ValueError("reveal schema")
    rows = {w["window_id"]: w for w in commitments["windows"]}
    row = rows.get(reveal["window_id"])
    if row is None:
        raise ValueError("WINDOW_NOT_COMMITTED")
    if commitments["schedule_commitment"] != digest(
            SCHEDULE_DOMAIN, canonical_bytes(commitments["windows"])):
        raise ValueError("SCHEDULE_COMMITMENT_MISMATCH")
    if commitments["profile_commitment"] != profiles.load(commitments["profile_id"]).commitment:
        raise ValueError("PROFILE_COMMITMENT_MISMATCH")
    seed, spec = bytes.fromhex(reveal["seed"]), reveal["spec"]
    if version == 1:
        if seed_commitment(reveal["window_id"], seed) != row["seed_commitment"]:
            raise ValueError("SEED_COMMITMENT_MISMATCH")
        key = seed
    else:
        key = bytes.fromhex(reveal["preseed"])
        if preseed_commitment(reveal["window_id"], key) != row["seed_commitment"]:
            raise ValueError("SEED_COMMITMENT_MISMATCH")
        if window_seed_2(key, commitments["schedule_id"], reveal["window_id"],
                         reveal["beacon"]).hex() != reveal["seed"]:
            raise ValueError("SEED_NOT_DERIVED_FROM_PRESEED_AND_BLOCK_HASH")
    if spec_commitment(spec, key) != row["spec_commitment"]:
        raise ValueError("SPEC_COMMITMENT_MISMATCH")
    if (spec["generator"], spec["window_id"], spec["opens_at"], spec["closes_at"],
            spec["profile_id"], spec["schedule_id"]) != (
            (GENERATOR_ID, GENERATOR_ID_2)[version - 1], row["window_id"], row["opens_at"],
            row["closes_at"], commitments["profile_id"], commitments["schedule_id"]):
        raise ValueError("SPEC_DOES_NOT_MATCH_COMMITMENT_ROW")
    if version == 2 and (spec["reveal_deadline"] != row["reveal_deadline"]
                         or spec["beacon"] != commitments["beacon"]):
        raise ValueError("SPEC_DOES_NOT_MATCH_COMMITMENT_ROW")
    if version == 2:
        check_beacon_window(check_beacon(reveal["beacon"]), spec["opens_at"])
    check_mix(spec["mix"])
    return build_window(seed, spec)


def check_ledger(path: Path, document: dict[str, Any], no_prior_reason: str | None,
                 prior_files: list[str]) -> dict[str, Any]:
    """The reuse ledger kept next to the master seed file: every (schedule id, window id) and seed
    commitment ever committed from it. It is on by default. A first commit, with no ledger yet,
    needs ``--no-prior-ledger REASON`` so that skipping the check is a stated choice."""
    if path.exists():
        ledger = json.loads(path.read_text("utf-8"))
    elif no_prior_reason:
        ledger = {"schema_version": "sn87-contest-ledger/0.1", "entries": [],
                  "no_prior_ledger_reason": no_prior_reason}
    else:
        raise PhaseError("PRIOR_LEDGER_REQUIRED",
                         f"no {path.name} beside the master seed file; "
                         "pass --no-prior-ledger REASON "
                         "for a first commit")
    entries = list(ledger["entries"])
    for prior_path in prior_files:
        prior = json.loads(Path(prior_path).read_text("utf-8"))
        entries += [{"schedule_id": prior["schedule_id"], "window_id": w["window_id"],
                     "seed_commitment": w["seed_commitment"]} for w in prior["windows"]]
    ids = {(e["schedule_id"], e["window_id"]) for e in entries}
    seeds = {e["seed_commitment"] for e in entries}
    for w in document["windows"]:
        if (document["schedule_id"], w["window_id"]) in ids or w["seed_commitment"] in seeds:
            raise PhaseError("WINDOW_OR_SEED_REUSED", f"{w['window_id']} was committed before")
    return ledger


def check_committed(path: Path, schedule: dict[str, Any], window: dict[str, str],
                    master: bytes) -> None:
    """A window opens or reveals only if its commitments were published and still match."""
    if not path.exists():
        raise PhaseError("WINDOW_NOT_COMMITTED", "run the commit phase first")
    published = json.loads(path.read_text("utf-8"))
    expected = commitments_document(schedule, master)
    if published != expected:
        raise PhaseError("COMMITMENTS_DO_NOT_MATCH", "seed, schedule or specification changed")


# --- truth (private) --------------------------------------------------------------------------

def derive_truth(entries: list[dict[str, Any]], reference=None) -> list[dict[str, Any]]:
    """Truth per instance from the private reference executors.

    ``reference`` defaults to the bound class's reference, which imports the private executors
    at the call and raises ``PrivateReferenceExecutorUnavailable`` in the public tree. A
    reference that raises on one instance is recorded as a reference failure for that instance
    (it leaves the admitted supply) and never retried.
    """
    if reference is None:
        from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY
        reference = IC_APPROVAL_APPLICABILITY.reference
    out = []
    for e in entries:
        row = {"position": e["position"], "qid": e["qid"], "family": e["family"],
               "track": e["track"], "wrong_scope_variant": e["wrong_scope_variant"],
               "capsule_commitment": e["capsule_commitment"]}
        try:
            row["truth"], row["reference_failure"] = reference(e["capsule"]), None
        except PrivateReferenceExecutorUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - one instance's failure is recorded, not hidden
            row["truth"], row["reference_failure"] = None, type(exc).__name__
        out.append(row)
    return out


def truth_document(window_id: str, seed_commitment: str, cases_commitment: str, salt: str,
                   rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Truth with its salted commitment. The salt travels in this document, so the private file
    holds it and the public file (written by publish-truth) reveals it."""
    return {"schema_version": "sn87-contest-truth/0.1", "window_id": window_id,
            "seed_commitment": seed_commitment, "cases_commitment": cases_commitment,
            "salt": salt,
            "truth_commitment": truth_commitment(
                rows, window_id=window_id, seed_commitment=seed_commitment,
                cases_commitment=cases_commitment, salt=salt),
            "cases": rows}


def check_truth_document(document: dict[str, Any], commitments: dict[str, Any] | None = None
                         ) -> None:
    """Recompute the salted commitment; with ``commitments`` also bind it to the published row."""
    if not isinstance(document.get("salt"), str) or SALT.fullmatch(document["salt"]) is None:
        raise ValueError("TRUTH_SALT_INVALID")
    expected = truth_commitment(
        document["cases"], window_id=document["window_id"],
        seed_commitment=document["seed_commitment"],
        cases_commitment=document["cases_commitment"], salt=document["salt"])
    if document["truth_commitment"] != expected:
        raise ValueError("TRUTH_COMMITMENT_MISMATCH")
    if cases_commitment(document["cases"]) != document["cases_commitment"]:
        raise ValueError("CASES_COMMITMENT_MISMATCH")
    if commitments is not None:
        row = next((w for w in commitments["windows"]
                    if w["window_id"] == document["window_id"]), None)
        if row is None or row["seed_commitment"] != document["seed_commitment"]:
            raise ValueError("TRUTH_NOT_BOUND_TO_PUBLISHED_COMMITMENT")


# --- reveal deadline and reveal bundle --------------------------------------------------------

def reveal_overdue(closes_at: str, reveal_deadline: str | None, now: str, *,
                   revealed: bool, grace_hours: int = 24) -> bool:
    """True when ``now`` is past the reveal deadline and the seed has not been published. A
    window without a deadline (protocol 0.1) is held to ``closes_at`` plus ``grace_hours``."""
    if revealed:
        return False
    if reveal_deadline is None:
        deadline = (datetime.strptime(closes_at, "%Y-%m-%dT%H:%M:%SZ")
                    + timedelta(hours=grace_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        deadline = reveal_deadline
    check_timestamp(now)
    return now > deadline


def load_open_records(directory: Path) -> dict[str, dict[str, Any]]:
    """The published open records found in ``directory``: ``window_<id>.open.json`` files, else the
    open record read from ``window_<id>.capsules.json`` (protocol 0.2 capsules files)."""
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("window_*.open.json")):
        doc = json.loads(path.read_text("utf-8"))
        if doc.get("schema_version") != OPEN_RECORD_SCHEMA:
            raise ValueError("open record schema")
        records[doc["window_id"]] = doc
    for path in sorted(directory.glob("window_*.capsules.json")):
        doc = json.loads(path.read_text("utf-8"))
        if doc.get("schema_version") == CAPSULES_SCHEMA_2 and doc["window_id"] not in records:
            records[doc["window_id"]] = open_record(doc)
    return records


def reveal_bundle(schedule: dict[str, Any], master: bytes, commitments: dict[str, Any], now: str,
                  *, open_records: dict[str, dict[str, Any]] | None = None,
                  closed_only: bool = False) -> dict[str, Any]:
    """Every closed window's reveal, derived from the master seed and the committed schedule and
    checked against the published commitments, as one document.

    Protocol 0.2: a window with a published open record is ``OPENED`` and carries its reveal and
    that record (the opening block comes from the record, never from free-form input); a window
    with none is an explicit ``NOT_OPENED`` entry with no seed. Refuses a schedule or master seed
    that does not reproduce the published commitments, and a window that has not closed (unless
    ``closed_only``, which leaves it out and says so)."""
    check_timestamp(now)
    if commitments_document(schedule, master) != commitments:
        raise PhaseError("COMMITMENTS_DO_NOT_MATCH",
                         "the master seed and schedule do not reproduce the published commitments")
    version = version_of(schedule)
    entries, left_out = [], []
    for w in schedule["windows"]:
        wid = w["window_id"]
        if now < w["closes_at"]:
            if not closed_only:
                raise PhaseError("REVEAL_BEFORE_CLOSE", f"{wid} has not closed")
            left_out.append(wid)
            continue
        if version == 1:
            reveal = reveal_document(schedule, w, master)
            check_reveal(commitments, reveal)
            entries.append({"window_id": wid, "status": "REVEALED", "reveal": reveal})
            continue
        record = (open_records or {}).get(wid)
        if record is None:
            entries.append({"window_id": wid, "status": "NOT_OPENED"})
            continue
        reveal = reveal_document(schedule, w, master, record["beacon"])
        regenerated = check_reveal(commitments, reveal)
        if cases_commitment(regenerated) != record["cases_commitment"]:
            raise PhaseError("OPEN_RECORD_DIFFERS_FROM_REVEAL", wid)
        entries.append({"window_id": wid, "status": "OPENED", "reveal": reveal,
                        "open_record": record})
    return {"schema_version": BUNDLE_SCHEMA, "schedule_id": schedule["schedule_id"],
            "schedule_commitment": commitments["schedule_commitment"],
            "protocol": (GENERATOR_ID, GENERATOR_ID_2)[version - 1],
            "windows": entries, "not_closed_and_left_out": left_out}


def check_reveal_bundle(bundle: dict[str, Any], commitments: dict[str, Any], *,
                        open_records: dict[str, dict[str, Any]] | None = None,
                        min_protocol: int | None = None, now: str | None = None,
                        allow_partial: bool = False) -> dict[str, list[str]]:
    """The public check of a reveal bundle. Every revealed window must reproduce its published
    seed (or pre-seed) commitment and specification commitment; for protocol 0.2 each must also
    match the open record published when it opened (``open_records``, required), and a window the
    bundle calls ``NOT_OPENED`` must have no published open record. Closed windows the bundle does
    not cover are an error unless ``allow_partial``. ``min_protocol`` refuses an older protocol.
    Malformed input is a ``ValueError``."""
    try:
        return _check_reveal_bundle(bundle, commitments, open_records, min_protocol, now,
                                    allow_partial)
    except (TypeError, AttributeError, KeyError, IndexError) as error:
        raise ValueError(f"BUNDLE_MALFORMED: {type(error).__name__}") from error


def _check_reveal_bundle(bundle: dict[str, Any], commitments: dict[str, Any],
                         open_records: dict[str, dict[str, Any]] | None,
                         min_protocol: int | None, now: str | None, allow_partial: bool
                         ) -> dict[str, list[str]]:
    if bundle.get("schema_version") != BUNDLE_SCHEMA:
        raise ValueError("bundle schema")
    version = version_of(commitments)
    if min_protocol is not None and version < min_protocol:
        raise ValueError("PROTOCOL_BELOW_MINIMUM")
    if (bundle["schedule_id"] != commitments["schedule_id"]
            or bundle["schedule_commitment"] != commitments["schedule_commitment"]):
        raise ValueError("BUNDLE_NOT_FOR_THESE_COMMITMENTS")
    if commitments["schedule_commitment"] != digest(
            SCHEDULE_DOMAIN, canonical_bytes(commitments["windows"])):
        raise ValueError("SCHEDULE_COMMITMENT_MISMATCH")
    rows = {w["window_id"]: w for w in commitments["windows"]}
    verified: list[str] = []
    not_opened: list[str] = []
    for entry in bundle["windows"]:
        wid = entry["window_id"]
        if wid not in rows:
            raise ValueError("WINDOW_NOT_COMMITTED")
        if wid in verified or wid in not_opened:
            raise ValueError("BUNDLE_REPEATS_A_WINDOW")
        status = entry["status"]
        if status == "NOT_OPENED":
            if version != 2:
                raise ValueError("BUNDLE_STATUS_NOT_FOR_THIS_PROTOCOL")
            if open_records is not None and wid in open_records:
                raise ValueError("BUNDLE_SAYS_NOT_OPENED_BUT_OPEN_RECORD_EXISTS")
            if set(entry) != {"window_id", "status"}:
                raise ValueError("BUNDLE_NOT_OPENED_ENTRY_CARRIES_DATA")
            not_opened.append(wid)
            continue
        reveal = entry["reveal"]
        if reveal["window_id"] != wid:
            raise ValueError("BUNDLE_ENTRY_WINDOW_MISMATCH")
        regenerated = check_reveal(commitments, reveal)
        if status == "REVEALED" and version == 1:
            verified.append(wid)
            continue
        if status != "OPENED" or version != 2:
            raise ValueError("BUNDLE_STATUS_NOT_FOR_THIS_PROTOCOL")
        record = entry["open_record"]
        if (record["window_id"] != wid or record["beacon"] != reveal["beacon"]
                or record["cases_commitment"] != cases_commitment(regenerated)):
            raise ValueError("OPEN_RECORD_DIFFERS_FROM_REVEAL")
        if open_records is None:
            raise PhaseError("OPEN_RECORDS_REQUIRED",
                             "pass the published open records (--open-dir) to tie each reveal "
                             "to what was published when the window opened")
        if open_records.get(wid) != record:
            raise ValueError("OPEN_RECORD_DIFFERS_FROM_PUBLISHED" if wid in open_records
                             else "OPEN_RECORD_MISSING")
        verified.append(wid)
    clock = now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    uncovered = [w["window_id"] for w in commitments["windows"]
                 if w["window_id"] not in verified and w["window_id"] not in not_opened]
    closed_uncovered = [w for w in uncovered if rows[w]["closes_at"] <= clock]
    if closed_uncovered and not allow_partial:
        raise PhaseError("BUNDLE_INCOMPLETE",
                         f"closed windows not covered: {', '.join(closed_uncovered)}")
    return {"verified": verified, "not_opened": not_opened, "not_covered": uncovered}


# --- command line -----------------------------------------------------------------------------

def _now(value: str | None) -> str:
    return value or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window(schedule: dict[str, Any], window_id: str) -> dict[str, str]:
    for w in schedule["windows"]:
        if w["window_id"] == window_id:
            return w
    raise ValueError(f"window {window_id!r} is not in the schedule")


def _beacon_input(args: argparse.Namespace, window: dict[str, str],
                  block_provider: Callable[[str], dict[str, Any]] | None) -> dict[str, Any] | None:
    """The opening block record from the injected read-only provider, else (only with
    ``--allow-manual-block``) from the flags, marked ``manual``. A block typed in by hand is
    refused by default: it is how an operator would choose a seed."""
    manual = (args.block_hash, args.block_number, args.block_time_ms, args.parent_block_time_ms)
    if any(v is not None for v in manual):
        if not args.allow_manual_block:
            raise PhaseError("MANUAL_BLOCK_REFUSED", "pass --allow-manual-block to type in a "
                             "block by hand; the record is marked manual")
        print("MANUAL_BLOCK: the opening block was typed in by hand and is marked manual in the "
              "record", file=sys.stderr)
        return check_beacon({"number": args.block_number, "hash": args.block_hash,
                             "time_ms": args.block_time_ms,
                             "parent_time_ms": args.parent_block_time_ms, "manual": True})
    if block_provider is not None:
        return check_beacon(block_provider(window["opens_at"]))
    return None


def open_record(capsules: dict[str, Any]) -> dict[str, Any]:
    """What a verifier ties a reveal to: the cases commitment, the truth commitment and the
    opening block published when the window opened (protocol 0.2)."""
    return {"schema_version": OPEN_RECORD_SCHEMA, "window_id": capsules["window_id"],
            "cases_commitment": capsules["cases_commitment"],
            "truth_commitment": capsules["truth_commitment"], "beacon": capsules["beacon"],
            "reveal_deadline": capsules["reveal_deadline"]}


def _open_2(schedule: dict[str, Any], window: dict[str, str], spec: dict[str, Any],
            master: bytes, out: Path, files: dict[str, str],
            beacon_input: dict[str, Any] | None, reference: Callable[..., Any] | None
            ) -> list[str]:
    """Open a protocol 0.2 window: bind the opening block into the seed, fix the truth now and
    publish its hash with the cases commitment. After a crash the recorded block is reused; a
    different block is refused (``BEACON_CONFLICT``), so the block cannot be re-chosen."""
    wid = window["window_id"]
    if (out / files["capsules"]).exists():
        raise PhaseError("WINDOW_ALREADY_OPENED", wid)
    cases_path, truth_path = out / files["cases"], out / files["truth_private"]
    if cases_path.exists():
        beacon = check_beacon(json.loads(cases_path.read_text("utf-8"))["beacon"])
        if beacon_input is not None and check_beacon(beacon_input) != beacon:
            raise PhaseError("BEACON_CONFLICT", "this window already recorded its opening block")
    elif beacon_input is None:
        raise PhaseError("BEACON_REQUIRED", "inject a read-only block provider (or, as a marked "
                         "exception, pass the block with --allow-manual-block)")
    else:
        beacon = check_beacon(beacon_input)
    check_beacon_window(beacon, window["opens_at"])
    pre = preseed(master, schedule["schedule_id"], wid)
    seed = window_seed_2(pre, schedule["schedule_id"], wid, beacon)
    entries = build_window(seed, spec)
    row = next(w for w in commitments_document(schedule, master)["windows"]
               if w["window_id"] == wid)
    print(f"OPENING_BLOCK {wid} number={beacon['number']} hash={beacon['hash']} "
          f"time_ms={beacon['time_ms']}{' MANUAL' if beacon.get('manual') else ''}")
    if not cases_path.exists():
        write_new(cases_path, dumps({"schema_version": CASES_SCHEMA_2, "window_id": wid,
                                     "beacon": beacon, "cases": cases_entries(entries)}),
                  mode=0o600)
    if truth_path.exists():
        truth = json.loads(truth_path.read_text("utf-8"))
        check_truth_document(truth)
        if (truth["window_id"], truth["seed_commitment"], truth["cases_commitment"],
                truth["salt"]) != (wid, row["seed_commitment"], cases_commitment(entries),
                                   truth_salt_2(pre, wid)):
            raise PhaseError("TRUTH_FIXED_FOR_OTHER_CASES", wid)
    else:
        truth = truth_document(wid, row["seed_commitment"], cases_commitment(entries),
                               truth_salt_2(pre, wid), derive_truth(entries, reference))
        write_new(truth_path, dumps(truth), mode=0o600)
    write_new(out / files["capsules"], dumps(capsules_document(
        spec, entries, truth_commitment=truth["truth_commitment"], beacon=beacon)))
    return [str(cases_path), str(truth_path), str(out / files["capsules"])]


def _remake_truth_2(schedule: dict[str, Any], window: dict[str, str], spec: dict[str, Any],
                    master: bytes, out: Path, files: dict[str, str],
                    reference: Callable[..., Any] | None) -> list[str]:
    """Protocol 0.2: make a lost private truth file again. The salt is derived, so with the same
    reference the commitment is the one published at open; any other result is refused."""
    wid = window["window_id"]
    if (out / files["truth_private"]).exists():
        raise PhaseError("TRUTH_FIXED_AT_OPEN", "the truth file exists; it is not made again")
    if not (out / files["capsules"]).exists() or not (out / files["cases"]).exists():
        raise PhaseError("WINDOW_NOT_OPENED", wid)
    opened = json.loads((out / files["capsules"]).read_text("utf-8"))
    beacon = check_beacon(opened["beacon"])
    pre = preseed(master, schedule["schedule_id"], wid)
    entries = build_window(window_seed_2(pre, schedule["schedule_id"], wid, beacon), spec)
    row = next(w for w in commitments_document(schedule, master)["windows"]
               if w["window_id"] == wid)
    truth = truth_document(wid, row["seed_commitment"], cases_commitment(entries),
                           truth_salt_2(pre, wid), derive_truth(entries, reference))
    check_truth_against_open(truth, opened)
    write_new(out / files["truth_private"], dumps(truth), mode=0o600)
    return [str(out / files["truth_private"])]


def run(args: argparse.Namespace, *, reference: Callable[..., Any] | None = None,
        block_provider: Callable[[str], dict[str, Any]] | None = None) -> list[str]:
    """Run one phase; returns the paths written. Raises PhaseError / ValueError on refusal.

    ``reference`` (truth) and ``block_provider`` (opening block) are injection seams: tests pass
    fakes, a deployment passes the private executors and a read-only chain reader."""
    out = Path(args.out_dir) if args.out_dir else None
    phase, now = args.phase, _now(args.now)
    if phase == "init-master":
        path = Path(args.master_seed_file)
        write_new(path, os.urandom(32).hex() + "\n", mode=0o600)
        return [str(path)]
    if phase == "verify-bundle":
        # The outsider's check of a whole-schedule reveal bundle: the bundle, the published
        # commitments file and (protocol 0.2) the published open records.
        if not args.bundle or not args.commitments:
            raise ValueError("--bundle and --commitments are required")
        commitments = json.loads(Path(args.commitments).read_text("utf-8"))
        records = load_open_records(Path(args.open_dir)) if args.open_dir else None
        report = check_reveal_bundle(
            json.loads(Path(args.bundle).read_text("utf-8")), commitments, open_records=records,
            min_protocol=args.min_protocol, now=now, allow_partial=args.allow_partial)
        for window_id in report["verified"]:
            print(f"verified {window_id}: commitments match"
                  + (" and the open record" if records is not None else ""))
        for window_id in report["not_opened"]:
            print(f"not opened: {window_id} (no seed was drawn; no open record is published)")
        for window_id in report["not_covered"]:
            if window_id not in report["not_opened"]:
                print(f"not covered by the bundle: {window_id}")
        if commitments.get("beacon"):
            print("NOTE: the opening block hashes and times are inputs to the seeds. This check "
                  "does not read a chain: compare each block number, hash and time with a node "
                  "of the network.")
        if args.index:
            index = json.loads(Path(args.index).read_text("utf-8"))
            overdue = [w["window_id"] for w in index["windows"]
                       if w.get("reveal_status") == "REVEAL_OVERDUE"
                       and w["window_id"] not in report["verified"]]
            for schedule_entry in index.get("schedules", []):
                voided = schedule_entry.get("voided")
                if voided:
                    print(f"{schedule_entry['schedule_id']}: {voided['count']} voided "
                          f"{voided['reasons']}")
            if overdue:
                raise PhaseError("REVEAL_OVERDUE_IN_INDEX", ", ".join(overdue))
        return []
    if out is None:
        raise ValueError("--out-dir is required")
    wid = args.window
    if wid is not None and re.fullmatch(WINDOW_ID, wid) is None:
        raise ValueError("invalid window id")
    if phase == "commit":
        schedule = load_schedule(Path(args.schedule), allow_demo=args.demo)
        for w in schedule["windows"]:
            guard("commit", w, now)
        document = commitments_document(schedule, read_master(Path(args.master_seed_file)))
        # The ledger lives beside the master seed file (the operator's persistent location).
        ledger_path = Path(args.master_seed_file).with_name(LEDGER_NAME)
        ledger = check_ledger(ledger_path, document, args.no_prior_ledger,
                              args.prior_commitments or [])
        target = out / "commitments.json"
        # Ledger first: a crash between the writes blocks a retry rather than allowing reuse.
        ledger["entries"] += [{"schedule_id": document["schedule_id"], "window_id": w["window_id"],
                               "seed_commitment": w["seed_commitment"]}
                              for w in document["windows"]]
        ledger_path.write_text(dumps(ledger), encoding="utf-8")
        write_new(target, dumps(document))
        return [str(target), str(ledger_path)]
    if not wid:
        raise ValueError("--window is required")
    files = names(wid)
    if phase == "truth":
        if not (out / "commitments.json").exists():
            raise PhaseError("WINDOW_NOT_COMMITTED", "run the commit phase first")
        commitments = json.loads((out / "commitments.json").read_text("utf-8"))
        row = next((w for w in commitments["windows"] if w["window_id"] == wid), None)
        if row is None:
            raise PhaseError("WINDOW_NOT_COMMITTED", f"{wid} is not in commitments.json")
        if version_of(commitments) == 2:
            if not args.schedule:
                raise PhaseError("TRUTH_FIXED_AT_OPEN", "protocol 0.2 fixes the truth when the "
                                 "window opens; making a lost file again needs --schedule")
            sched = load_schedule(Path(args.schedule), allow_demo=args.demo)
            win = _window(sched, wid)
            return _remake_truth_2(sched, win, window_spec(sched, win),
                                   read_master(Path(args.master_seed_file)), out, files, reference)
        if not (out / files["cases"]).exists() or not (out / files["capsules"]).exists():
            raise PhaseError("WINDOW_NOT_OPENED", "run the open phase first")
        cases = json.loads((out / files["cases"]).read_text("utf-8"))
        capsules = json.loads((out / files["capsules"]).read_text("utf-8"))
        entries = [dict(row, capsule=capsule)
                   for row, capsule in zip(cases["cases"], capsules["capsules"], strict=True)]
        target = out / files["truth_private"]
        document = truth_document(wid, row["seed_commitment"], capsules["cases_commitment"],
                                  os.urandom(16).hex(), derive_truth(entries))
        write_new(target, dumps(document), mode=0o600)
        return [str(target)]
    if phase == "verify":
        commitments = json.loads((out / "commitments.json").read_text("utf-8"))
        reveal = json.loads((out / files["reveal"]).read_text("utf-8"))
        regenerated = check_reveal(commitments, reveal)
        report = [f"commitments verified for {wid}: {len(regenerated)} instances regenerated"]
        published = out / files["capsules"]
        if published.exists():
            doc = json.loads(published.read_text("utf-8"))
            if canonical_bytes(doc["capsules"]) != canonical_bytes(
                    [e["capsule"] for e in regenerated]):
                raise ValueError("PUBLISHED_CAPSULES_DIFFER_FROM_REGENERATED")
            report.append("published capsules equal the regenerated capsules")
        if version_of(commitments) == 2:
            opened = json.loads(published.read_text("utf-8")) if published.exists() else None
            if opened is not None and (
                    opened.get("beacon") != reveal["beacon"]
                    or opened["cases_commitment"] != cases_commitment(regenerated)):
                raise ValueError("OPEN_RECORD_DIFFERS_FROM_REVEAL")
        truth_path = out / files["truth"]
        if truth_path.exists():
            doc = json.loads(truth_path.read_text("utf-8"))
            if [(c["qid"], c["family"], c["track"]) for c in doc["cases"]] != [
                    (e["qid"], e["family"], e["track"]) for e in regenerated]:
                raise ValueError("PUBLISHED_TRUTH_CASES_DIFFER_FROM_REGENERATED")
            check_truth_document(doc, commitments)
            if version_of(commitments) == 2:
                check_truth_against_open(doc, opened)
                report.append("published truth hash equals the hash published at open")
            report.append("published truth cases match the regenerated instances")
        print("\n".join(report))
        return []
    schedule = load_schedule(Path(args.schedule), allow_demo=args.demo)
    window = _window(schedule, wid)
    spec = window_spec(schedule, window)
    if phase == "publish-truth":
        private = out / files["truth_private"]
        reveal_path = out / files["reveal"]
        guard(phase, window, now, revealed=reveal_path.exists(),
              publish_policy=args.publish_closed_window_truth)
        # The reveal must verify against the earlier commitment: existence is not enough.
        commitments = json.loads((out / "commitments.json").read_text("utf-8"))
        regenerated = check_reveal(commitments, json.loads(reveal_path.read_text("utf-8")))
        document = json.loads(private.read_text("utf-8"))
        check_truth_document(document, commitments)
        if version_of(commitments) == 2:
            opened = out / files["capsules"]
            check_truth_against_open(
                document, json.loads(opened.read_text("utf-8")) if opened.exists() else None)
        if [(c["qid"], c["family"], c["track"], c["capsule_commitment"])
                for c in document["cases"]] != [
                (e["qid"], e["family"], e["track"], e["capsule_commitment"])
                for e in regenerated]:
            raise ValueError("TRUTH_CASES_DIFFER_FROM_REGENERATED_INSTANCES")
        target = out / files["truth"]
        write_new(target, dumps(document))
        return [str(target)]
    guard(phase, window, now)
    master = read_master(Path(args.master_seed_file))
    check_committed(out / "commitments.json", schedule, window, master)
    version = version_of(schedule)
    if phase == "open" and version == 2:
        return _open_2(schedule, window, spec, master, out, files,
                       _beacon_input(args, window, block_provider), reference)
    if phase == "open":
        entries = build_window(window_seed(master, schedule["schedule_id"], wid), spec)
        done = []
        for key, document, mode in (
                ("capsules", capsules_document(spec, entries), 0o644),
                ("cases", {"schema_version": CASES_SCHEMA, "window_id": wid,
                           "cases": cases_entries(entries)}, 0o600)):
            write_new(out / files[key], dumps(document), mode=mode)
            done.append(str(out / files[key]))
        return done
    if phase == "reveal":
        target = out / files["reveal"]
        beacon = None
        if version == 2:
            opened = out / files["cases"]
            beacon = (json.loads(opened.read_text("utf-8"))["beacon"] if opened.exists()
                      else _beacon_input(args, window, block_provider))
        write_new(target, dumps(reveal_document(schedule, window, master, beacon)))
        return [str(target)]
    raise ValueError(f"unknown phase {phase!r}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--phase", required=True, choices=PHASES)
    p.add_argument("--schedule", help="schedule JSON (commit, open, reveal, publish-truth)")
    p.add_argument("--master-seed-file", help="file holding the master seed (64 hex characters)")
    p.add_argument("--window", help="window id")
    p.add_argument("--out-dir", help="directory for the phase's output files")
    p.add_argument("--now", help="override the clock (ISO 8601 UTC, whole seconds, Z)")
    p.add_argument("--prior-commitments", action="append",
                   help="earlier commitments.json (repeatable), checked with the ledger")
    p.add_argument("--no-prior-ledger", metavar="REASON",
                   help="commit without an existing reuse ledger (a first commit); states why")
    p.add_argument("--allow-manual-block", action="store_true",
                   help="protocol 0.2: accept an opening block typed in below (marked manual)")
    p.add_argument("--block-number", type=int, help="manual opening block: number")
    p.add_argument("--block-hash", help="manual opening block: 0x plus 64 lowercase hex")
    p.add_argument("--block-time-ms", type=int, help="manual opening block: timestamp (ms)")
    p.add_argument("--parent-block-time-ms", type=int,
                   help="manual opening block: its parent's timestamp (ms)")
    p.add_argument("--bundle", help="verify-bundle: a reveal bundle file")
    p.add_argument("--commitments", help="verify-bundle: the published commitments file")
    p.add_argument("--open-dir", help="verify-bundle: folder of published open records")
    p.add_argument("--min-protocol", type=int, choices=(1, 2),
                   help="verify-bundle: refuse a bundle of an older protocol")
    p.add_argument("--allow-partial", action="store_true",
                   help="verify-bundle: accept closed windows the bundle does not cover")
    p.add_argument("--index", help="verify-bundle: the published index.json (checks the "
                   "REVEAL_OVERDUE flag)")
    p.add_argument("--demo", action="store_true", help="demo- window ids only (public seed)")
    p.add_argument("--publish-closed-window-truth", action="store_true",
                   help="policy flag for publish-truth; the decision is open (ADR-0020)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        for path in run(args):
            print(path)
    except (PhaseError, PrivateReferenceExecutorUnavailable, ValueError, FileExistsError,
            FileNotFoundError, KeyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
