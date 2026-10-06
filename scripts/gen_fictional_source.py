"""Generator for the FICTIONAL launch-approvals source fixture (all names, notes and URLs are
invented). Deterministic; tests regenerate it and compare with the committed files."""
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Usage: python scripts/gen_fictional_source.py [OUT_DIR]; default is the committed fixture dir.
OUT = (sys.argv[1].rstrip("/") + "/") if len(sys.argv) > 1 else str(
    Path(__file__).resolve().parents[1] / "src/sn87_provenonce/sources/fixtures") + "/"
def ts(base, minutes):
    return (base + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
def case(week, n, base, stale, jitter, gap=False, flaw=None):
    ref = f"{week}-{n:03d}"
    t = lambda m: ts(base, m)
    P = f"aurora-{ref}"
    mission, recip = f"{P}-mission", f"{P}-desk"
    art = f"Launch notice draft {ref} (fictional)"
    old, new = f"Condition v1 for {ref}: two reviewers (fictional)", f"Condition v2 for {ref}: three reviewers (fictional)"
    j = jitter
    def e(i, typ, minute, **kw):
        d = {"id": f"{ref}-{i}", "type": typ, "ts": t(minute)}; d.update(kw); return d
    log = [
        e("pol1", "policy_published", 0, effective_ts=t(0), policy_ref=f"{P}-pol1", condition_text=old),
        e("pol2", "policy_published", 40 + j, effective_ts=t(50 + j), policy_ref=f"{P}-pol2", condition_text=new),
        e("rev1", "review_signed", 5, condition_text=old, approved=True, reviewer=f"{P}-rev", mission=mission, recipient=recip, artifact_text=art, note="Fictional reviewer note: looks fine."),
        e("rev2", "review_signed", 55 + j, condition_text=new, approved=True, reviewer=f"{P}-rev", mission=mission, recipient=recip, artifact_text=art),
        e("apr1", "approval_issued", 6, review_id=f"{ref}-rev1", approver=f"{P}-apr", valid_until=t(130 + j), mission=mission, recipient=recip, artifact_text=art, ticket_url="https://example.invalid/fictional/ticket/" + ref),
        e("apr2", "approval_issued", 56 + j, review_id=f"{ref}-rev2", approver=f"{P}-apr", valid_until=t(130 + j), mission=mission, recipient=recip, artifact_text=art),
        e("tok1", "token_bound", 7, token=f"{P}-tok1", approval_id=f"{ref}-apr1"),
        e("tok2", "token_bound", 57 + j, token=f"{P}-tok2", approval_id=f"{ref}-apr2"),
    ]
    carried = f"{P}-tok1" if stale else f"{P}-tok2"
    log += [
        e("hand", "handoff", 60 + j, from_agent=f"{P}-a", to_agent=f"{P}-b", from_step=2, to_step=3, token=carried, input_text=art, output_text=art),
        e("act1", "step_executed", 10, step=1, agent=f"{P}-a", token=f"{P}-tok1", mission=mission, recipient=recip, artifact_text=art),
        e("act2", "step_executed", 30, step=2, agent=f"{P}-a", token=f"{P}-tok1", mission=mission, recipient=recip, artifact_text=art),
        e("act3", "step_executed", 80 + j, step=3, agent=f"{P}-b", token=carried, mission=mission, recipient=recip, artifact_text=art),
    ]
    gaps = []
    if gap:
        log = [x for x in log if x["id"] != f"{ref}-tok1"]; gaps = ["token_bound"]
    if flaw == "missing_approved":
        del log[2]["approved"]
    elif flaw == "step4":
        log[-1]["step"] = 4
    elif flaw == "bad_ts":
        log[3]["ts"] = "2026-09-24 10:00"
    elif flaw == "dup_id":
        log[1]["id"] = log[0]["id"]
    return {"case_ref": ref, "pipeline": P, "origin_agent": f"{P}-a", "successor_agent": f"{P}-b",
            "reviewer_id": f"{P}-rev", "approver_id": f"{P}-apr", "reviewer_name": "Pat Fictional",
            "reviewer_comment": "Fictional free-text comment, not to be mapped.", "gaps": gaps, "log": log}
def export(week, start, close, plan):
    base0 = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    cases = []
    for n, (stale, gap, flaw) in enumerate(plan, 1):
        base = base0 + timedelta(hours=7 * n)   # spread over the window
        cases.append(case(week, n, base, stale, (n * 3) % 10, gap, flaw))
    return {"export_id": f"aurora-{week}", "window": {"opened_at": start, "closed_at": close}, "cases": cases}
S, F, G, N = True, False, True, None
plan38 = [(S,F,N),(F,F,N),(S,F,N),(S,F,N),(F,F,N),(S,F,"missing_approved"),(S,F,N),(S,G,N),(F,F,N),(S,F,N),(S,F,N),(F,F,N),(S,F,"step4"),(S,F,N),(F,G,N),(S,F,N)]
plan39 = [(S,F,N),(F,F,N),(F,F,N),(S,F,N),(S,F,"bad_ts"),(F,F,N),(S,F,N),(S,G,N),(F,F,N),(S,F,N),(S,F,N),(F,G,N),(S,F,"dup_id"),(F,F,N),(S,F,N),(S,G,N),(S,F,N)]
doc = {"schema_id": "fictional-launch-approvals/1",
       "label": "FICTIONAL: Aurora Launch Office is an invented organisation; every record, name and identifier below is synthetic. Not derived from any real source.",
       "exports": [export("w38", "2026-09-14T00:00:00Z", "2026-09-20T23:59:59Z", plan38),
                   export("w39", "2026-09-21T00:00:00Z", "2026-09-27T23:59:59Z", plan39)]}
json.dump(doc, open(OUT + "fictional_launch_approvals.json", "w"), indent=1, sort_keys=True); open(OUT + "fictional_launch_approvals.json", "a").write("\n")
perm = {"permission_id": "perm-aurora-launch-approvals-001", "fictional": True,
        "scope": "FICTIONAL grant: read-only, IC-APPROVAL-APPLICABILITY evidence from the Aurora launch-approvals log; identifiers and structural fields only",
        "meaning_version": "aurora-approval-meaning/1", "expires_at": "2026-12-31T00:00:00Z",
        "allowed_fields": sorted(["case_ref","pipeline","origin_agent","successor_agent","reviewer_id","approver_id","gaps","log","id","type","ts","effective_ts","policy_ref","condition_text","approved","reviewer","mission","recipient","artifact_text","review_id","approver","valid_until","token","approval_id","from_agent","to_agent","from_step","to_step","input_text","output_text","step","agent"])}
json.dump(perm, open(OUT + "fictional_launch_permission.json", "w"), indent=1, sort_keys=True); open(OUT + "fictional_launch_permission.json", "a").write("\n")
