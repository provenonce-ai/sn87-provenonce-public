"""One profile family: the committed document drives the result and fails closed."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sn87_provenonce import profile
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.classes import TYPE_C_RELEASE as TC
from sn87_provenonce.profile import Profile, ProfileNotApplied, require_applied
from sn87_provenonce.scoring import epoch_estimate, preference_row

FIRST_LIGHT = "sha256:7049f165bc9b4fae32133f2d37aa9a48f5bf13f3b4fa47ea94643e5633d3c766"


def document(profile_id):
    path = Path(profile.__file__).with_name("profiles") / f"{profile_id}.json"
    return json.loads(path.read_text())


def derive(doc, class_id="IC-APPROVAL-APPLICABILITY",
           domain="SN87:SCORING_PROFILE:institution/0.2"):
    return Profile.from_document(doc, class_id=class_id, domain=domain)


def test_committed_profiles_keep_their_recorded_commitments():
    assert IC.profile.commitment == FIRST_LIGHT
    assert IC.profile.minimum == 12 and TC.profile.minimum == 40
    assert (IC.profile.theta, IC.profile.gamma) == (0.6, 2.0)


def test_profile_drives_result():
    """Changing the committed document changes the row: the profile is applied."""
    estimates = {"state_machine": 1.0, "relational": 0.8}
    base = preference_row(estimates, IC.profile)["weights"]
    doc = document("IC-FIRST-LIGHT-MIN-1") | {"theta": "0.70"}
    moved = derive(doc)
    assert moved.commitment != FIRST_LIGHT
    assert preference_row(estimates, moved)["weights"] != base
    doc = document("IC-FIRST-LIGHT-MIN-1") | {"minimum_assignments": 13}
    assert epoch_estimate([1.0] * 12, [True] * 12, derive(doc))["reason"] == "SAMPLE_FLOOR"


@pytest.mark.parametrize("change", [
    {"theta": 0.6}, {"theta": "6e-1"}, {"gamma": None}, {"beta": "2"}, {"freshness": "0.5"},
    {"cost_coefficients": ["0", "0", "0", "0.1"]}, {"utility": "LINEAR"},
    {"minimum_assignments": "12"}, {"weights": {"detection": "1"}},
])
def test_missing_unparsed_or_unsupported_values_fail_closed(change):
    doc = document("IC-FIRST-LIGHT-MIN-1") | change
    with pytest.raises((ProfileNotApplied, ValueError)):
        derive(doc)


def test_edited_committed_file_or_mismatched_run_fails_closed(monkeypatch):
    registry = dict(profile.REGISTRY)
    registry["IC-FIRST-LIGHT-MIN-1"] = (*registry["IC-FIRST-LIGHT-MIN-1"][:2], "sha256:" + "0" * 64)
    monkeypatch.setattr(profile, "REGISTRY", registry)
    with pytest.raises(ProfileNotApplied, match="pinned commitment"):
        profile.load("IC-FIRST-LIGHT-MIN-1")
    with pytest.raises(ProfileNotApplied):
        require_applied(TC.profile, FIRST_LIGHT)
    with pytest.raises(ProfileNotApplied):
        require_applied(replace(IC.profile, commitment="sha256:" + "1" * 64), FIRST_LIGHT)
