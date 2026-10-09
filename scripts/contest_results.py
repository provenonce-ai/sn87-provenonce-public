#!/usr/bin/env python3
"""Per-window results for a contest window: score, agreement with truth, failures, cost.

SHADOW TOOLING. Reads files, writes two files, touches no weight, chain or active profile.

  uv run python scripts/contest_results.py --capsules C --truth T --responses R --out-dir D
         [--profile IC-FIRST-LIGHT-MIN-1] [--commitments K] [--reveal V] [--now ISO]
         [--include-case-detail --publish-closed-window-truth]

Writes ``window_<id>.json`` (schema ``sn87-contest-window-results/0.1``) and ``window_<id>.md``,
create-only and byte-deterministic: the output is a pure function of the input files and the
committed profile, with no clock, no randomness and no hand-copied number. The schema is in
docs/protocol/window-results.md.

Scoring is the one scorer (``scoring.score_response``) under a committed profile chosen by id
(default ``IC-FIRST-LIGHT-MIN-1``; ``IC-FIRST-LIGHT-MIN-2`` and ``-3`` are reachable only by id
and are active nowhere). Every method, the public-contract baseline included, is scored on the
same capsules with the same truth. The baseline's responses are recomputed here from the public
baseline code and compared, so a published baseline row cannot differ from the code.

Aggregate results are published for CLOSED windows only: the script refuses before the window's
close time. Per-case rows (which reveal truth case by case) need a verified reveal and the
explicit policy flag; whether to publish them is an open decision (ADR-0020).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contest_window as cw  # noqa: E402

from sn87_provenonce import bundle  # noqa: E402
from sn87_provenonce import profile as profiles
from sn87_provenonce.baselines import METHOD_ID as BASELINE  # noqa: E402
from sn87_provenonce.canonical import canonical_bytes  # noqa: E402
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY  # noqa: E402
from sn87_provenonce.scoring import (  # noqa: E402
    NA,
    Integrity,
    epoch_estimate,
    score_response,
    wire,
)

SCHEMA = "sn87-contest-window-results/0.1"
RESPONSES_SCHEMA = "sn87-contest-responses/0.1"
CLAIM = "SHADOW_RESULTS_NOT_WIRED_TO_WEIGHTS"
DEFAULT_PROFILE = "IC-FIRST-LIGHT-MIN-1"
STATES = ("FINDINGS", "NO_MATERIAL_DEVIATION", "INSUFFICIENT_EVIDENCE_ABSTAIN")
NO_RESPONSE = "NO_VALID_RESPONSE"
INTEGRITY_KEYS = ("schema", "policy", "signature", "nonce", "evidence", "deadline")
REPORTED_COSTS = ("wall_time", "cpu_time", "model_tokens", "oracle_time")


def _mean(values: list[float]) -> float | str:
    return math.fsum(values) / len(values) if values else NA


def _signature(response: dict[str, Any] | None):
    return None if response is None else (
        response["state"], tuple(sorted(f["code"] for f in response["findings"])))


def _truth_signature(truth: dict[str, Any]):
    return truth["state"], tuple(sorted(d["code"] for d in truth["defects"]))


def _cell(agree: int, n: int) -> dict[str, Any]:
    return {"agree": agree, "n": n, "fraction": agree / n if n else NA}


def _integrity(raw: dict[str, Any] | None) -> Integrity:
    if raw is None:
        return Integrity(*[True] * 6)
    if set(raw) != set(INTEGRITY_KEYS) or any(type(v) is not bool for v in raw.values()):
        raise ValueError("integrity must hold the six booleans")
    return Integrity(**raw)


def _cost(capsule: dict[str, Any], response: dict[str, Any] | None,
          reported: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The six-dimension cost record: bytes are measured here, the rest are reported or missing."""
    measured = {"bytes_in": (float(len(canonical_bytes(capsule))), "canonical_capsule_bytes")}
    missing = {}
    if response is not None:
        measured["bytes_out"] = (float(len(canonical_bytes(response))),
                                 "canonical_response_bytes")
    else:
        missing["bytes_out"] = "NO_RESPONSE"
    for key in REPORTED_COSTS:
        value = (reported or {}).get(key)
        if type(value) in (int, float) and not isinstance(value, bool) and value >= 0:
            measured[key] = (float(value), "reported_with_responses")
        else:
            missing[key] = "NOT_REPORTED"
    return bundle.cost_record(measured, missing)


def load_inputs(capsules_path: Path, truth_path: Path, responses_path: Path
                ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    capsules = json.loads(capsules_path.read_text("utf-8"))
    truth = json.loads(truth_path.read_text("utf-8"))
    responses = json.loads(responses_path.read_text("utf-8"))
    window_id = capsules["window_id"]
    if truth["window_id"] != window_id or responses.get("window_id") != window_id:
        raise ValueError("WINDOW_ID_MISMATCH")
    if responses.get("schema_version") != RESPONSES_SCHEMA:
        raise ValueError("responses schema")
    rows = truth["cases"]
    if [r["qid"] for r in rows] != [c["qid"] for c in capsules["capsules"]]:
        raise ValueError("TRUTH_AND_CAPSULES_DISAGREE_ON_CASES")
    if [r["capsule_commitment"] for r in rows] != [
            c["evidence_commitment"] for c in capsules["capsules"]]:
        raise ValueError("TRUTH_BOUND_TO_OTHER_CAPSULES")
    if capsules["cases_commitment"] != cw.cases_commitment(rows) or (
            truth["cases_commitment"] != capsules["cases_commitment"]):
        raise ValueError("CASES_COMMITMENT_MISMATCH")
    cw.check_truth_document(truth)  # the salted commitment, recomputed from the truth file
    return capsules, truth, responses


def score_window(capsules: dict[str, Any], truth: dict[str, Any], responses: dict[str, Any],
                 profile_id: str, *, case_detail: bool = False,
                 baseline: Callable[[dict[str, Any]], dict[str, Any]] | None = None
                 ) -> dict[str, Any]:
    """The results document (floats not yet on the wire) for one window."""
    loaded = profiles.load(profile_id)
    if loaded.class_id != IC_APPROVAL_APPLICABILITY.class_id:
        raise ValueError(f"PROFILE_CLASS_MISMATCH: {profile_id} is for {loaded.class_id}")
    binding = replace(IC_APPROVAL_APPLICABILITY, profile=loaded)
    profile = binding.profile
    baseline = baseline or binding.baseline
    by_qid = {c["qid"]: c for c in capsules["capsules"]}
    admitted = [r for r in truth["cases"] if r["truth"] is not None]
    failures = [r for r in truth["cases"] if r["truth"] is None]
    scored_n = sum(r["track"] == "scored" for r in admitted)
    methods = sorted(responses["methods"], key=lambda m: (m["role"] == "baseline", m["method_id"]))
    if len({m["method_id"] for m in methods}) != len(methods):
        raise ValueError("DUPLICATE_METHOD_ID")
    if [m["role"] for m in methods].count("baseline") != 1:
        raise ValueError("exactly one public_contract_baseline row is required")
    out_methods, estimates, per_case = [], {}, []
    for method in methods:
        if method["role"] not in ("candidate", "baseline"):
            raise ValueError("method role must be candidate or baseline")
        if method["role"] == "baseline" and method["method_id"] != BASELINE:
            raise ValueError("the baseline row is the public-contract baseline")
        seen, records = method["responses"], []
        for row in admitted:
            entry = seen.get(row["qid"]) or {}
            capsule = by_qid[row["qid"]]
            response = entry.get("response")
            record = score_response(binding, capsule, row["truth"], response,
                                    _integrity(entry.get("integrity")))
            records.append((row, response, record, _cost(capsule, response, entry.get("cost"))))
        scored = [r for r in records if r[0]["track"] == "scored"]
        diagnostic = [r for r in records if r[0]["track"] == "diagnostic"]
        epoch = epoch_estimate([r[2]["score"] for r in scored], [r[2]["valid"] for r in scored],
                               profile)
        estimates[method["method_id"]] = epoch["estimate"]
        confusion: dict[str, Counter] = {t: Counter() for t in STATES}
        family: dict[str, dict[str, Any]] = {}
        reasons: Counter = Counter()
        for row, response, record, _ in records:
            shown = response["state"] if record["valid"] else NO_RESPONSE
            confusion[row["truth"]["state"]][shown] += 1
            reasons.update(record["failures"])
            f = family.setdefault(row["family"], {"n": 0, "agree": 0, "scores": []})
            f["n"] += 1
            f["agree"] += shown == row["truth"]["state"]
            f["scores"].append(record["score"])
        agree = [r[2]["valid"] and r[1]["state"] == r[0]["truth"]["state"] for r in records]
        exact = [r[2]["valid"] and _signature(r[1]) == _truth_signature(r[0]["truth"])
                 for r in records]
        track_agree = {t: [a for a, r in zip(agree, records, strict=True) if r[0]["track"] == t]
                       for t in cw.TRACKS}
        valid_scored = [r[2]["dimensions"] for r in scored if r[2]["valid"]]
        out_methods.append({
            "method_id": method["method_id"], "uid": method.get("uid"), "role": method["role"],
            "score": {
                "estimate": NA if epoch["estimate"] is None else epoch["estimate"],
                "eligible": epoch["eligible"], "reason": epoch["reason"],
                "admitted": len(scored), "evaluable": sum(r[2]["valid"] for r in scored),
                "raw_invalid_or_missing_rate": NA if epoch["raw_invalid_or_missing_rate"] is None
                else epoch["raw_invalid_or_missing_rate"],
                "lower": epoch.get("lower", NA), "upper": epoch.get("upper", NA),
                "dimensions": {k: _mean([d[k] for d in valid_scored if d.get(k, NA) != NA])
                               for k in bundle.DIMENSIONS}},
            "diagnostic": {"assigned": len(diagnostic),
                           "mean_score": _mean([r[2]["score"] for r in diagnostic]),
                           "epoch_input": False},
            "agreement": {
                "state_all": _cell(sum(agree), len(agree)),
                "state_scored": _cell(sum(track_agree["scored"]), len(track_agree["scored"])),
                "state_diagnostic": _cell(sum(track_agree["diagnostic"]),
                                          len(track_agree["diagnostic"])),
                "exact_all": _cell(sum(exact), len(exact))},
            "confusion": {t: {s: confusion[t][s] for s in (*STATES, NO_RESPONSE)}
                          for t in STATES},
            "by_family": {name: {"n": f["n"], "state_agreement": _cell(f["agree"], f["n"]),
                                 "mean_score": _mean(f["scores"])}
                          for name, f in sorted(family.items())},
            "failures": {"invalid_or_missing": sum(not r[2]["valid"] for r in records),
                         "by_reason": {k: reasons[k] for k in sorted(reasons)}},
            "cost": bundle._sum_costs([r[3] for r in records]),
        })
        if method["role"] == "baseline":
            expected = [baseline(by_qid[r["qid"]]) for r in admitted]
            out_methods[-1]["recomputed_from_public_code"] = all(
                canonical_bytes((seen.get(r["qid"]) or {}).get("response")) ==
                canonical_bytes(e) for r, e in zip(admitted, expected, strict=True))
        if case_detail:
            per_case.append((method["method_id"], records))
    base = estimates.get(BASELINE)
    for m in out_methods:
        e = estimates[m["method_id"]]
        m["versus_baseline"] = ({"estimate_delta": NA, "result": NA} if m["role"] == "baseline"
                                else bundle._compare(e, base))
        b = next((x for x in out_methods if x["role"] == "baseline"), None)
        m["versus_baseline"]["agreement_delta"] = (
            NA if b is None or m["role"] == "baseline" or NA in (
                m["agreement"]["state_all"]["fraction"], b["agreement"]["state_all"]["fraction"])
            else m["agreement"]["state_all"]["fraction"] - b["agreement"]["state_all"]["fraction"])
    assigned_scored = sum(r["track"] == "scored" for r in truth["cases"])
    document = {
        "schema_version": SCHEMA, "claim": CLAIM,
        "note": "Shadow results. Testnet weights are unchanged; nothing here sets a weight.",
        "window": {
            "window_id": capsules["window_id"], "opens_at": capsules["opens_at"],
            "closes_at": capsules["closes_at"], "cases": len(truth["cases"]),
            "assigned_scored": assigned_scored,
            "admitted_scored": scored_n, "admitted_diagnostic": len(admitted) - scored_n,
            "reference_failures": len(failures),
            "reference_failure_qids": [r["qid"] for r in failures],
            "status": "VALID" if scored_n >= profile.minimum else "VOID_SAMPLE_FLOOR",
            "minimum_assignments": profile.minimum,
            "reference_failures_tolerated": max(0, assigned_scored - profile.minimum),
            "cases_commitment": capsules["cases_commitment"],
            "truth_commitment": truth["truth_commitment"]},
        "profile": {"profile_id": profile.profile_id, "profile_commitment": profile.commitment,
                    "state_payoff": "state_payoff" in profile.document.get("scoring_rules", {})},
        "evidence": {"same_cases_for_every_method": True,
                     "baseline_recomputed_from_public_code": all(
                         m.get("recomputed_from_public_code", True) for m in out_methods),
                     "integrity": responses.get("integrity_mode", "ASSERTED_FIXTURE")},
        "truth_state_counts": {s: sum(r["truth"]["state"] == s for r in admitted)
                               for s in STATES},
        "methods": out_methods,
        "disclosure": "TRUTH_DERIVED",
    }
    if case_detail:
        document["cases"] = [
            {"position": row["position"], "qid": row["qid"], "family": row["family"],
             "track": row["track"], "truth_state": row["truth"]["state"],
             "methods": {mid: {"state": (rec[i][1]["state"] if rec[i][2]["valid"]
                                         else NO_RESPONSE), "score": rec[i][2]["score"]}
                         for mid, rec in per_case}}
            for i, row in enumerate(admitted)]
    return document


SCORES_ONLY_WINDOW = ("window_id", "opens_at", "closes_at", "cases", "minimum_assignments",
                      "cases_commitment", "truth_commitment")


def scores_only(doc: dict[str, Any]) -> dict[str, Any]:
    """The part of a record that is published at close, before the reveal and the policy decision.

    Agreement, confusion tables, family tables, failure counts, truth state counts, reference
    failures and score dimensions all derive from truth and are withheld. The estimate and its
    eligibility remain: they are the published score, and on a task with three states they still
    constrain the truth (see docs/protocol/window-results.md, "What a score alone reveals").
    """
    return {
        "schema_version": doc["schema_version"], "claim": doc["claim"], "note": doc["note"],
        "disclosure": "SCORES_ONLY",
        "window": {k: doc["window"][k] for k in SCORES_ONLY_WINDOW},
        "profile": doc["profile"],
        "evidence": {k: doc["evidence"][k] for k in ("same_cases_for_every_method",
                                                     "baseline_recomputed_from_public_code",
                                                     "integrity")},
        "methods": [{"method_id": m["method_id"], "uid": m["uid"], "role": m["role"],
                     "score": {k: m["score"][k] for k in ("estimate", "eligible", "reason")},
                     "cost": m["cost"]} for m in doc["methods"]],
    }


def _f(value: Any, digits: int = 4) -> str:
    return value if isinstance(value, str) and value == NA else f"{float(value):.{digits}f}"


def render_scores_only(doc: dict[str, Any]) -> str:
    w, p = doc["window"], doc["profile"]
    lines = [f"# Contest window {w['window_id']}: scores", "", doc["note"], "",
             f"- Window: {w['opens_at']} to {w['closes_at']}; {w['cases']} cases",
             f"- Scoring profile: {p['profile_id']} (`{p['profile_commitment']}`)",
             f"- Cases commitment: `{w['cases_commitment']}`",
             f"- Truth commitment (salted, binds the truth until it is published): "
             f"`{w['truth_commitment']}`",
             "- Withheld until the seed is revealed and truth publication is authorized: "
             "agreement with truth, confusion tables, failure counts and truth state counts.", "",
             "| Method | uid | Role | Epoch estimate | Eligible |", "|---|---|---|---|---|"]
    for m in doc["methods"]:
        s = m["score"]
        eligible = "yes" if s["eligible"] else f"no ({s['reason']})"
        lines.append(f"| {m['method_id']} | {m['uid'] if m['uid'] is not None else '-'} | "
                     f"{m['role']} | {_f(s['estimate'])} | {eligible} |")
    return "\n".join(lines) + "\n"


def render_markdown(doc: dict[str, Any], *, revealed: dict[str, Any] | None) -> str:
    """The human-readable page, built only from the results document (floats on the wire)."""
    if doc["disclosure"] == "SCORES_ONLY":
        return render_scores_only(doc)
    w, p = doc["window"], doc["profile"]
    lines = [f"# Contest window {w['window_id']}: results", "",
             f"{doc['note']}", "",
             f"- Window: {w['opens_at']} to {w['closes_at']}",
             f"- Status: {w['status']} (admitted scored cases {w['admitted_scored']} of "
             f"{w['assigned_scored']} assigned, minimum {w['minimum_assignments']}, "
             f"reference failures {w['reference_failures']}, tolerated "
             f"{w['reference_failures_tolerated']})",
             f"- Scoring profile: {p['profile_id']} (`{p['profile_commitment']}`)",
             f"- Cases commitment: `{w['cases_commitment']}`",
             f"- Truth commitment: `{w['truth_commitment']}`"]
    if revealed:
        lines.append(f"- Seed: revealed and verified against the committed seed commitment "
                     f"`{revealed['seed_commitment']}`")
    ev = doc["evidence"]
    lines += [f"- Equal evidence: every method answered the same {w['cases']} capsules; "
              "baseline recomputed from public code: "
              f"{ev['baseline_recomputed_from_public_code']}; integrity: {ev['integrity']}", "",
              "Truth states in the window (admitted cases): " + ", ".join(
                  f"{s} {n}" for s, n in doc["truth_state_counts"].items()), "",
              "## Scores and agreement with truth", "",
              "| Method | uid | Role | Epoch estimate | Eligible | Agreement (scored) | "
              "Agreement (all) | Invalid or missing | Estimate vs baseline |",
              "|---|---|---|---|---|---|---|---|---|"]
    for m in doc["methods"]:
        s, a = m["score"], m["agreement"]
        eligible = "yes" if s["eligible"] else f"no ({s['reason']})"
        lines.append(
            f"| {m['method_id']} | {m['uid'] if m['uid'] is not None else '-'} | {m['role']} | "
            f"{_f(s['estimate'])} | {eligible} | "
            f"{a['state_scored']['agree']}/{a['state_scored']['n']} "
            f"({_f(a['state_scored']['fraction'], 3)}) | "
            f"{a['state_all']['agree']}/{a['state_all']['n']} "
            f"({_f(a['state_all']['fraction'], 3)}) | "
            f"{m['failures']['invalid_or_missing']} | {m['versus_baseline']['result']} |")
    for m in doc["methods"]:
        lines += ["", f"## {m['method_id']}", "",
                  f"Role {m['role']}. Exact agreement (state and finding codes): "
                  f"{m['agreement']['exact_all']['agree']}/{m['agreement']['exact_all']['n']}. "
                  f"Diagnostic cases: {m['diagnostic']['assigned']} (never an epoch input).", "",
                  "Confusion table, rows are the recomputed truth state, columns the response:",
                  "", "| Truth \\ response | " + " | ".join((*STATES, NO_RESPONSE)) + " |",
                  "|---|" + "---|" * (len(STATES) + 1)]
        for t in STATES:
            lines.append(f"| {t} | " + " | ".join(
                str(m["confusion"][t][s]) for s in (*STATES, NO_RESPONSE)) + " |")
        lines += ["", "| Family | Cases | State agreement | Mean score |", "|---|---|---|---|"]
        for name, f in m["by_family"].items():
            lines.append(f"| {name} | {f['n']} | {f['state_agreement']['agree']}/{f['n']} | "
                         f"{_f(f['mean_score'])} |")
        reasons = ", ".join(f"{k} {v}" for k, v in m["failures"]["by_reason"].items()) or "none"
        lines += ["", f"Validity and integrity failures: {reasons}.", "",
                  "| Cost | Value | Unit | Source or reason |", "|---|---|---|---|"]
        for key, c in m["cost"].items():
            lines.append(f"| {key} | {_f(c['value'], 1)} | {c['unit']} | "
                         f"{c.get('source') or c.get('missing')} |")
    if "cases" in doc:
        ids = [m["method_id"] for m in doc["methods"]]
        lines += ["", "## Per-case rows", "", "| Position | Family | Track | Truth | "
                  + " | ".join(ids) + " |", "|---|---|---|---|" + "---|" * len(ids)]
        for c in doc["cases"]:
            lines.append(f"| {c['position']} | {c['family']} | {c['track']} | {c['truth_state']} | "
                         + " | ".join(f"{c['methods'][i]['state']} ({_f(c['methods'][i]['score'])})"
                                      for i in ids) + " |")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> list[str]:
    capsules, truth, responses = load_inputs(Path(args.capsules), Path(args.truth),
                                             Path(args.responses))
    window = {"window_id": capsules["window_id"], "opens_at": capsules["opens_at"],
              "closes_at": capsules["closes_at"]}
    now = args.now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cw.guard("results", window, now)
    disclose = args.publish_closed_window_truth
    if args.include_case_detail and not disclose:
        raise cw.PhaseError("TRUTH_PUBLICATION_NOT_AUTHORIZED",
                            "per-case rows need --publish-closed-window-truth")
    revealed = None
    if args.reveal:
        if not args.commitments:
            raise ValueError("--reveal needs --commitments")
        commitments = json.loads(Path(args.commitments).read_text("utf-8"))
        reveal = json.loads(Path(args.reveal).read_text("utf-8"))
        regenerated = cw.check_reveal(commitments, reveal)
        if [(e["qid"], e["family"], e["track"]) for e in regenerated] != [
                (r["qid"], r["family"], r["track"]) for r in truth["cases"]]:
            raise ValueError("TRUTH_CASES_DIFFER_FROM_REGENERATED_INSTANCES")
        if canonical_bytes(capsules["capsules"]) != canonical_bytes(
                [e["capsule"] for e in regenerated]):
            raise ValueError("CAPSULES_DIFFER_FROM_REGENERATED_INSTANCES")
        cw.check_truth_document(truth, commitments)
        revealed = next(r for r in commitments["windows"] if r["window_id"] == window["window_id"])
    if disclose:  # truth-derived aggregates: closed, revealed and authorized, like per-case truth
        cw.guard("results-truth-derived", window, now, revealed=revealed is not None,
                 publish_policy=True)
    document = wire(score_window(capsules, truth, responses, args.profile,
                                 case_detail=args.include_case_detail))
    if not disclose:
        document = scores_only(document)
    out = Path(args.out_dir)
    stem = f"window_{window['window_id']}"
    cw.write_new(out / f"{stem}.json", cw.dumps(document))
    cw.write_new(out / f"{stem}.md", render_markdown(document, revealed=revealed))
    return [str(out / f"{stem}.json"), str(out / f"{stem}.md")]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--capsules", required=True, help="window_<id>.capsules.json")
    p.add_argument("--truth", required=True, help="window_<id>.truth.json (or the private file)")
    p.add_argument("--responses", required=True, help="window_<id>.responses.json")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--profile", default=DEFAULT_PROFILE,
                   help="committed profile id (default %(default)s)")
    p.add_argument("--commitments", help="commitments.json (needed with --reveal)")
    p.add_argument("--reveal", help="window_<id>.reveal.json; verified before it is trusted")
    p.add_argument("--now", help="override the clock (ISO 8601 UTC, whole seconds, Z)")
    p.add_argument("--include-case-detail", action="store_true",
                   help="per-case rows; needs --reveal and --publish-closed-window-truth")
    p.add_argument("--publish-closed-window-truth", action="store_true",
                   help="publish truth-derived aggregates (agreement, confusion, failures); "
                   "needs --commitments and --reveal; an open decision (ADR-0020)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        for path in run(args):
            print(path)
    except (cw.PhaseError, ValueError, KeyError, FileExistsError, FileNotFoundError,
            profiles.ProfileNotApplied) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
