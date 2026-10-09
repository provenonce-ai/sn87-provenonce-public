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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sn87_provenonce import profile as profiles
from sn87_provenonce.canonical import canonical_bytes, check_timestamp, evidence_commitment
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable

GENERATOR_ID = "sn87-contest-generator/0.1"
GENERATOR_CLASS = "IC-APPROVAL-APPLICABILITY"
LEDGER_NAME = "commitments-ledger.json"
SCHEDULE_SCHEMA = "sn87-contest-schedule/0.1"
COMMITMENTS_SCHEMA = "sn87-contest-commitments/0.1"
CAPSULES_SCHEMA = "sn87-contest-capsules/0.1"
CASES_SCHEMA = "sn87-contest-cases/0.1"
REVEAL_SCHEMA = "sn87-contest-reveal/0.1"
CLAIM = "SHADOW_TOOLING_NOT_WIRED_TO_WEIGHTS"
WINDOW_SEED_DOMAIN = b"SN87:CONTEST:WINDOW_SEED/v1"
COMMIT_DOMAIN = b"SN87:CONTEST:SEED_COMMITMENT/v1"
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
PHASES = ("init-master", "commit", "open", "truth", "reveal", "publish-truth", "verify")


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
    if (not isinstance(schedule, dict) or schedule.get("schema_version") != SCHEDULE_SCHEMA
            or not {"schedule_id", "profile_id", "windows"} <= set(schedule)
            or set(schedule) - {"schema_version", "schedule_id", "profile_id", "mix_preset", "mix",
                                "windows"}):
        raise ValueError("schedule schema")
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
        if set(w) != {"window_id", "opens_at", "closes_at"}:
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
    return {"generator": GENERATOR_ID, "schedule_id": schedule["schedule_id"],
            "window_id": window["window_id"],
            "opens_at": window["opens_at"], "closes_at": window["closes_at"],
            "profile_id": pid, "profile_commitment": profiles.load(pid).commitment,
            "mix_preset": preset, "mix": mix}


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


def capsules_document(spec: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    """What miners receive: capsules in position order, with nothing about family or track."""
    return {"schema_version": CAPSULES_SCHEMA, "window_id": spec["window_id"],
            "opens_at": spec["opens_at"], "closes_at": spec["closes_at"],
            "cases_commitment": cases_commitment(entries),
            "capsules": [e["capsule"] for e in entries]}


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
    rows = []
    for w in schedule["windows"]:
        spec = window_spec(schedule, w)
        seed = window_seed(master, schedule["schedule_id"], w["window_id"])
        rows.append({"window_id": w["window_id"], "opens_at": w["opens_at"],
                     "closes_at": w["closes_at"],
                     "seed_commitment": seed_commitment(w["window_id"], seed),
                     "spec_commitment": spec_commitment(spec, seed)})
    return {"schema_version": COMMITMENTS_SCHEMA, "claim": CLAIM, "generator": GENERATOR_ID,
            "schedule_id": schedule["schedule_id"], "profile_id": schedule["profile_id"],
            "profile_commitment": profiles.load(schedule["profile_id"]).commitment,
            "windows": rows,
            "schedule_commitment": digest(SCHEDULE_DOMAIN, canonical_bytes(rows))}


def reveal_document(schedule: dict[str, Any], window: dict[str, str], master: bytes
                    ) -> dict[str, Any]:
    return {"schema_version": REVEAL_SCHEMA, "window_id": window["window_id"],
            "seed": window_seed(master, schedule["schedule_id"], window["window_id"]).hex(),
            "spec": window_spec(schedule, window)}


def check_reveal(commitments: dict[str, Any], reveal: dict[str, Any]) -> list[dict[str, Any]]:
    """The commitment checks a public reader runs. Returns the instances it regenerated."""
    if reveal.get("schema_version") != REVEAL_SCHEMA:
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
    if seed_commitment(reveal["window_id"], seed) != row["seed_commitment"]:
        raise ValueError("SEED_COMMITMENT_MISMATCH")
    if spec_commitment(spec, seed) != row["spec_commitment"]:
        raise ValueError("SPEC_COMMITMENT_MISMATCH")
    if (spec["generator"], spec["window_id"], spec["opens_at"], spec["closes_at"],
            spec["profile_id"], spec["schedule_id"]) != (
            GENERATOR_ID, row["window_id"], row["opens_at"], row["closes_at"],
            commitments["profile_id"], commitments["schedule_id"]):
        raise ValueError("SPEC_DOES_NOT_MATCH_COMMITMENT_ROW")
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


# --- command line -----------------------------------------------------------------------------

def _now(value: str | None) -> str:
    return value or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window(schedule: dict[str, Any], window_id: str) -> dict[str, str]:
    for w in schedule["windows"]:
        if w["window_id"] == window_id:
            return w
    raise ValueError(f"window {window_id!r} is not in the schedule")


def run(args: argparse.Namespace) -> list[str]:
    """Run one phase; returns the paths written. Raises PhaseError / ValueError on refusal."""
    out = Path(args.out_dir) if args.out_dir else None
    phase, now = args.phase, _now(args.now)
    if phase == "init-master":
        path = Path(args.master_seed_file)
        write_new(path, os.urandom(32).hex() + "\n", mode=0o600)
        return [str(path)]
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
        truth_path = out / files["truth"]
        if truth_path.exists():
            doc = json.loads(truth_path.read_text("utf-8"))
            if [(c["qid"], c["family"], c["track"]) for c in doc["cases"]] != [
                    (e["qid"], e["family"], e["track"]) for e in regenerated]:
                raise ValueError("PUBLISHED_TRUTH_CASES_DIFFER_FROM_REGENERATED")
            check_truth_document(doc, commitments)
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
        write_new(target, dumps(reveal_document(schedule, window, master)))
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
