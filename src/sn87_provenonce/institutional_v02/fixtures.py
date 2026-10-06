"""Public synthetic First Light case generator (IC-APPROVAL-APPLICABILITY)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sn87_provenonce.canonical import evidence_commitment

from .contracts import FIELDS


def build_case(family, *, identifier=None, timestamp="2026-09-28T00:00:00Z"):
    if family not in ("stale_authority", "fresh_review", "incomplete"):
        raise ValueError("unknown family")
    counter = 0

    def fresh():
        nonlocal counter
        counter += 1
        return identifier() if identifier else f"fixture-{family}-{counter:03d}"

    def digest():
        return "sha256:" + hashlib.sha256(fresh().encode()).hexdigest()

    base = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) - timedelta(
        seconds=100
    )

    def at(offset):
        return (base + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")

    qid, pipeline, nonce = fresh(), fresh(), fresh()
    agents = {"origin": fresh(), "successor": fresh()}
    reviewer, approver = fresh(), fresh()
    scope = {"mission": fresh(), "action": "SEND", "recipient": fresh()}
    artifact, old, new = digest(), digest(), digest()
    source_governance, source_review, source_authority, source_work, source_handoff = [
        fresh() for _ in range(5)
    ]

    def event(kind, offset, source, **kwargs):
        return {
            "event_id": fresh(),
            "kind": kind,
            "at": at(offset),
            "source_system": source,
            **kwargs,
        }

    policies = [
        event(
            "POLICY_VERSION",
            0,
            source_governance,
            effective_at=at(0),
            version_id=fresh(),
            condition_commitment=old,
        ),
        event(
            "POLICY_VERSION",
            40,
            source_governance,
            effective_at=at(50),
            version_id=fresh(),
            condition_commitment=new,
        ),
    ]
    reviews = [
        event(
            "REVIEW",
            5,
            source_review,
            condition_commitment=old,
            scope=scope,
            approved=True,
            actor_id=reviewer,
            artifact_commitment=artifact,
        ),
        event(
            "REVIEW",
            55,
            source_review,
            condition_commitment=new,
            scope=scope,
            approved=True,
            actor_id=reviewer,
            artifact_commitment=artifact,
        ),
    ]
    approvals = [
        event(
            "APPROVAL",
            offset,
            source_authority,
            review_ref=r["event_id"],
            scope=scope,
            artifact_commitment=artifact,
            valid_until=at(99),
            actor_id=approver,
        )
        for r, offset in zip(reviews, (6, 56), strict=True)
    ]
    tokens = [fresh(), fresh()]
    links = [
        event(
            "APPROVAL_LINK",
            offset,
            source_handoff,
            local_token=t,
            approval_ref=a["event_id"],
        )
        for t, a, offset in zip(tokens, approvals, (7, 57), strict=True)
    ]
    last_token = tokens[1] if family == "fresh_review" else tokens[0]
    actions = [
        event(
            "ACTION",
            offset,
            source_work,
            episode=ep,
            actor_id=agents["successor" if ep == 3 else "origin"],
            approval_token=last_token if ep == 3 else tokens[0],
            scope=scope,
            artifact_commitment=artifact,
        )
        for ep, offset in ((1, 10), (2, 30), (3, 80))
    ]
    handoff = event(
        "HANDOFF",
        60,
        source_handoff,
        from_actor=agents["origin"],
        to_actor=agents["successor"],
        from_episode=2,
        to_episode=3,
        carried_token=last_token,
        input_commitment=artifact,
        output_commitment=artifact,
    )
    events = policies + reviews + approvals + links + [handoff] + actions
    completeness = dict.fromkeys(FIELDS, True)
    if family == "incomplete":
        completeness["APPROVAL_LINK"] = False
        events = [e for e in events if e["event_id"] != links[0]["event_id"]]
    c = {
        "schema_version": "institution/0.2",
        "qid": qid,
        "pipeline_id": pipeline,
        "events": events,
        "source_commitments": [digest() for _ in range(5)],
        "policy": {
            "qid": qid,
            "grammar": "FIRST_LIGHT_MINIMAL_TYPE_C_0.2",
            "agents": agents,
            "reviewer": reviewer,
            "approver": approver,
            "episode_range": [1, 2, 3],
            "completeness": completeness,
            "mapping_uncertainty": "NONE",
        },
        "nonce": nonce,
        "timestamp": timestamp,
    }
    c["evidence_commitment"] = evidence_commitment(c)
    return c
