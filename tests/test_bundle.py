"""The evidence bundle: one dry run, every identity on board, NA never 0, status matrix live."""

import importlib
import math
from pathlib import Path

import pytest

from sn87_provenonce.bundle import (
    COST_UNITS,
    DIMENSIONS,
    STATUS_MATRIX,
    cost_record,
    evaluate,
    fixture_run,
)
from sn87_provenonce.canonical import canonical_bytes
from sn87_provenonce.classes import BINDINGS
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.profile import ProfileNotApplied
from sn87_provenonce.scoring import Integrity, epoch_estimate, wire

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("class_id", sorted(BINDINGS))
def test_fixture_bundle_end_to_end(class_id):
    bundle = fixture_run(BINDINGS[class_id])
    canonical_bytes(bundle, max_bytes=4 * 1024 * 1024)  # no floats anywhere
    assert bundle["mode"] == "FIXTURE" and bundle["claim"] == "CONFORMANCE_ONLY"
    manifest = bundle["manifest"]
    assert manifest["class_id"] == class_id and manifest["canonicalizer_id"] == "gra/0.1"
    assert manifest["profile_applied"] is True and manifest["source"]["kind"] == "PUBLIC_FIXTURE"
    for method, score in bundle["scores"].items():
        assert score["admitted"] == sum(BINDINGS[class_id].profile.document["assignment"].values())
        assert score["evaluable"] == score["admitted"] and score["estimate"] == "1"
        assert score["dimensions"]["utility"] == {"value": "NA", "n": 0}
        cost = bundle["cost"][method]
        assert cost["model_tokens"]["value"] == "NA" and cost["model_tokens"]["missing"]
        assert cost["wall_time"]["unit"] == "ms" and cost["wall_time"]["missing"] is None
    assert bundle["row"]["weights"] == {"state_machine": "0.5", "relational": "0.5"}
    assert set(bundle["inactive"].values()) == {"NA"}
    assert bundle["efficiency"] == {"status": "INACTIVE_ZERO_COEFFICIENTS", "eta": "1",
                                    "coefficients": ["0", "0", "0", "0"]}


def test_missing_observations_stay_zero_and_mismatched_profile_fails_closed():
    case = {"qid": "q", "track": "scored", "capsule": IC.generate("stale_authority", 0)}
    case["truth"] = IC.reference(case["capsule"])
    common = dict(mode="REPLAY", run_id="r", window={"opened_at": "a", "closed_at": "b"},
                  source_digest="sha256:" + "0" * 64)
    bundle = evaluate(IC, [case], {m: {} for m in IC.candidates},
                      profile_commitment=IC.profile.commitment, **common)
    score = bundle["scores"]["relational"]
    assert (score["admitted"], score["evaluable"], score["estimate"]) == (1, 0, "NA")
    assert bundle["row"]["state"] == "NO_VALID_PREFERENCE_ROW"
    assert bundle["cost"]["relational"]["bytes_in"]["missing"] == "NOT_OBSERVED"
    with pytest.raises(ProfileNotApplied):
        evaluate(IC, [case], {m: {} for m in IC.candidates},
                 profile_commitment="sha256:" + "f" * 64, **common)


def test_cost_dimensions_are_measured_or_missing_exactly_once():
    with pytest.raises(ValueError):
        cost_record({"wall_time": (1.0, "x")}, {})


@pytest.mark.requires_private_executors("tests/test_golden.py", "scripts/pilot_chain_dry_run.py")
def test_status_matrix_references_resolve():
    for item, implemented, enabled, tested, _deployed in STATUS_MATRIX:
        assert (implemented is None) == (tested == "NOT_TESTED") or not enabled, item
        if implemented:
            module, symbol = implemented.split(":")
            if module.endswith(".py"):
                assert f"def {symbol}(" in (ROOT / module).read_text(), item
            else:
                assert hasattr(importlib.import_module(module), symbol), item
        if tested != "NOT_TESTED":
            path, _, name = tested.partition("::")
            assert (ROOT / path).exists(), item
            assert not name or f"def {name}(" in (ROOT / path).read_text(), item


def test_implementation_status_doc_is_the_generated_matrix():
    from sn87_provenonce.bundle import status_markdown

    text = (ROOT / "docs" / "protocol" / "implementation-status.md").read_text()
    table = text.split("<!-- BEGIN STATUS_MATRIX -->\n")[1].split("<!-- END STATUS_MATRIX -->")[0]
    assert table == status_markdown()


def _floats(value):
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_floats(v) for v in value.values())
    return isinstance(value, list) and any(_floats(v) for v in value)


@pytest.mark.parametrize("class_id", sorted(BINDINGS))
def test_fixture_cases_reproduce_dimension_means_and_estimate(class_id):
    binding = BINDINGS[class_id]
    bundle = fixture_run(binding)
    assert not _floats(bundle)
    families = set(binding.profile.document["assignment"]) | set(
        binding.profile.document["diagnostics"])
    cases = bundle["cases"]
    assert len({c["qid"] for c in cases}) == len(cases)  # one record per case
    assert all(c["family"] in families and c["track"] in ("scored", "diagnostic")
               for c in cases)
    scored = [c for c in cases if c["track"] == "scored"]
    for method, score in bundle["scores"].items():
        records = [c["methods"][method] for c in scored]
        assert len(records) == score["admitted"]
        assert sum(r["valid"] for r in records) == score["evaluable"]
        for key in DIMENSIONS:
            values = [float(r["dimensions"][key]) for r in records
                      if r["valid"] and r["dimensions"][key] != "NA"]
            mean = {"value": wire(math.fsum(values) / len(values)), "n": len(values)} \
                if values else {"value": "NA", "n": 0}
            assert mean == score["dimensions"][key], (method, key)
        estimate = epoch_estimate([float(r["score"]) for r in records],
                                  [r["valid"] for r in records], binding.profile)
        assert wire(estimate["estimate"]) == score["estimate"]
        diagnostic = [c["methods"][method] for c in cases if c["track"] == "diagnostic"]
        assert sum(r["valid"] and r["state"] == "INSUFFICIENT_EVIDENCE_ABSTAIN"
                   for r in diagnostic) == bundle["diagnostics"][method]["correct_abstentions"]


@pytest.mark.parametrize("mode", ["REPLAY", "LIVE"])
def test_sealed_modes_never_carry_per_case_records(mode):
    case = {"qid": "q", "track": "scored", "family": "stale_authority",
            "capsule": IC.generate("stale_authority", 0)}
    case["truth"] = IC.reference(case["capsule"])
    observed = {m: {"q": {"response": c(case["capsule"]),
                          "integrity": Integrity(*[True] * 6),
                          "cost": cost_record({}, dict.fromkeys(COST_UNITS, "NOT_RECORDED"))}}
                for m, c in IC.candidates.items()}
    common = dict(run_id="r", window={"opened_at": "a", "closed_at": "b"},
                  source_digest="sha256:" + "0" * 64, profile_commitment=IC.profile.commitment)
    assert "cases" not in evaluate(IC, [case], observed, mode=mode, **common)
    with pytest.raises(ValueError, match="PER_CASE_RECORDS_ARE_FIXTURE_ONLY"):
        evaluate(IC, [case], observed, mode=mode, per_case=True, **common)
    # FIXTURE alone is not enough: per-case output is opt-in for established provenance.
    assert "cases" not in evaluate(IC, [case], observed, mode="FIXTURE", **common)
    fixture = evaluate(IC, [case], observed, mode="FIXTURE", per_case=True, **common)
    assert fixture["cases"][0]["methods"]["relational"]["valid"] is True


@pytest.mark.parametrize("class_id", sorted(BINDINGS))
def test_bundle_carries_the_committed_profile_bound_to_its_commitment(class_id):
    """0.3: a reader recomputes the commitment from the carried document, not from a copy."""
    from sn87_provenonce.canonical import object_commitment

    manifest = fixture_run(BINDINGS[class_id])["manifest"]
    document = manifest["profile_document"]
    assert document == BINDINGS[class_id].profile.document
    assert object_commitment(document, manifest["profile_commitment_domain"]) \
        == manifest["profile_commitment"]
    # The values the Observatory used to copy are in the bound document.
    for key in ("minimum_assignments", "maximum_raw_invalid_or_missing_rate", "tail_fraction",
                "theta", "gamma"):
        assert key in document


def test_emission_rejects_a_profile_document_mutated_after_load():
    """The frozen Profile holds a mutable dict: emitting it must recheck the commitment."""
    import copy
    import dataclasses

    base = BINDINGS["IC-APPROVAL-APPLICABILITY"]
    document = copy.deepcopy(base.profile.document)
    document["theta"] = "0.10"  # same cached commitment, different document
    profile = dataclasses.replace(base.profile, document=document)
    mutated = dataclasses.replace(base, profile=profile)
    with pytest.raises(ValueError, match="PROFILE_DOCUMENT_DIFFERS_FROM_COMMITMENT"):
        fixture_run(mutated)
    fixture_run(base)  # the unmutated binding still emits
