"""The baseline-headroom gate: a family earns weight only above EVERY public method.

The gate is a check the weighting tools must call. These tests use fake estimates and fake
bundles; nothing here sets a weight, and a source test proves no live weight path calls it.
"""

import copy
import re
from pathlib import Path

import pytest
from conftest import REASON, executors_available

from sn87_provenonce import bundle as bundle_module
from sn87_provenonce.bundle import (
    ELIGIBLE,
    FAMILY_ACTIVE,
    GATE_BELOW,
    GATE_NOT_COMPARABLE,
    GATE_NULL,
    GATE_PUBLIC,
    GATE_REFERENCE,
    MIN_MARGIN,
    RETIRE_RECOMMENDED,
    SCHEMA,
    WeightGateRefused,
    bundle_gate,
    candidate_gate,
    family_gate,
    public_methods,
    require_weight_eligible,
)
from sn87_provenonce.classes import BINDINGS
from sn87_provenonce.scoring import wire

ROOT = Path(__file__).parents[1]
IC = "IC-APPROVAL-APPLICABILITY"
BASE, WITNESS = "public_contract_baseline", "approval_witness"
PUBLIC = (BASE, WITNESS)


def test_the_public_methods_of_the_ic_family_are_the_baseline_and_approval_witness():
    assert public_methods(IC) == (BASE, WITNESS)
    assert public_methods("TYPE-C-RELEASE") == (BASE,)  # no published candidate method yet


@pytest.mark.parametrize("class_id", ["NO-SUCH-CLASS", "", None, 7])
def test_an_unbound_class_is_refused_not_reduced_to_the_baseline(class_id):
    with pytest.raises(WeightGateRefused, match="WEIGHT_GATE_CLASS_NOT_BOUND"):
        public_methods(class_id)
    with pytest.raises(WeightGateRefused, match="WEIGHT_GATE_CLASS_NOT_BOUND"):
        family_gate({"new": 0.9, BASE: 0.5}, class_id, {"new": "candidate"})


def test_the_margin_is_documented_and_a_lead_inside_it_is_a_tie():
    assert MIN_MARGIN == 0.001
    inside = candidate_gate({"new": 0.5 + MIN_MARGIN / 2, BASE: 0.5, WITNESS: 0.1}, "new", PUBLIC)
    assert inside["verdict"] == GATE_NULL and inside["blocked_by"] == [BASE]
    edge = candidate_gate({"new": 0.75, BASE: 0.75 - MIN_MARGIN, WITNESS: 0.1}, "new", PUBLIC)
    assert edge["verdict"] == ELIGIBLE
    behind = candidate_gate({"new": 0.5, BASE: 0.5 + MIN_MARGIN / 2, WITNESS: 0.1}, "new", PUBLIC)
    assert behind["verdict"] == GATE_NULL  # not ahead by the margin, not behind by it
    assert candidate_gate({"new": 0.5, BASE: 0.5 + MIN_MARGIN, WITNESS: 0.1}, "new",
                          PUBLIC)["verdict"] == GATE_BELOW


def test_a_candidate_above_every_public_method_is_eligible():
    gate = candidate_gate({"new": 0.9, BASE: 0.5, WITNESS: 0.6}, "new", PUBLIC)
    assert gate["verdict"] == ELIGIBLE and gate["weight_eligible"] is True
    assert gate["compared_with"] == [WITNESS, BASE] and gate["blocked_by"] == []
    assert gate["compared"][WITNESS] == {"estimate_delta": pytest.approx(0.3),
                                         "result": "ABOVE_BASELINE"}


def test_a_tie_with_any_public_method_is_null_no_headroom_and_refuses():
    gate = candidate_gate({"new": 0.6, BASE: 0.5, WITNESS: 0.6}, "new", PUBLIC)
    assert gate["verdict"] == GATE_NULL and gate["weight_eligible"] is False
    assert gate["blocked_by"] == [WITNESS]
    # beating the baseline alone is not enough: approval_witness is a public method too
    assert candidate_gate({"new": 0.6, BASE: 0.5, WITNESS: 0.6}, "new", (BASE,))["weight_eligible"]


def test_a_candidate_below_any_public_method_refuses():
    gate = candidate_gate({"new": 0.7, BASE: 0.5, WITNESS: 0.8}, "new", PUBLIC)
    assert gate["verdict"] == GATE_BELOW and gate["weight_eligible"] is False
    assert gate["blocked_by"] == [WITNESS]
    both = candidate_gate({"new": 0.5, BASE: 0.5, WITNESS: 0.8}, "new", PUBLIC)
    assert both["verdict"] == GATE_BELOW and both["blocked_by"] == [WITNESS, BASE]


@pytest.mark.parametrize("estimates", [
    {"new": None, BASE: 0.5, WITNESS: 0.6},       # the candidate's own estimate is missing
    {"new": 0.9, BASE: None, WITNESS: 0.6},       # a public method has none
    {"new": 0.9, BASE: 0.5},                      # approval_witness was not evaluated
    {"new": float("nan"), BASE: 0.5, WITNESS: 0.6},
    {"new": 0.9, BASE: 1.5, WITNESS: 0.6},        # out of range
    {"new": "0.9", BASE: 0.5, WITNESS: 0.6},      # not a number
    {"new": 1, BASE: 0.5, WITNESS: 0.6},          # an int is not a float estimate
    {"new": 0.9, BASE: 0, WITNESS: 0.6},
    {},
])
def test_a_missing_or_unusable_estimate_refuses(estimates):
    gate = candidate_gate(estimates, "new", PUBLIC)
    assert gate["verdict"] == GATE_NOT_COMPARABLE and gate["weight_eligible"] is False


def test_a_public_method_cannot_earn_weight_whatever_it_scores():
    gate = candidate_gate({WITNESS: 0.9, BASE: 0.5}, WITNESS, PUBLIC)
    assert gate["compared_with"] == [BASE] and gate["compared"][BASE]["result"] == "ABOVE_BASELINE"
    assert gate["verdict"] == GATE_PUBLIC and gate["weight_eligible"] is False
    assert candidate_gate({BASE: 0.9, WITNESS: 0.5}, BASE, PUBLIC)["verdict"] == GATE_PUBLIC


CAND = {"a": "candidate", "b": "candidate"}


def test_the_family_is_weight_eligible_only_if_a_candidate_beats_every_public_method():
    estimates = {"a": 0.9, "b": 0.6, BASE: 0.5, WITNESS: 0.6}
    gate = family_gate(estimates, IC, CAND)
    assert gate["family"] == {"weight_eligible": True, "eligible_methods": ["a"],
                              "status": FAMILY_ACTIVE}
    assert gate["methods"]["b"]["verdict"] == GATE_NULL
    none = family_gate({"a": 0.6, "b": 0.5, BASE: 0.5, WITNESS: 0.6}, IC, CAND)
    assert none["family"]["weight_eligible"] is False and none["family"]["eligible_methods"] == []
    assert "not wired into any live weight path" in gate["note"]


def test_a_family_whose_public_methods_all_sit_at_the_ceiling_is_marked_retire_recommended():
    saturated = {"a": 1.0, "b": 1.0, BASE: 1.0, WITNESS: 1.0}
    gate = family_gate(saturated, IC, CAND)
    assert gate["family"]["status"] == RETIRE_RECOMMENDED
    assert gate["family"]["weight_eligible"] is False
    assert all(g["verdict"] == GATE_NULL for g in gate["methods"].values())
    # one public method below the ceiling: not saturated
    assert family_gate(saturated | {BASE: 0.99}, IC, {"a": "candidate"})["family"]["status"] \
        == FAMILY_ACTIVE
    # a public method that was not evaluated cannot be assumed saturated
    unevaluated = {"a": 1.0, BASE: 1.0}
    gate = family_gate(unevaluated, IC, {"a": "candidate"})
    assert gate["family"]["status"] == FAMILY_ACTIVE
    assert gate["public_methods_not_evaluated"] == [WITNESS]
    # a missing estimate is not saturation
    assert family_gate(saturated | {WITNESS: None}, IC, {"a": "candidate"})["family"][
        "status"] == FAMILY_ACTIVE


def test_a_reference_method_is_never_a_subject():
    estimates = {"state_machine": 0.99, "a": 0.9, BASE: 0.1, WITNESS: 0.1}
    gate = family_gate(estimates, IC, {"state_machine": "reference", "a": "candidate"})
    assert gate["methods"]["state_machine"]["verdict"] == GATE_REFERENCE
    assert gate["methods"]["state_machine"]["weight_eligible"] is False
    assert gate["family"]["eligible_methods"] == ["a"]
    odd = family_gate(estimates, IC, {"state_machine": "mystery"})
    assert odd["methods"]["state_machine"]["verdict"] == GATE_NOT_COMPARABLE


# ------------------------------------------------------------- the check weighting tools call
def fake_bundle(estimates, *, roles=None, with_section=False, class_id=IC):
    profile = BINDINGS[class_id].profile
    from sn87_provenonce.profile import REGISTRY

    methods = [m for m in estimates if m != BASE]
    bundle = {
        "schema_version": SCHEMA,
        "manifest": {"class_id": class_id, "profile_id": profile.profile_id,
                     "profile_commitment": profile.commitment, "profile_applied": True,
                     "profile_commitment_domain": REGISTRY[profile.profile_id][1],
                     "profile_document": copy.deepcopy(profile.document)},
        "methods": [{"method_id": m, "role": (roles or {}).get(m, "candidate"), "uid": None}
                    for m in methods] + [{"method_id": BASE, "role": "baseline", "uid": None}],
        "scores": {m: {"estimate": "NA" if e is None else wire(e)}
                   for m, e in estimates.items()},
    }
    if with_section:
        bundle["weight_gate"] = wire(bundle_gate(bundle))
    return bundle


def refused(source, method, match):
    with pytest.raises(WeightGateRefused, match=match):
        require_weight_eligible(source, method)


def test_require_weight_eligible_passes_only_for_a_method_above_every_public_method():
    good = fake_bundle({"new": 0.9, BASE: 0.5, WITNESS: 0.6})
    require_weight_eligible(good, "new")
    refused(good, WITNESS, f"WEIGHT_GATE_REFUSES: {GATE_PUBLIC}")
    refused(good, BASE, "WEIGHT_GATE_METHOD_NOT_A_SUBJECT")  # the baseline is never a subject
    refused(good, "unknown", "WEIGHT_GATE_METHOD_NOT_A_SUBJECT")
    tie = fake_bundle({"new": 0.6, BASE: 0.5, WITNESS: 0.6})
    refused(tie, "new", f"WEIGHT_GATE_REFUSES: {GATE_NULL}")
    refused(fake_bundle({"new": 0.9, BASE: 0.5}), "new", f"WEIGHT_GATE_REFUSES: "
            f"{GATE_NOT_COMPARABLE}")


def test_a_reference_method_in_a_bundle_is_refused():
    bundle = fake_bundle({"state_machine": 0.99, BASE: 0.1, WITNESS: 0.1},
                         roles={"state_machine": "reference"})
    refused(bundle, "state_machine", f"WEIGHT_GATE_REFUSES: {GATE_REFERENCE}")


def test_a_crafted_bundle_cannot_pass_on_an_unbound_class_or_a_foreign_profile():
    good = fake_bundle({"new": 0.9, BASE: 0.5, WITNESS: 0.6})
    require_weight_eligible(good, "new")
    unknown = copy.deepcopy(good)
    unknown["manifest"]["class_id"] = "NO-SUCH-CLASS"  # only the baseline would be "public"
    del unknown["scores"][WITNESS]
    unknown["methods"] = [m for m in unknown["methods"] if m["method_id"] != WITNESS]
    refused(unknown, "new", "WEIGHT_GATE_CLASS_NOT_BOUND")
    mutations = {
        "schema": lambda b: b.update(schema_version="sn87-evidence-bundle/0.2"),
        "commitment": lambda b: b["manifest"].update(profile_commitment="sha256:" + "0" * 64),
        "profile id": lambda b: b["manifest"].update(profile_id="OTHER"),
        "not applied": lambda b: b["manifest"].update(profile_applied=False),
        "domain": lambda b: b["manifest"].update(profile_commitment_domain="x"),
        "document": lambda b: b["manifest"]["profile_document"].update(tail=0.4),
        "no baseline": lambda b: b["methods"].pop(),
        "extra score": lambda b: b["scores"].update(ghost={"estimate": "1"}),
        "no manifest": lambda b: b.pop("manifest"),
    }
    for mutate in mutations.values():
        bad = copy.deepcopy(good)
        mutate(bad)
        with pytest.raises(WeightGateRefused, match="WEIGHT_GATE_"):
            require_weight_eligible(bad, "new")


def test_a_retire_recommended_family_refuses_every_method():
    saturated = fake_bundle({"new": 1.0, BASE: 1.0, WITNESS: 1.0})
    assert bundle_gate(saturated)["family"]["status"] == RETIRE_RECOMMENDED
    refused(saturated, "new", f"WEIGHT_GATE_REFUSES: {GATE_NULL} .*{RETIRE_RECOMMENDED}")


def test_the_gate_is_recomputed_from_the_scores_not_trusted_from_the_bundle():
    tie = fake_bundle({"new": 0.6, BASE: 0.5, WITNESS: 0.6}, with_section=True)
    forged = copy.deepcopy(tie)
    forged["weight_gate"]["methods"]["new"].update(verdict=ELIGIBLE, weight_eligible=True)
    forged["weight_gate"]["family"].update(weight_eligible=True, eligible_methods=["new"])
    refused(forged, "new", "WEIGHT_GATE_SECTION_DIFFERS_FROM_SCORES")
    # a bundle whose scores were edited after the section was written
    edited = fake_bundle({"new": 0.6, BASE: 0.5, WITNESS: 0.6}, with_section=True)
    edited["scores"]["new"]["estimate"] = "0.9"
    refused(edited, "new", "WEIGHT_GATE_SECTION_DIFFERS_FROM_SCORES")
    # an honest section agrees and the verdict stands
    good = fake_bundle({"new": 0.9, BASE: 0.5, WITNESS: 0.6}, with_section=True)
    require_weight_eligible(good, "new")


@pytest.mark.parametrize("source", [None, {}, [], "x", {"scores": {}},
                                    {"scores": {}, "manifest": {}, "methods": []},
                                    {"schema_version": "other"}])
def test_a_missing_or_malformed_bundle_refuses(source):
    with pytest.raises(WeightGateRefused):
        require_weight_eligible(source, "new")


def test_a_bare_gate_dict_is_never_trusted():
    gate = family_gate({"new": 0.9, BASE: 0.5, WITNESS: 0.6}, IC, {"new": "candidate"})
    assert gate["methods"]["new"]["weight_eligible"] is True
    refused(gate, "new", "WEIGHT_GATE_NEEDS_A_BUNDLE")
    refused({"weight_gate": gate}, "new", "WEIGHT_GATE_NEEDS_A_BUNDLE")


def test_an_unlisted_method_is_not_a_subject():
    refused(fake_bundle({"new": 0.9, BASE: 0.5, WITNESS: 0.6}), "ghost",
            "WEIGHT_GATE_METHOD_NOT_A_SUBJECT")


def test_no_live_weight_path_calls_the_gate():
    """The gate is a check weighting tools must call; this change wires it into none of them.

    Every script or module that can build or send a weight row (it mentions set_weights,
    set_mechanism_weights, a commit_ call or u16_weights) is found by grep, not listed by name,
    and none of them may reference the gate. The only gate users are bundle.py and tests.
    """
    pattern = re.compile(r"set_mechanism_weights|set_weights|commit_|u16_weights")
    gate = re.compile(r"require_weight_eligible|candidate_gate|family_gate|bundle_gate|weight_gate")
    # Readers and recompute-only tools, none of which writes a weight (asserted below). The
    # lifecycle demo reports the gate verdict and checks an empty row against an empty pinned row.
    # admission_plan.propose_version recomputes the verdict while it builds a PROPOSED plan version,
    # so a plan cannot be built for a family the gate refuses; compose_row, the function the weight
    # paths call, does not use it. bundle.py, reproduce_window.py and gen_repro_fixture.py re-run a
    # published gate verdict or build a fixture; they build no row for a chain.
    recompute_only = {"bundle.py", "reproduce_window.py", "gen_repro_fixture.py",
                      "contest_lifecycle_demo.py", "admission_plan.py"}
    files = [p for base in ("scripts", "src") for p in (ROOT / base).rglob("*.py")
             if p.name not in recompute_only
             and "headroom" not in p.relative_to(ROOT).parts  # ADR-0024: calls the gate, no weights
             and p.name != "headroom_test.py"]
    weighting = [p for p in files if pattern.search(p.read_text())]
    names = {p.name for p in weighting}
    # The private operator scripts are absent from the public export, so the floor follows
    # which of them exist; the private tree keeps the full floor.
    operator = {"flip_live.py", "flip_chain.py", "flip_to_testnet.py", "flip_auth.py"}
    private_tree = all((ROOT / "scripts" / n).exists() for n in operator)
    assert len(weighting) >= (8 if private_tree else 3)  # the grep finds the real weighting tools
    expected = {"commit_reveal_weights.py", "weights_dry_run.py"}
    if private_tree:
        expected |= {"flip_live.py"}
    assert expected <= names
    assert [p.name for p in weighting if gate.search(p.read_text())] == []
    users = sorted(p.relative_to(ROOT).as_posix() for p in files if gate.search(p.read_text()))
    assert users == []  # nothing else uses it yet
    plan = (ROOT / "scripts" / "admission_plan.py").read_text()
    assert not re.search(r"set_mechanism_weights|set_weights|commit_reveal|commit_weights", plan)
    import ast

    functions = {n.name: ast.get_source_segment(plan, n) for n in ast.parse(plan).body
                 if isinstance(n, ast.FunctionDef)}
    assert "gate" not in functions["compose_row"].lower()
    assert "gate" not in functions["eligible_row_uids"].lower()
    assert "gate_verdict(" in functions["propose_version"]
    demo_path = ROOT / "scripts" / "contest_lifecycle_demo.py"
    if not demo_path.exists():  # the demo needs the private reference executors: not exported
        return
    demo = demo_path.read_text()
    # it writes nothing (commit_lead_hours is a schedule setting, not a weight commit)
    assert not re.search(r"set_mechanism_weights|set_weights|commit_reveal|commit_weights", demo)
    assert re.search(r"family_gate", demo) and "compose_row" in demo


# ---------------------------------------------------------------------- the bundle output
pytestmark_exec = pytest.mark.skipif(not executors_available(), reason=REASON)


@pytestmark_exec
def test_the_weight_gate_section_is_opt_in_and_leaves_default_bundles_unchanged():
    from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as BOUND

    plain = bundle_module.fixture_run(BOUND)
    assert "weight_gate" not in plain and plain["manifest"]["profile_commitment"]
    section = bundle_gate(plain)  # a real bundle passes the bundle checks
    # the fixture bundle holds the references and the baseline: approval_witness is not
    # evaluated, so nothing is comparable and nothing is weight-eligible
    assert section["family"]["weight_eligible"] is False
    assert section["public_methods_not_evaluated"] == [WITNESS]
    assert {g["verdict"] for g in section["methods"].values()} == {GATE_REFERENCE}
    for method in section["methods"]:
        refused(plain, method, "WEIGHT_GATE_REFUSES")


@pytestmark_exec
def test_evaluate_with_weight_gate_embeds_the_gate_and_a_tie_with_the_public_methods_refuses():
    from sn87_provenonce.bundle import COST_UNITS, cost_record, evaluate
    from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as BOUND
    from sn87_provenonce.classes import with_candidates
    from sn87_provenonce.miners import for_class
    from sn87_provenonce.scoring import Integrity

    binding = with_candidates(BOUND, {WITNESS: for_class(IC)[WITNESS]})
    cases = []
    for family, count in binding.profile.document["assignment"].items():
        for _ in range(count):
            capsule = binding.generate(family, len(cases))
            cases.append({"qid": capsule["qid"], "track": "scored", "family": family,
                          "capsule": capsule, "truth": binding.reference(capsule)})
    observed = {m: {c["qid"]: {"response": fn(c["capsule"]),
                               "integrity": Integrity(*[True] * 6),
                               "cost": cost_record({}, dict.fromkeys(COST_UNITS, "NOT_RECORDED"))}
                    for c in cases} for m, fn in binding.candidates.items()}
    common = dict(mode="FIXTURE", run_id="r", window={"opened_at": "a", "closed_at": "b"},
                  source_digest="sha256:" + "0" * 64,
                  profile_commitment=binding.profile.commitment)
    plain = evaluate(binding, cases, observed, **common)
    gated = evaluate(binding, cases, observed, weight_gate=True, **common)
    assert "weight_gate" not in plain
    # the baseline's wall and CPU times are measured per call, so cost differs run to run
    assert {k: v for k, v in gated.items() if k not in ("weight_gate", "cost")} \
        == {k: v for k, v in plain.items() if k != "cost"}
    section = gated["weight_gate"]
    assert section == wire(bundle_gate(gated))
    assert section["public_methods_not_evaluated"] == []
    # every method, the baseline and approval_witness included, scores 1 on the published
    # fixtures: a tie everywhere, so no method is eligible and the family is saturated
    assert {m: g["verdict"] for m, g in section["methods"].items()} == {
        "state_machine": GATE_REFERENCE, "relational": GATE_REFERENCE, WITNESS: GATE_PUBLIC}
    assert section["family"] == {"weight_eligible": False, "eligible_methods": [],
                                 "status": RETIRE_RECOMMENDED}
    for method in section["methods"]:
        refused(gated, method, "WEIGHT_GATE_REFUSES")
