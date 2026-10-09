"""Truth records echo rule_reliability / deterministic from the bound committed profile (#71).

These fail if an emitter hard-codes a value that differs from the committed profile, or if it
ignores the profile and so cannot follow a profile whose values change.
"""

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from sn87_provenonce import profile
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.pilot.contracts import capsule_from_fixture
from sn87_provenonce.profile import ProfileNotApplied
from sn87_provenonce.simulation.type_c import FIXTURES

SRC = Path(profile.__file__).parent

# (profile id, module that emits the truth record, truth builder over its own capsule). The
# emitters are the private reference executors: they are imported by the tests that need them,
# which the executor marker skips where they are absent.
CASES = {
    "GRA-W03-3": ("sn87_provenonce.pilot.reference",
                  lambda: capsule_from_fixture(FIXTURES[1])),
    "IC-FIRST-LIGHT-MIN-1": ("sn87_provenonce.institutional_v02.references",
                             lambda: build_case("stale_authority")),
}


def _committed(profile_id):
    return json.loads((SRC / "profiles" / f"{profile_id}.json").read_text("utf-8"))


@pytest.mark.requires_private_executors
@pytest.mark.parametrize("profile_id", sorted(CASES))
def test_truth_record_matches_committed_profile(profile_id):
    module, make = CASES[profile_id]
    module = importlib.import_module(module)
    document = _committed(profile_id)
    truth = module.agreed_truth(make())
    assert truth["rule_reliability"] == document["rule_reliability"]
    assert truth["deterministic"] == document["deterministic"]


@pytest.mark.requires_private_executors
@pytest.mark.parametrize("profile_id", sorted(CASES))
def test_truth_record_follows_the_bound_profile(profile_id, monkeypatch):
    """A profile with different values must flow into the truth record (no literal copy)."""
    module, make = CASES[profile_id]
    module = importlib.import_module(module)
    real = profile.load(profile_id)
    document = dict(real.document, rule_reliability="0.5", deterministic=False)
    altered = replace(real, document=document)
    monkeypatch.setattr(module, "load_profile", lambda pid: altered if pid == profile_id else real)
    truth = module.agreed_truth(make())
    assert truth["rule_reliability"] == "0.5"
    assert truth["deterministic"] is False


@pytest.mark.parametrize("bad", [
    {"rule_reliability": 0.95},
    {"rule_reliability": "x"},
    {"deterministic": "true"},
    {"deterministic": None},
])
def test_truth_fields_reject_malformed_profile_values(bad):
    real = profile.load("GRA-W03-3")
    with pytest.raises(ProfileNotApplied):
        replace(real, document=dict(real.document, **bad)).truth_fields()
