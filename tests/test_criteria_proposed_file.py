"""The committed shadow-to-weighted criteria file is a valid, self-consistent proposal."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


ap = _load("admission_plan")
CRITERIA = json.loads((ROOT / "shadow" / "criteria-proposed.json").read_text(encoding="utf-8"))


def test_the_rules_validate():
    assert ap.validate_rules(CRITERIA["rules"]) is None


def test_the_digest_matches_the_content():
    assert ap.criteria_digest_ok(CRITERIA)


def test_the_file_is_marked_as_a_proposal():
    assert CRITERIA["status"] == "PROPOSED_NEEDS_AUTHORITY_APPROVAL"
    assert CRITERIA["applies_to"] == "shadow to weighted"
    assert any("proposals" in line for line in CRITERIA["not_claimed"])


def test_the_proposed_values_and_the_signature_requirement():
    rules = CRITERIA["rules"]
    assert rules["consecutive_windows"] == 7
    assert rules["min_valid_responses_per_window"] == 24
    assert rules["max_integrity_failures_per_window"] == 0
    assert rules["require_endpoint_announcement_valid"] is True
    assert rules["require_signature_verified"] is True
    assert rules["results_must_be_shadow_with_weight_zero"] is True
