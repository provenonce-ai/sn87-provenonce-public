"""IC-APPROVAL-APPLICABILITY candidate, written from the public contract only.

Where the matched baseline cites every event and abstains on any doubt, this method
reconstructs, per action, the approval chain (action -> link -> approval -> review, plus the
policy in force) and cites only that chain as the witness of a finding. It checks the chain's
own validity (approved review, matching scope and artifact, ordering, approval still valid),
abstains when the chain is broken or the governing policy is genuinely ambiguous, but resolves
a same-time tie of governing versions that carry the same condition (the ambiguity is moot).
"""

from __future__ import annotations

from typing import Any

from sn87_provenonce.institutional_v02 import contracts as ic
from sn87_provenonce.miners import register

CLASS_ID = "IC-APPROVAL-APPLICABILITY"
METHOD_ID = "approval_witness"
ABSTAIN = "INSUFFICIENT_EVIDENCE_ABSTAIN"


def _differential(c: dict[str, Any], state: str, witness: set[str]) -> dict[str, Any]:
    findings = [{"code": "STALE_APPROVAL", "severity": ic.DEFECT_SEVERITY["STALE_APPROVAL"],
                 "evidence_refs": sorted(witness), "confidence": "1",
                 "rationale": "The review behind the action's approval certified a condition "
                              "that was no longer the governing one when the action ran."}
                if state == "FINDINGS" else None]
    return {"schema_version": c["schema_version"], "qid": c["qid"],
            "capsule_commitment": c["evidence_commitment"], "method": METHOD_ID, "state": state,
            "rationale": f"Approval-chain witness reconstruction: {state}.",
            "findings": [f for f in findings if f]}


def approval_witness(c: dict[str, Any]) -> dict[str, Any]:
    ic.validate_capsule(c)
    policy = c["policy"]
    if not all(policy["completeness"].values()) or policy["mapping_uncertainty"] != "NONE":
        return _differential(c, ABSTAIN, set())
    by_id = {e["event_id"]: e for e in c["events"]}
    of = {k: [e for e in c["events"] if e["kind"] == k] for k in ic.FIELDS}
    witness: set[str] = set()
    if not of["ACTION"]:
        return _differential(c, ABSTAIN, set())
    for action in of["ACTION"]:
        links = [x for x in of["APPROVAL_LINK"] if x["local_token"] == action["approval_token"]]
        approval = by_id.get(links[0]["approval_ref"]) if len(links) == 1 else None
        # A link may point at any event kind in a contract-valid capsule: check kinds first.
        if not approval or approval["kind"] != "APPROVAL":
            return _differential(c, ABSTAIN, set())
        review = by_id.get(approval["review_ref"])
        if not review or review["kind"] != "REVIEW":
            return _differential(c, ABSTAIN, set())
        link = links[0]
        chain_ok = (review["approved"] and review["at"] < approval["at"] <= link["at"]
                    < action["at"] < approval["valid_until"]
                    and review["scope"] == approval["scope"] == action["scope"]
                    and review["artifact_commitment"] == approval["artifact_commitment"]
                    == action["artifact_commitment"])
        governing = [v for v in of["POLICY_VERSION"]
                     if v["effective_at"] <= action["at"] and v["at"] < action["at"]]
        newest = max((v["effective_at"] for v in governing), default=None)
        current = [v for v in governing if v["effective_at"] == newest]
        if not chain_ok or not current or len({v["condition_commitment"] for v in current}) != 1:
            return _differential(c, ABSTAIN, set())
        if review["condition_commitment"] != current[0]["condition_commitment"]:
            reviewed = [v["event_id"] for v in of["POLICY_VERSION"]
                        if v["condition_commitment"] == review["condition_commitment"]
                        and v["at"] < review["at"]]
            witness |= {action["event_id"], link["event_id"], approval["event_id"],
                        review["event_id"], current[0]["event_id"], *reviewed, "$completeness"}
            for h in of["HANDOFF"]:  # the carried token's lineage across episodes
                if h["carried_token"] == action["approval_token"] and \
                        h["to_episode"] == action["episode"]:
                    witness |= {h["event_id"], *(a["event_id"] for a in of["ACTION"]
                                                 if a["episode"] == h["from_episode"])}
    return _differential(c, "FINDINGS" if witness else "NO_MATERIAL_DEVIATION", witness)


register(CLASS_ID, METHOD_ID, approval_witness)
