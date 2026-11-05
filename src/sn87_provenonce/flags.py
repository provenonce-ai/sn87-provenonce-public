"""Non-scoring flags recorded beside window results (ADR-0022).

Pure functions on already-collected answers and timestamps; nothing here feeds a score, and the
scorer does not import this module. See ``redundancy`` for the grouping that the scorer does use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sn87_provenonce.redundancy import answer_key

USE = "NEVER_A_SCORE_INPUT_NEVER_IN_THE_PREFERENCE_ROW"


def _fraction(n: int, d: int) -> str:
    return format(n / d, ".17g") if d else "NA"


def observation_flags(
    observations: Mapping[str, Mapping[str, Mapping[str, Any]]], params: Mapping[str, Any]
) -> dict[str, Any]:
    """Pairwise flags, recorded in results and never scored.

    ``observations``: identity -> case id -> {"response", "dispatched_at", "responded_at"}
    (seconds; a missing timestamp is None). ``params`` are the profile's flag parameters:
    ``dispatch_window_seconds``, ``latency_difference_seconds``, ``pair_share``, ``min_cases``.

    * ``SIMULTANEOUS_DISPATCH``: the two identities were sent the same cases within the window.
    * ``SIMILAR_RESPONSE_TIME``: their dispatch-to-response times differ by no more than the limit.
    * ``IDENTICAL_ANSWERS_ON_SEPARATING_TASKS``: on cases where the answers of the identities
      are not all alike (the case separates methods), the pair gave the same answer.

    A pair is flagged when it has at least ``min_cases`` comparable cases and the share of
    matching ones reaches ``pair_share``.
    """
    window = float(params["dispatch_window_seconds"])
    limit = float(params["latency_difference_seconds"])
    need, minimum = float(params["pair_share"]), int(params["min_cases"])
    identities = sorted(observations)
    cases = sorted({c for by in observations.values() for c in by})
    separating = []
    for case in cases:
        keys = {
            answer_key(observations[i][case]["response"])
            for i in identities
            if case in observations[i] and observations[i][case]["response"] is not None
        }
        keys.discard(None)
        if len(keys) > 1:
            separating.append(case)
    timed = any(
        o.get("dispatched_at") is not None and o.get("responded_at") is not None
        for by in observations.values()
        for o in by.values()
    )
    out: dict[str, Any] = {
        "scored": False,
        "use": USE,
        "separating_tasks": len(separating),
        "timing": "RECORDED" if timed else "NOT_RECORDED",
        "SIMULTANEOUS_DISPATCH": [],
        "SIMILAR_RESPONSE_TIME": [],
        "IDENTICAL_ANSWERS_ON_SEPARATING_TASKS": [],
    }
    for ai, a in enumerate(identities):
        for b in identities[ai + 1 :]:
            oa, ob = observations[a], observations[b]
            common = [c for c in cases if c in oa and c in ob]
            both = [
                c for c in common if oa[c]["response"] is not None and ob[c]["response"] is not None
            ]
            dispatch = [
                abs(oa[c]["dispatched_at"] - ob[c]["dispatched_at"])
                for c in common
                if oa[c].get("dispatched_at") is not None and ob[c].get("dispatched_at") is not None
            ]
            latency = [
                abs(
                    (oa[c]["responded_at"] - oa[c]["dispatched_at"])
                    - (ob[c]["responded_at"] - ob[c]["dispatched_at"])
                )
                for c in both
                if None
                not in (
                    oa[c].get("dispatched_at"),
                    oa[c].get("responded_at"),
                    ob[c].get("dispatched_at"),
                    ob[c].get("responded_at"),
                )
            ]
            same = [
                (key := answer_key(oa[c]["response"])) is not None
                and key == answer_key(ob[c]["response"])
                for c in both
                if c in separating
            ]
            for name, hits, n in (
                ("SIMULTANEOUS_DISPATCH", sum(d <= window for d in dispatch), len(dispatch)),
                ("SIMILAR_RESPONSE_TIME", sum(d <= limit for d in latency), len(latency)),
                ("IDENTICAL_ANSWERS_ON_SEPARATING_TASKS", sum(same), len(same)),
            ):
                if n >= minimum and hits / n >= need:
                    out[name].append(
                        {"pair": [a, b], "cases": n, "matching": hits, "share": _fraction(hits, n)}
                    )
    return out
