#!/usr/bin/env python3
"""Second-party reproduction kit for one closed contest window.

  uv run python scripts/reproduce_window.py --dir PUBLISHED_DIR [--window ID] [--json]
         [--expect-block NUMBER:0xHASH] [--commitments-seen-at ISO] [--use-reference]

READ ONLY. NO NETWORK, NO CHAIN, NO KEYS, NO WALLET, NO CLOCK, NO PRIVATE FILE.

Given only what a closed window publishes, this recomputes, step by step, the claim the
publisher makes, and says for each step PASS, FAIL or UNVERIFIED and why:

  S1  schedule commitments   the schedule commitment and the profile commitment recompute
  S2  reveal                 the revealed pre-seed (or seed) opens the committed seed commitment
  S3  seed                   the seed follows from the pre-seed and the opening block; the
                             specification opens its commitment; the block is the first one at or
                             after the opening time (offline rule check only)
  S4  cases                  the cases regenerate from the seed and equal the published capsules
                             and the cases commitment published at open
  S5  truth commitment       the published truth opens the salted truth commitment written in
                             the open record (binding only if that record was seen at open)
  S6  outcomes               each miner's outcome codes agree with its published responses
  S7  scores                 the window result recomputes under the named scoring profile
  S8  preference row         the preference row recomputes from the recomputed scores
  S9  weight row             the u16 weight row recomputes; no shadow uid is in it
  S10 weight gate            the baseline-headroom gate verdicts recompute
  S11 admission              the shadow window records and the admission verdict recompute

Five more lines are UNVERIFIED unless you supply evidence from outside the published files:
the opening block is canonical (B, ``--expect-block`` from a node you queried), the commitments
were public before the window opened (A, ``--commitments-seen-at`` with a time zone), the open
record is the one seen at open (O, ``--open-record-seen`` with the window_commitments a miner
recorded), truth is correct for capsule-computed families (T, ``--use-reference``, only where the
private reference executors are installed) and the miners' response signatures (G, never checked
by this kit, so the exit code is never 0).

Exit codes, as in ``verify_attestation.py``: 0 every step PASS, 3 none FAIL but some UNVERIFIED,
1 any FAIL (2 is argparse's usage error). Line G is always UNVERIFIED, so 0 is not reachable.
All files come from the operator: a pass means they agree with each other, not that they are
true. The closing claim says what was reproduced and what was
not. See docs/guides/reproduce-a-window.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import admission_plan as ap  # noqa: E402
import contest_results as cr  # noqa: E402
import contest_window as cw  # noqa: E402

from sn87_provenonce import bundle  # noqa: E402
from sn87_provenonce import profile as profiles  # noqa: E402
from sn87_provenonce.baselines import METHOD_ID as BASELINE  # noqa: E402
from sn87_provenonce.canonical import canonical_bytes  # noqa: E402
from sn87_provenonce.classes import BINDINGS  # noqa: E402
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable  # noqa: E402
from sn87_provenonce.scoring import NA, preference_row, wire  # noqa: E402

PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"
SUBMISSIONS_SCHEMA = "sn87-window-submissions/0.1"
DERIVED_SCHEMA = "sn87-window-derived/0.1"
STAGES = ("weighted", "shadow", "reference")
# Outcome codes, as the shadow tooling publishes them. A test in the private source tree keeps
# these equal to the shadow tooling's own sets, which are not part of the public tree.
INTEGRITY_CODES = frozenset({
    "AUTHENTICATION_FAILED", "AUTHENTICATION_UNAVAILABLE", "REPLAYED_REQUEST",
    "RESPONDER_IDENTITY_MISMATCH", "RESPONSE_BINDING_FAILED", "RESPONSE_MEDIA_TYPE",
    "DUPLICATE_RESPONSE_HEADER", "RESPONSE_TOO_LARGE", "BODY_TOO_LARGE", "RATE_LIMITED",
    "BOUNDARY_ERROR_UNCODED"})
UNAVAILABLE_CODES = frozenset({
    "REMOTE_REJECTED", "RESPONSE_LATE", "MINER_REJECTED_ENVELOPE", "TIMEOUT",
    "NOT_QUERIED_CIRCUIT_OPEN", "NOT_QUERIED_TIME_BUDGET"})
REPLY_CODES = frozenset({"REPLY_SCHEMA_INVALID", "REPLY_WRONG_CAPSULE"})
_DYNAMIC_UNAVAILABLE = re.compile(
    r"\A(?:CONNECTION_[A-Za-z0-9_]{1,80}|REMOTE_REJECTED_[1-5][0-9]{2})\Z")
DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
NOT_PUBLISHED = "NOT_PUBLISHED"


def redact(response: Any) -> Any:
    """The published form of a reply: the free text (``method``, ``rationale``, each finding's
    ``rationale``) is replaced by a constant, because it is not published. Nothing that is scored
    changes. A digest in the submissions file is the digest of this published form."""
    if not isinstance(response, dict):
        return response
    out = dict(response)
    for key in ("method", "rationale"):
        if key in out:
            out[key] = NOT_PUBLISHED
    if isinstance(out.get("findings"), list):
        out["findings"] = [dict(f, rationale=NOT_PUBLISHED) if isinstance(f, dict)
                           and "rationale" in f else f for f in out["findings"]]
    return out


def outcome_kind(code: Any) -> str | None:
    """valid, invalid (a reply that failed), integrity, unavailable; None for an unknown code."""
    if not isinstance(code, str):
        return None
    if code == "VALID":
        return "valid"
    if code in REPLY_CODES:
        return "invalid"
    if code in INTEGRITY_CODES:
        return "integrity"
    if code in UNAVAILABLE_CODES or _DYNAMIC_UNAVAILABLE.match(code):
        return "unavailable"
    return None


def digest_of(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def quantize_u16(rows: list[tuple[int, str]]) -> tuple[list[int], list[int]]:
    """The u16 quantizer of ``weights_dry_run.dry_run`` (positive weights scaled to the peak,
    round-half-even, zeros dropped) without the SDK cross-check or the target checks. A test
    keeps it equal to ``dry_run`` where the SDK is installed."""
    positive = [(u, Decimal(w)) for u, w in rows if Decimal(w) > 0]
    if not positive:
        return [], []
    peak = max(w for _, w in positive)
    out = [(u, int((w / peak * 65535).to_integral_value(rounding=ROUND_HALF_EVEN)))
           for u, w in positive]
    kept = [(u, v) for u, v in out if v > 0]
    return [u for u, _ in kept], [v for _, v in kept]


def first_difference(a: Any, b: Any, path: str = "") -> str | None:
    """The first path at which two JSON values differ, or None."""
    if type(a) is not type(b):
        return f"{path or '/'}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}: present in only one"
            found = first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path or '/'}: {len(a)} items vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            found = first_difference(x, y, f"{path}/{i}")
            if found:
                return found
        return None
    return None if a == b else f"{path or '/'}: {a!r} vs {b!r}"


@dataclass
class Step:
    key: str
    title: str
    status: str = UNVERIFIED
    reason: str = ""
    informational: bool = False


class Missing(Exception):
    """A needed artifact was not supplied: the step is UNVERIFIED, not FAIL."""


class Skip(Exception):
    """A step cannot run because an earlier one it depends on did not pass."""


@dataclass
class Window:
    """The published artifacts of one window, and what the steps compute from them."""

    directory: Path
    window_id: str
    docs: dict[str, Any] = field(default_factory=dict)
    broken: dict[str, str] = field(default_factory=dict)
    regenerated: list[dict[str, Any]] | None = None
    bundle_open_record: dict[str, Any] | None = None
    cases_verified: bool = False  # S4 passed: the capsules are the ones the seed makes
    reveal: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None  # the recomputed result, floats not yet on the wire

    def need(self, name: str) -> Any:
        if name in self.broken:
            raise ValueError(f"{name} is not valid JSON, or not an object: {self.broken[name]}")
        if self.docs.get(name) is None:
            raise Missing(f"{name} was not supplied")
        return self.docs[name]


def artifact_paths(directory: Path, window_id: str, overrides: dict[str, str | None]
                   ) -> dict[str, Path]:
    stem = f"window_{window_id}"
    paths = {"commitments": directory / "commitments.json",
             "capsules": directory / f"{stem}.capsules.json",
             "bundle": directory / "reveal-bundle.json",
             "reveal": directory / f"{stem}.reveal.json",
             "truth": directory / f"{stem}.truth.json",
             "submissions": directory / f"{stem}.submissions.json",
             "result": directory / f"{stem}.json",
             "derived": directory / f"{stem}.derived.json"}
    for key, value in overrides.items():
        if value:
            paths[key] = Path(value)
    return paths


def detect_window(directory: Path) -> str:
    found = sorted(p.name[len("window_"):-len(".capsules.json")]
                   for p in directory.glob("window_*.capsules.json"))
    if len(found) != 1:
        raise ValueError(f"expected one window_<id>.capsules.json in {directory}, found "
                         f"{len(found)}; pass --window")
    return found[0]


def load_window(directory: Path, window_id: str, overrides: dict[str, str | None]) -> Window:
    window = Window(directory, window_id)
    for name, path in artifact_paths(directory, window_id, overrides).items():
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text("utf-8"))
        except (ValueError, OSError) as error:
            window.broken[name] = str(error)[:120]
            continue
        if isinstance(doc, dict):
            window.docs[name] = doc
        else:
            window.broken[name] = f"top level is {type(doc).__name__}, not a JSON object"
    return window


# --- the steps --------------------------------------------------------------------------------

def row_of(commitments: dict[str, Any], window_id: str) -> dict[str, Any]:
    row = next((w for w in commitments["windows"] if w["window_id"] == window_id), None)
    if row is None:
        raise ValueError("WINDOW_NOT_COMMITTED: the window is not in the commitments")
    return row


def s1_schedule(w: Window) -> str:
    commitments = w.need("commitments")
    version = cw.version_of(commitments)
    if commitments["schedule_commitment"] != cw.digest(
            cw.SCHEDULE_DOMAIN, canonical_bytes(commitments["windows"])):
        raise ValueError("SCHEDULE_COMMITMENT_MISMATCH: the committed rows do not hash to it")
    profile = profiles.load(commitments["profile_id"])
    if commitments["profile_commitment"] != profile.commitment:
        raise ValueError("PROFILE_COMMITMENT_MISMATCH: the committed profile differs from the "
                         f"profile document {profile.profile_id} in this checkout")
    row = row_of(commitments, w.window_id)
    opened = w.need("capsules")
    if (row["opens_at"], row["closes_at"]) != (opened["opens_at"], opened["closes_at"]):
        raise ValueError("WINDOW_TIMES_DIFFER: the open record times differ from the commitment")
    return (f"protocol 0.{version}; {len(commitments['windows'])} committed window(s); the "
            f"schedule commitment recomputes; sizing profile {profile.profile_id} matches its "
            "committed document")


def _reveal_entry(w: Window) -> dict[str, Any]:
    commitments = w.need("commitments")
    if "bundle" in w.docs or "bundle" in w.broken:
        data = w.need("bundle")
        if data.get("schema_version") != cw.BUNDLE_SCHEMA:
            raise ValueError("BUNDLE_SCHEMA: not a reveal bundle")
        if (data["schedule_id"], data["schedule_commitment"]) != (
                commitments["schedule_id"], commitments["schedule_commitment"]):
            raise ValueError("BUNDLE_NOT_FOR_THESE_COMMITMENTS")
        entries = [e for e in data["windows"] if e["window_id"] == w.window_id]
        if len(entries) != 1:
            raise Missing("the reveal bundle has no single entry for this window")
        entry = entries[0]
        if entry["status"] == "NOT_OPENED":
            raise ValueError("BUNDLE_SAYS_NOT_OPENED: no seed was drawn, yet a capsule file "
                             "is published for this window")
        return entry
    return {"status": "REVEALED", "reveal": w.need("reveal")}


def s2_reveal(w: Window) -> str:
    commitments = w.need("commitments")
    row = row_of(commitments, w.window_id)
    entry = _reveal_entry(w)
    reveal = entry["reveal"]
    version = cw.version_of(commitments)
    if (reveal.get("schema_version") != (cw.REVEAL_SCHEMA, cw.REVEAL_SCHEMA_2)[version - 1]
            or reveal["window_id"] != w.window_id):
        raise ValueError("REVEAL_SCHEMA: the reveal is not for this window and protocol")
    if version == 1:
        ok = cw.seed_commitment(w.window_id, bytes.fromhex(reveal["seed"])) == row[
            "seed_commitment"]
        what = "seed"
    else:
        ok = cw.preseed_commitment(w.window_id, bytes.fromhex(reveal["preseed"])) == row[
            "seed_commitment"]
        what = "pre-seed"
    if not ok:
        raise ValueError(f"SEED_COMMITMENT_MISMATCH: the revealed {what} does not open the "
                         "commitment published before the window")
    w.reveal = reveal
    w.bundle_open_record = entry.get("open_record")
    return f"the revealed {what} opens the committed seed commitment `{row['seed_commitment']}`"


def s3_seed(w: Window) -> str:
    commitments, reveal = w.need("commitments"), w.reveal
    if reveal is None:
        raise Skip("S2")
    row = row_of(commitments, w.window_id)
    version = cw.version_of(commitments)
    spec = reveal["spec"]
    if version == 1:
        seed, key, note = bytes.fromhex(reveal["seed"]), bytes.fromhex(reveal["seed"]), (
            "protocol 0.1: the window seed is the committed value; there is no opening block")
    else:
        key = bytes.fromhex(reveal["preseed"])
        beacon = cw.check_beacon(reveal["beacon"])
        derived = cw.window_seed_2(key, commitments["schedule_id"], w.window_id, beacon)
        if derived.hex() != reveal["seed"]:
            raise ValueError("SEED_NOT_DERIVED_FROM_PRESEED_AND_BLOCK_HASH")
        opened = w.need("capsules")
        if opened.get("beacon") != reveal["beacon"]:
            raise ValueError("OPEN_RECORD_DIFFERS_FROM_REVEAL: the opening block published at "
                             "open is not the block in the reveal")
        if w.bundle_open_record is not None and w.bundle_open_record != cw.open_record(opened):
            raise ValueError("OPEN_RECORD_DIFFERS_FROM_BUNDLE: the open record in the reveal "
                             "bundle is not the published open record")
        try:
            cw.check_beacon_window(beacon, spec["opens_at"])
        except ValueError as error:
            raise ValueError(str(error)) from None
        seed = derived
        note = (f"seed = HMAC(pre-seed, schedule, window, block {beacon['number']}, block hash); "
                "the block's timestamps satisfy the first-block-at-or-after-opening rule"
                + ("; the block record is marked MANUAL (typed in, not read from a node)"
                   if beacon.get("manual") else ""))
    if cw.spec_commitment(spec, key) != row["spec_commitment"]:
        raise ValueError("SPEC_COMMITMENT_MISMATCH: the revealed specification does not open "
                         "its commitment")
    try:
        cw.check_reveal(commitments, reveal)  # every remaining cross-check of the reference rule
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(str(error)) from None
    w.regenerated = cw.build_window(seed, spec)
    return note + f"; the specification opens its commitment; {len(w.regenerated)} cases follow"


def s4_cases(w: Window) -> str:
    opened = w.need("capsules")
    if w.regenerated is None:
        raise Skip("S3")
    got = cw.cases_commitment(w.regenerated)
    if got != opened["cases_commitment"]:
        raise ValueError("CASES_COMMITMENT_MISMATCH: the regenerated cases hash to "
                         f"{got}, the open record says {opened['cases_commitment']}")
    if canonical_bytes(opened["capsules"]) != canonical_bytes(
            [e["capsule"] for e in w.regenerated]):
        raise ValueError("PUBLISHED_CAPSULES_DIFFER_FROM_REGENERATED")
    if cw.cases_commitment([{"qid": c["qid"], "capsule_commitment": c["evidence_commitment"]}
                            for c in opened["capsules"]]) != opened["cases_commitment"]:
        raise ValueError("CASES_COMMITMENT_MISMATCH: the published capsules do not hash to it")
    w.cases_verified = True
    return (f"{len(w.regenerated)} cases regenerate from the seed; capsules and the cases "
            f"commitment `{got}` equal the open record")


def s5_truth(w: Window) -> str:
    commitments, opened, truth = w.need("commitments"), w.need("capsules"), w.need("truth")
    if w.regenerated is None:
        raise Skip("S3")
    try:
        cw.check_truth_document(truth, commitments)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(str(error)) from None
    if cw.version_of(opened) == 2:
        try:
            cw.check_truth_against_open(truth, opened)
        except cw.PhaseError as error:
            raise ValueError(str(error)) from None
    if [(c["qid"], c["family"], c["track"], c["capsule_commitment"]) for c in truth["cases"]] != [
            (e["qid"], e["family"], e["track"], e["capsule_commitment"]) for e in w.regenerated]:
        raise ValueError("TRUTH_CASES_DIFFER_FROM_REGENERATED_INSTANCES")
    states = sorted({c["truth"]["state"] for c in truth["cases"] if c["truth"]})
    failures = sum(c["truth"] is None for c in truth["cases"])
    return (f"the published truth ({len(truth['cases'])} cases, {failures} reference failure(s), "
            f"states {', '.join(states)}) opens the salted truth commitment written in the open "
            "record. That binds the truth only if the open record is the one seen when the "
            "window opened (line O)")


def _response_view(w: Window) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    submissions = w.need("submissions")
    if submissions.get("schema_version") != SUBMISSIONS_SCHEMA or (
            submissions.get("window_id") != w.window_id):
        raise ValueError("SUBMISSIONS_SCHEMA: not the submissions of this window")
    return {c["qid"]: c for c in w.need("capsules")["capsules"]}, submissions["methods"]


def s6_outcomes(w: Window) -> str:
    capsules, methods = _response_view(w)
    if not w.cases_verified:
        raise Skip("S4")
    binding = BINDINGS[cw.GENERATOR_CLASS]
    baseline = binding.baseline
    counts = {"valid": 0, "invalid": 0, "integrity": 0, "unavailable": 0}
    digest_only = 0
    for method in methods:
        name, subs = method["method_id"], method["submissions"]
        if set(subs) != set(capsules):
            raise ValueError(f"{name}: submissions do not cover exactly the window's cases")
        if method["role"] == "baseline":
            if name != BASELINE:
                raise ValueError("the baseline row is the public-contract baseline")
            for qid, sub in subs.items():
                if canonical_bytes(sub.get("response")) != canonical_bytes(
                        redact(baseline(capsules[qid]))):
                    raise ValueError(f"{name} {qid}: the baseline's response is not what the "
                                     "public baseline code returns")
            continue
        for qid, sub in subs.items():
            capsule, code = capsules[qid], sub["outcome"]
            kind = outcome_kind(code)
            if kind is None:
                raise ValueError(f"{name} {qid}: unknown outcome code {code!r}")
            counts[kind] += 1
            response, reply, shown = sub.get("response"), sub.get("reply"), sub.get(
                "response_digest")
            if shown is not None and DIGEST.match(shown) is None:
                raise ValueError(f"{name} {qid}: malformed response digest")
            if code == "VALID":
                if response is None:
                    digest_only += 1  # a digest without the response cannot be re-checked
                    if shown is None:
                        raise ValueError(f"{name} {qid}: VALID with neither response nor digest")
                    continue
                try:
                    binding.validate_differential(capsule, response)
                except (ValueError, TypeError, KeyError, RecursionError):
                    raise ValueError(f"{name} {qid}: outcome VALID but the published response "
                                     "fails the response schema for its capsule") from None
                if shown is not None and shown != digest_of(response):
                    raise ValueError(f"{name} {qid}: the response does not match its digest")
                continue
            if response is not None:
                raise ValueError(f"{name} {qid}: outcome {code} but a scored response is "
                                 "published")
            if code in REPLY_CODES:
                if reply is None:
                    digest_only += 1
                    continue
                if shown is not None and shown != digest_of(reply):
                    raise ValueError(f"{name} {qid}: the reply does not match its digest")
                wrong = (isinstance(reply, dict) and "capsule_commitment" in reply
                         and reply["capsule_commitment"] != capsule["evidence_commitment"])
                if (code == "REPLY_WRONG_CAPSULE") != wrong:
                    raise ValueError(f"{name} {qid}: outcome {code} does not match the reply's "
                                     "capsule binding")
                try:
                    binding.validate_differential(capsule, reply)
                except (ValueError, TypeError, KeyError, RecursionError):
                    pass
                else:
                    raise ValueError(f"{name} {qid}: outcome {code} but the reply is valid")
            elif reply is not None or shown is not None:
                raise ValueError(f"{name} {qid}: outcome {code} carries a reply or digest")
    text = (f"{len(methods)} methods; outcomes {counts['valid']} VALID, {counts['invalid']} "
            f"invalid reply, {counts['integrity']} integrity, {counts['unavailable']} "
            "unavailable, each consistent with what is published; baseline responses equal "
            "the public baseline code")
    if digest_only:
        raise Partial(text + f"; {digest_only} submission(s) publish a digest only, so their "
                      "content cannot be re-checked")
    return text


class Partial(Exception):
    """Everything that could be checked passed, but some of it could not be."""


def _scored(w: Window) -> dict[str, Any]:
    """The recomputed window result (floats not on the wire), cached."""
    if w.raw is not None:
        return w.raw
    _response_view(w)
    _, methods = _response_view(w)
    truth, published = w.need("truth"), w.need("result")
    if not w.cases_verified:
        raise Skip("S4")
    commitments = w.need("commitments")
    named = published.get("profile") or {}
    if (named.get("profile_id"), named.get("profile_commitment")) != (
            commitments["profile_id"], commitments["profile_commitment"]):
        raise ValueError("PROFILE_NOT_THE_COMMITTED_PROFILE: the result is scored under "
                         f"{named.get('profile_id')}, the schedule commits to "
                         f"{commitments['profile_id']}")
    responses = {"schema_version": cr.RESPONSES_SCHEMA, "window_id": w.window_id,
                 "methods": [{
                     "method_id": m["method_id"], "uid": m.get("uid"), "role": m["role"],
                     "responses": {qid: {"response": s.get("response") if s["outcome"] == "VALID"
                                         else None}
                                   for qid, s in m["submissions"].items()}} for m in methods]}
    if "integrity_mode" in w.need("submissions"):
        responses["integrity_mode"] = w.docs["submissions"]["integrity_mode"]
    capsule_doc = w.need("capsules")
    if cw.version_of(capsule_doc) == 2:
        cw.check_truth_against_open(truth, capsule_doc)
    profile_id = commitments["profile_id"]
    binding = BINDINGS[cw.GENERATOR_CLASS]
    w.raw = cr.score_window(capsule_doc, truth, responses, profile_id,
                            case_detail="cases" in published,
                            baseline=lambda c: redact(binding.baseline(c)))
    return w.raw


def s7_scores(w: Window) -> str:
    published = w.need("result")
    raw = wire(_scored(w))
    expected = raw if published.get("disclosure") == "TRUTH_DERIVED" else cr.scores_only(raw)
    found = first_difference(json.loads(json.dumps(expected)), published)
    if found:
        raise ValueError(f"RESULT_DIFFERS_FROM_RECOMPUTATION at {found}")
    name = published["profile"]["profile_id"]
    estimates = ", ".join(f"{m['method_id']} {m['score']['estimate']}" for m in published[
        "methods"])
    return (f"the {published['disclosure']} window result recomputes exactly under profile "
            f"{name} from the published truth and responses ({estimates})")


def _identities(w: Window) -> list[dict[str, Any]]:
    """Method, uid, hotkey and stage of every method, taken from the submissions. The derived
    record repeats them; any difference is a refusal, so a stage cannot be changed there."""
    derived = w.need("derived")
    if derived.get("schema_version") != DERIVED_SCHEMA or derived["window_id"] != w.window_id:
        raise ValueError("DERIVED_SCHEMA: not the derived record of this window")
    _, methods = _response_view(w)
    ids = [{"method_id": m["method_id"], "uid": m.get("uid"), "hotkey": m.get("hotkey"),
            "stage": m.get("stage")} for m in methods]
    if any(i["stage"] not in STAGES for i in ids):
        raise ValueError("UNKNOWN_STAGE")
    shown = derived["identities"]
    if (not isinstance(shown, list) or any(not isinstance(i, dict) or set(i) != set(ids[0])
                                           for i in shown)
            or sorted(json.dumps(i, sort_keys=True) for i in shown)
            != sorted(json.dumps(i, sort_keys=True) for i in ids)):
        raise ValueError("IDENTITIES_DIFFER_FROM_SUBMISSIONS: method, stage, uid or hotkey in the "
                         "derived record is not what the submissions say")
    names = [m["method_id"] for m in _scored(w)["methods"]]
    if sorted(i["method_id"] for i in ids) != sorted(names):
        raise ValueError("IDENTITIES_DIFFER_FROM_RESULT_METHODS")
    return ids


def _estimates(w: Window) -> dict[str, float | None]:
    return {m["method_id"]: (None if m["score"]["estimate"] == NA else m["score"]["estimate"])
            for m in _scored(w)["methods"]}


def _preference(w: Window) -> dict[str, Any]:
    ids = _identities(w)
    estimates = _estimates(w)
    weighted = sorted(i["method_id"] for i in ids if i["stage"] == "weighted")
    if not weighted:
        raise ValueError("NO_WEIGHTED_IDENTITY")
    profile = profiles.load(w.need("result")["profile"]["profile_id"])
    answers = None
    if profile.fixed_outcome is not None:
        _, methods = _response_view(w)
        admitted = [r["qid"] for r in w.need("truth")["cases"]
                    if r["truth"] is not None and r["track"] == "scored"]
        answers = {m["method_id"]: {q: (m["submissions"][q].get("response")
                                        if m["submissions"][q]["outcome"] == "VALID" else None)
                                    for q in admitted}
                   for m in methods if m["method_id"] in weighted}
    return wire(preference_row({k: estimates[k] for k in weighted}, profile, answers=answers))


def s8_preference(w: Window) -> str:
    published = w.need("derived")["preference_row"]
    found = first_difference(json.loads(json.dumps(_preference(w))), published)
    if found:
        raise ValueError(f"PREFERENCE_ROW_DIFFERS at {found}")
    return (f"preference row ({published['state']}) recomputes from the recomputed estimates of "
            "the weighted identities, with the profile's threshold and sharpness")


def s9_weight_row(w: Window) -> str:
    derived = w.need("derived")
    ids = {i["method_id"]: i for i in _identities(w)}
    pref = _preference(w)
    uid_of = {m: i["uid"] for m, i in ids.items() if i["stage"] == "weighted"}
    if any(type(u) is not int for u in uid_of.values()):
        raise ValueError("WEIGHTED_IDENTITY_WITHOUT_UID")
    rows = [] if pref["weights"] is None else sorted(
        ((uid_of[m], v) for m, v in pref["weights"].items()))
    uids, values = quantize_u16(rows)
    expected = {"state": "TARGET_CONFORMED_DRY_RUN" if uids else "NO_VALID_WEIGHT_ROW",
                "uids": uids, "u16_weights": values}
    published = derived["weight_row"]
    shadow = {i["uid"] for i in ids.values() if i["stage"] == "shadow"}
    if shadow & set(published.get("uids", [])):
        raise ValueError(f"SHADOW_UID_IN_WEIGHT_ROW: {sorted(shadow & set(published['uids']))}")
    found = first_difference(expected, {k: published.get(k) for k in expected})
    if found:
        raise ValueError(f"WEIGHT_ROW_DIFFERS at {found}")
    return (f"u16 row {dict(zip(uids, values, strict=True))} recomputes from the preference row "
            f"({len(shadow)} shadow uid(s), none in the row). Computation only: nothing here "
            "shows the row was ever set on a chain")


def s10_gate(w: Window) -> str:
    published = w.need("derived")["weight_gate"]
    roles = {m["method_id"]: m["role"] for m in _scored(w)["methods"] if m["role"] != "baseline"}
    gate = wire(bundle.family_gate(_estimates(w), cw.GENERATOR_CLASS, roles))
    found = first_difference(json.loads(json.dumps(gate)), published)
    if found:
        raise ValueError(f"WEIGHT_GATE_DIFFERS at {found}")
    verdicts = ", ".join(f"{m} {g['verdict']}" for m, g in sorted(gate["methods"].items()))
    return (f"gate recomputes (family weight_eligible {gate['family']['weight_eligible']}, "
            f"status {gate['family']['status']}; {verdicts})")


def _shadow_record(w: Window, published: dict[str, Any], seed_hex: str) -> dict[str, Any]:
    _, methods = _response_view(w)
    method = next(m for m in methods if m["uid"] == published["uid"])
    kinds = [outcome_kind(s["outcome"]) for s in method["submissions"].values()]
    codes = [s["outcome"] for s in method["submissions"].values()
             if outcome_kind(s["outcome"]) == "integrity"]
    scored = {m["method_id"]: m for m in _scored(w)["methods"]}
    mine, base = scored[method["method_id"]]["score"], scored[BASELINE]["score"]
    return ap.build_window_result(
        uid=published["uid"], hotkey=published["hotkey"], netuid=published["netuid"],
        window=published["window"], seed=int(seed_hex[:12], 16), queried=len(kinds),
        valid_responses=kinds.count("valid"), invalid_responses=kinds.count("invalid"),
        unavailable=kinds.count("unavailable"), integrity_failure_codes=codes,
        estimate=wire(mine["estimate"]), evaluable=mine["evaluable"], admitted=mine["admitted"],
        profile_id=w.need("result")["profile"]["profile_id"],
        endpoint_record_digest=published["endpoint_record_digest"],
        baseline_estimate=wire(base["estimate"]), baseline_admitted=base["admitted"],
        baseline_evaluable=base["evaluable"])


def s11_admission(w: Window) -> str:
    admission = w.need("derived")["admission"]
    criteria = admission["criteria"]
    if not ap.criteria_digest_ok(criteria):
        raise ValueError("CRITERIA_DIGEST_OR_RULES_INVALID")
    if w.reveal is None:
        raise Skip("S2")
    ids = _identities(w)
    shadow_uids = sorted(i["uid"] for i in ids if i["stage"] == "shadow")
    records = admission["results"]
    if sorted(r["uid"] for r in records) != shadow_uids:
        raise ValueError("ADMISSION_RESULTS_DO_NOT_COVER_EXACTLY_THE_SHADOW_UIDS")
    verdicts, unchecked = {}, []
    for published in records:
        recomputed = _shadow_record(w, published, w.reveal["seed"])
        found = first_difference(json.loads(json.dumps(recomputed)), published)
        if found:
            raise ValueError(f"SHADOW_WINDOW_RESULT_DIFFERS (uid {published['uid']}) at {found}")
        report = ap.evaluate_criteria(
            criteria, [recomputed], None, uid=published["uid"], hotkey=published["hotkey"],
            now_window=published["window"], netuid=published["netuid"])
        if criteria["rules"]["require_endpoint_announcement_valid"]:
            # The announcement is read from the chain; it is not in the published files.
            unchecked.append(published["uid"])
            reasons = [r for r in report.reasons if not r["code"].startswith("ENDPOINT_")]
        else:
            reasons = report.reasons
        verdicts[published["uid"]] = "PASS" if not reasons else "FAIL"
        want = next((a for a in admission["reports"] if a["uid"] == published["uid"]), None)
        if want is None:
            raise ValueError(f"no admission report published for uid {published['uid']}")
        if criteria["rules"]["require_endpoint_announcement_valid"]:
            got = [r for r in want["reasons"] if not r["code"].startswith("ENDPOINT_")]
            same = got == reasons and want["windows_checked"] == report.windows_checked
        else:
            same = first_difference(json.loads(json.dumps(report.as_document())), want) is None
        if not same:
            raise ValueError(f"ADMISSION_VERDICT_DIFFERS (uid {published['uid']})")
    text = ("shadow window records recompute (outcome counts, score, public-baseline score) and "
            f"the criteria verdict per shadow uid recomputes: {verdicts}. A shadow uid has "
            "weight 0 whatever the verdict")
    if unchecked:
        raise Partial(text + "; the endpoint announcement the criteria require is read from the "
                      f"chain and is not checked here (uids {unchecked})")
    return text


# --- the steps that need evidence from outside the files ---------------------------------------

def i_block(w: Window, expect: str | None) -> tuple[str, str]:
    reveal = w.reveal
    if reveal is None or "beacon" not in reveal:
        return UNVERIFIED, "no opening block in this protocol, or the reveal did not verify"
    block = reveal["beacon"]
    if expect is None:
        return UNVERIFIED, (f"block {block['number']} {block['hash']} is an input to the seed; "
                            "this kit reads no chain. Check it against a node you run or trust, "
                            "or pass --expect-block NUMBER:0xHASH")
    number, _, digest = expect.partition(":")
    if number == str(block["number"]) and digest.lower() == block["hash"].lower():
        return PASS, f"block {number} and its hash equal the block you supplied"
    return FAIL, f"the block you supplied ({expect}) is not the published block"


def utc_instant(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an ISO 8601 time") from None
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{text!r} needs a time zone, for example "
                                         "2026-11-09T00:00:00Z")
    return moment.astimezone(UTC)


def i_anchor(w: Window, seen_at: datetime | None) -> tuple[str, str]:
    if seen_at is None:
        return UNVERIFIED, ("whether commitments.json was public before the window opened needs "
                            "an independent timestamp (a dated release, repository commit or "
                            "log); pass --commitments-seen-at ISO if you hold one")
    commitments = w.docs.get("commitments")
    if commitments is None:
        return UNVERIFIED, "commitments.json was not supplied"
    opens = row_of(commitments, w.window_id)["opens_at"]
    opened = datetime.strptime(opens, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    if seen_at < opened:
        return PASS, (f"you saw the commitments at {seen_at.isoformat()}, before the window "
                      f"opened ({opens})")
    return FAIL, f"your time {seen_at.isoformat()} is not before the window opened ({opens})"


def i_open_record(w: Window, seen_file: str | None) -> tuple[str, str]:
    if seen_file is None:
        return UNVERIFIED, ("the open record (cases and truth commitments) binds the truth only "
                            "if it is the one published when the window opened. Pass "
                            "--open-record-seen FILE with the window_commitments a miner "
                            "recorded in a signed request, or another copy you saw at open")
    opened = w.docs.get("capsules")
    if opened is None:
        return UNVERIFIED, "the open record was not supplied"
    expected = cw.request_commitments(opened)
    if expected is None:
        return UNVERIFIED, "protocol 0.1 has no window_commitments in its requests"
    seen = json.loads(Path(seen_file).read_text("utf-8"))
    if isinstance(seen, dict) and "window_commitments" in seen:
        seen = seen["window_commitments"]
    if seen == expected:
        return PASS, "the window_commitments you saw at open equal the open record's"
    return FAIL, "the window_commitments you saw at open differ from the open record"


def i_truth_correct(w: Window, use_reference: bool) -> tuple[str, str]:
    truth = w.docs.get("truth")
    if not use_reference or truth is None or w.regenerated is None:
        return UNVERIFIED, ("the truth for capsule-computed families comes from private "
                            "reference executors; it is bound by the commitment, not recomputed. "
                            "Where the executors are installed, --use-reference recomputes it")
    try:
        rows = cw.derive_truth(w.regenerated)
    except PrivateReferenceExecutorUnavailable:
        return UNVERIFIED, ("--use-reference was given but the private reference executors "
                            "are absent")
    if first_difference([r["truth"] for r in rows], [c["truth"] for c in truth["cases"]]):
        return FAIL, "the reference executors give different truth for some case"
    return PASS, f"the reference executors reproduce the truth of all {len(rows)} cases"


def i_signatures(w: Window) -> tuple[str, str]:
    return UNVERIFIED, ("miner response signatures are not checked by this kit; a response digest "
                        "is of the published form (free text removed) and shows which bytes were "
                        "meant, not that anyone signed them")


STEPS: list[tuple[str, str, Callable[[Window], str]]] = [
    ("S1", "schedule commitments", s1_schedule),
    ("S2", "reveal opens the seed commitment", s2_reveal),
    ("S3", "seed from pre-seed and opening block", s3_seed),
    ("S4", "cases regenerate to the cases commitment", s4_cases),
    ("S5", "truth opens the truth commitment in the open record", s5_truth),
    ("S6", "outcome codes agree with published responses", s6_outcomes),
    ("S7", "scores recompute under the named profile", s7_scores),
    ("S8", "preference row recomputes", s8_preference),
    ("S9", "weight row recomputes", s9_weight_row),
    ("S10", "weight gate verdict recomputes", s10_gate),
    ("S11", "admission verdict recomputes", s11_admission),
]


def run_steps(w: Window, args: argparse.Namespace) -> list[Step]:
    steps: list[Step] = []
    failed: set[str] = set()
    for key, title, fn in STEPS:
        step = Step(key, title)
        try:
            step.reason, step.status = fn(w), PASS
        except Partial as note:
            step.status, step.reason = UNVERIFIED, str(note)
        except Missing as note:
            step.status, step.reason = UNVERIFIED, str(note)
        except Skip as note:
            step.status, step.reason = UNVERIFIED, f"depends on {note}, which did not pass"
        except (ValueError, KeyError, TypeError, AttributeError, IndexError,
                profiles.ProfileNotApplied, cw.PhaseError) as error:
            step.status = FAIL
            step.reason = str(error) or type(error).__name__
            if not isinstance(error, ValueError):
                step.reason = f"artifact malformed: {type(error).__name__}: {step.reason}"
            failed.add(key)
        steps.append(step)
    for key, title, call in (
            ("B", "opening block is canonical", lambda: i_block(w, args.expect_block)),
            ("A", "commitments public before the window opened",
             lambda: i_anchor(w, args.commitments_seen_at)),
            ("O", "open record is the one seen at open",
             lambda: i_open_record(w, args.open_record_seen)),
            ("T", "truth correct for capsule-computed families",
             lambda: i_truth_correct(w, args.use_reference)),
            ("G", "miner response signatures", lambda: i_signatures(w))):
        try:
            status_reason = call()
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, OSError) as error:
            status_reason = (FAIL, f"artifact malformed: {type(error).__name__}: {error}")
        steps.append(Step(key, title, *status_reason, informational=True))
    return steps


def verdict_of(steps: list[Step]) -> str:
    states = {s.status for s in steps}
    return FAIL if FAIL in states else UNVERIFIED if UNVERIFIED in states else PASS


EXIT = {PASS: 0, UNVERIFIED: 3, FAIL: 1}

NOT_SHOWN = (
    "independent participation: not shown (the files cannot tell whether miners are independent "
    "of each other or of the operator)",
    "forgery by an operator who controls every file: not ruled out (such an operator can produce "
    "a set that passes S1 to S11; only outside anchoring, miner signatures and the private "
    "executors rule that out)",
    "TIMEOUT and other unavailable outcomes: cannot be falsified from files (a missing reply "
    "has nothing to check)",
    "weighted activity: not shown (a weight row here is a computation from the files; nothing "
    "checks that any weight was set on a chain)",
    "performance or adoption: not claimed",
)


def claim(w: Window, steps: list[Step]) -> list[str]:
    done = [f"{s.key} {s.title}" for s in steps if s.status == PASS]
    open_ = [f"{s.key} {s.title}: {s.status}" for s in steps if s.status != PASS]
    result = w.docs.get("result") or {}
    lines = [f"Internally consistent, operator-supplied files: CLAIM for window {w.window_id}: "
             "what this run reproduced and what it did not."]
    if (w.reveal or {}).get("beacon", {}).get("manual"):
        lines.append("  The opening block record is marked MANUAL: typed in by the operator, "
                     "not read from a node.")
    lines += [
              "  Reproduced from the published files: " + ("; ".join(done) or "nothing") + ".",
              "  Not reproduced: " + ("; ".join(open_) or "nothing") + "."]
    lines += [f"  {line}" for line in NOT_SHOWN]
    if result.get("claim"):
        lines.append(f"  The publisher's own label: {result['claim']}.")
    return lines


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dir", required=True, help="folder holding the published artifacts")
    p.add_argument("--window", help="window id (default: the only window_<id>.capsules.json)")
    for name in ("commitments", "bundle", "reveal", "capsules", "truth", "submissions",
                 "result", "derived"):
        p.add_argument(f"--{name}", help=f"path of the {name} file if not the default name")
    p.add_argument("--expect-block", metavar="NUMBER:0xHASH",
                   help="the opening block as read from a node you trust")
    p.add_argument("--commitments-seen-at", metavar="ISO", type=utc_instant,
                   help="when you independently saw the commitments (ISO 8601 with a time zone)")
    p.add_argument("--open-record-seen", metavar="FILE",
                   help="the window_commitments you saw at open (JSON), checked for equality")
    p.add_argument("--use-reference", action="store_true",
                   help="recompute truth with the private reference executors, if installed")
    p.add_argument("--json", action="store_true", help="print the steps as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    directory = Path(args.dir)
    try:
        window_id = args.window or detect_window(directory)
    except ValueError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    overrides = {k: getattr(args, k) for k in ("commitments", "bundle", "reveal", "capsules",
                                               "truth", "submissions", "result", "derived")}
    w = load_window(directory, window_id, overrides)
    steps = run_steps(w, args)
    overall = verdict_of(steps)
    if args.json:
        print(json.dumps({"window_id": window_id, "verdict": overall,
                          "steps": [vars(s) for s in steps], "claim": claim(w, steps)},
                         indent=2))
    else:
        print(f"Reproduction of window {window_id} from {directory}")
        for s in steps:
            print(f"[{s.status}] {s.key} {s.title}: {s.reason}")
        print()
        print("\n".join(claim(w, steps)))
        print(f"\n{overall}")
    return EXIT[overall]


if __name__ == "__main__":
    raise SystemExit(main())
