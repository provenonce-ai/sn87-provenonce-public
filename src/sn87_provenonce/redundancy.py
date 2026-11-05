"""Redundancy groups (ADR-0022).

Pure functions on already-collected answers; no clock, no network, no file. Identities whose
decision vectors (declared state and set of finding codes, per case) are identical on every case
share a single weight, see ``scoring.preference_row``, which computes the groups itself from the
answers and refuses groups a caller supplies that disagree. Two independent miners that are both
right on every case have the same decision vector and are therefore grouped: the rule cannot
tell agreement from copying. That is an open design question, and the rule has a second limit,
both stated in ADR-0022.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def answer_key(response: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
    """The decision vector of one answer: the declared state and the set of finding codes.

    Citations, declared severity, confidence, rationale, method name, commitments and order are
    left out. They cost little or nothing to vary, so keying on them would let an identity
    escape its group by varying only those (ADR-0022). A missing response
    has no key.
    """
    if response is None:
        return None
    return (response["state"], tuple(sorted({f["code"] for f in response["findings"]})))


def redundancy_groups(
    answers: Mapping[str, Mapping[str, Mapping[str, Any] | None]],
) -> list[list[str]]:
    """Groups of two or more identities whose answers are identical on every case.

    ``answers`` maps identity -> case id -> response (or None). Two identities are in one group
    when they answered the same set of cases (at least one) and every answer has the same key.
    Identity is an equivalence relation here, so the groups are exact and sorted.
    """
    buckets: dict[tuple[Any, ...], list[str]] = {}
    for identity, by_case in answers.items():
        keys = tuple(sorted((case, answer_key(r)) for case, r in by_case.items() if r is not None))
        if keys:
            buckets.setdefault(keys, []).append(identity)
    return sorted(sorted(members) for members in buckets.values() if len(members) > 1)
