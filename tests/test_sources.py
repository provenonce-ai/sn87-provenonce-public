"""Fictional permitted source -> capsules + disclosure: validity, withholding, config identity."""

import copy
import json

import pytest

from sn87_provenonce.canonical import canonical_bytes
from sn87_provenonce.institutional_v02 import contracts as ic
from sn87_provenonce.sources import mapping

DOC, PERMISSION = mapping.load_fixture()


def export(index: int) -> dict:
    return {"schema_id": DOC["schema_id"], **DOC["exports"][index]}


def test_fixture_is_labelled_fictional():
    assert DOC["label"].startswith("FICTIONAL") and PERMISSION["fictional"] is True
    assert "example.invalid" in json.dumps(DOC)  # no real host anywhere


@pytest.mark.parametrize("index,mapped,rejects", [(0, 14, 2), (1, 15, 2)])
def test_capsules_are_contract_valid_and_disclosure_accounts_for_every_case(index, mapped, rejects):
    capsules, disclosure = mapping.map_source(export(index), PERMISSION)
    assert len(capsules) == mapped and len(disclosure["rejects"]) == rejects
    for capsule in capsules:
        ic.validate_capsule(capsule)
    assert disclosure["offered"]["cases"] == mapped + rejects
    assert {r["reason"].split(":")[0] for r in disclosure["rejects"]} <= {
        "MISSING_FIELD", "CONTRACT_INVALID"} and all(r["reason"] for r in disclosure["rejects"])
    assert set(disclosure["mapped_fields"]) <= set(PERMISSION["allowed_fields"])
    assert disclosure["config"]["config_id"].startswith("sha256:")
    canonical_bytes(disclosure)


def test_withheld_fields_never_reach_a_capsule():
    capsules, disclosure = mapping.map_source(export(0), PERMISSION)
    assert set(disclosure["withheld_fields"]) == {
        "note", "reviewer_comment", "reviewer_name", "ticket_url"}
    assert not set(disclosure["withheld_fields"]) & set(disclosure["mapped_fields"])
    blob = json.dumps(capsules)
    for secret in ("Pat Fictional", "Fictional free-text", "example.invalid",
                   "Fictional reviewer note"):
        assert secret not in blob
    # Opaque free text is committed, not copied.
    assert "Launch notice draft" not in blob and "Condition v1" not in blob


def test_permission_narrowing_is_enforced_before_mapping():
    narrow = copy.deepcopy(PERMISSION)
    narrow["allowed_fields"].remove("artifact_text")
    capsules, disclosure = mapping.map_source(export(0), narrow)
    assert capsules == [] and len(disclosure["rejects"]) == 16
    assert {r["reason"] for r in disclosure["rejects"]} == {
        "MISSING_FIELD:artifact_text", "MISSING_FIELD:approved"}
    assert "artifact_text" in disclosure["withheld_fields"]


def test_config_id_commits_to_each_of_its_four_parts_and_nothing_else():
    source = export(0)
    base = mapping.make_config(source, PERMISSION)
    assert base == mapping.make_config(export(1), PERMISSION)  # same config, any window
    renewed = PERMISSION | {"expires_at": "2027-06-30T00:00:00Z"}
    assert mapping.make_config(source, renewed)["config_id"] == base["config_id"]
    changed = {
        "source schema": mapping.make_config(source | {"schema_id": "other/1"}, PERMISSION),
        "permission": mapping.make_config(source, PERMISSION | {"scope": "narrower"}),
        "meaning": mapping.make_config(source, PERMISSION | {"meaning_version": "m/2"}),
        "mapping": mapping.make_config(source, PERMISSION, mapping_version="v2"),
        "profile": mapping.make_config(source, PERMISSION, profile_commitment="sha256:" + "1" * 64),
    }
    ids = {v["config_id"] for v in changed.values()} | {base["config_id"]}
    assert len(ids) == 6
