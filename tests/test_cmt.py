"""CMT v0.1 (candidate schema): golden vector, round trip, tamper, determinism, mutation."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sn87_provenonce import profile
from sn87_provenonce.canonical import canonical_bytes, evidence_commitment
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.cmt import (
    CMT_DOMAIN,
    CMTCompileError,
    CMTManifest,
    CompiledCMT,
    cmt_canonical_bytes,
    cmt_commitment,
    compile_cmt,
    compiled_bytes,
    compiler,
    hashing,
    parse_cmt,
    verify_cmt,
)
from sn87_provenonce.institutional_v02 import contracts as ic

ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "tests" / "cmt_vectors" / "ic_approval_applicability.cmt.json"
GOLDEN_MANIFEST_COMMITMENT = (
    "sha256:bf982fbdf941dc2bc40c1fefbaa1aac89e5e96d123ded191c6f3e8e9dfc8cdae")
IC_PROFILE_COMMITMENT = (
    "sha256:7049f165bc9b4fae32133f2d37aa9a48f5bf13f3b4fa47ea94643e5633d3c766")


def golden_bytes() -> bytes:
    return GOLDEN.read_bytes().rstrip(b"\n")


def leaf_paths(value, prefix=()):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaf_paths(v, (*prefix, k))
    elif isinstance(value, list) and value:
        for i, v in enumerate(value):
            yield from leaf_paths(v, (*prefix, i))
    else:
        yield prefix


def set_path(doc, path, value):
    for key in path[:-1]:
        doc = doc[key]
    doc[path[-1]] = value


def get_path(doc, path):
    for key in path:
        doc = doc[key]
    return doc


def test_golden_vector_is_pinned_and_reproduced():
    compiled = compile_cmt(task_family="IC-APPROVAL-APPLICABILITY")
    assert compiled_bytes(compiled) == golden_bytes()
    assert cmt_commitment(compiled.manifest) == GOLDEN_MANIFEST_COMMITMENT
    assert compiled.compatibility.manifest_commitment == GOLDEN_MANIFEST_COMMITMENT
    assert CMT_DOMAIN == "SN87:CMT:gra/0.1"


def test_profile_commitment_comes_from_the_committed_profile():
    manifest = compile_cmt().manifest
    assert manifest.evaluation.profile_commitment == IC_PROFILE_COMMITMENT == IC.profile.commitment
    assert manifest.evaluation.measurement_profile_id == "IC-FIRST-LIGHT-MIN-1"
    assert manifest.identity.class_id == "IC-APPROVAL-APPLICABILITY"


def test_candidate_status_and_unspecified_items_are_explicit():
    manifest = compile_cmt().manifest
    assert manifest.adoption_status == "CANDIDATE_SCHEMA_NOT_ADOPTED"
    assert manifest.operations.instance_expiry == "not_in_v0_1"
    assert "operations.instance_expiry" in manifest.not_in_v0_1
    codes = {d.code for d in compile_cmt().compatibility.diagnostics}
    assert {"CMT_SCHEMA_NOT_ADOPTED", "V0ALPHA1_MODELS_NOT_BOUND", "NOT_IN_V0_1_ITEMS"} <= codes
    statuses = {b.reference: b.status for b in compile_cmt().compatibility.bindings}
    assert statuses["protocol.v0alpha1.AssuranceRequest"] == "NOT_BOUND"


def test_round_trip_and_verify():
    compiled = compile_cmt()
    data = cmt_canonical_bytes(compiled.manifest)
    assert parse_cmt(data) == compiled.manifest
    assert cmt_canonical_bytes(parse_cmt(data)) == data
    assert verify_cmt(data, GOLDEN_MANIFEST_COMMITMENT) == compiled.manifest
    assert CompiledCMT.model_validate(json.loads(golden_bytes())) == compiled
    with pytest.raises(ValueError, match="mismatch"):
        verify_cmt(data, "sha256:" + "0" * 64)


def test_determinism():
    runs = {compiled_bytes(compile_cmt()) for _ in range(3)}
    assert len(runs) == 1
    code = ("from sn87_provenonce.cmt import compile_cmt, compiled_bytes;"
            "import sys; sys.stdout.buffer.write(compiled_bytes(compile_cmt()))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True).stdout
    assert out == golden_bytes()


def test_every_manifest_field_change_changes_the_hash():
    doc = compile_cmt().manifest.model_dump(mode="json")
    base = cmt_commitment(doc)
    paths = list(leaf_paths(doc))
    assert len(paths) > 60
    for path in paths:
        mutated = copy.deepcopy(doc)
        value = get_path(mutated, path)
        if type(value) is bool:
            replacement = not value
        elif type(value) is int:
            replacement = value + 1
        elif isinstance(value, list):  # empty list
            replacement = ["x"]
        else:
            replacement = value + "x"
        set_path(mutated, path, replacement)
        assert cmt_commitment(mutated) != base, path
    for key in ("extra_field",):  # an added field changes the hash too
        assert cmt_commitment({**doc, key: "x"}) != base


def test_tampered_bytes_are_rejected_on_read():
    data = golden_bytes()
    doc = json.loads(data)
    tampered = copy.deepcopy(doc)
    tampered["manifest"]["identity"]["task_version"] = "9.9.9"
    assert compiled_bytes(CompiledCMT.model_validate(tampered)) != data
    with pytest.raises(ValueError):
        parse_cmt(b'{"a": 1}')  # not canonical bytes
    extra = cmt_canonical_bytes(doc["manifest"]).replace(b"{", b'{"zz":1,', 1)
    with pytest.raises(ValueError):
        parse_cmt(extra)


def test_duplicate_keys_floats_and_non_nfc_rejected():
    manifest = cmt_canonical_bytes(compile_cmt().manifest)
    dup = manifest[:-1] + b',"schema_version":"sn87-cmt/0.1"}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_cmt(dup)
    doc = compile_cmt().manifest.model_dump(mode="json")
    with pytest.raises(ValueError, match="floating"):
        cmt_commitment({**doc, "x": 0.1})
    with pytest.raises(ValueError, match="NFC"):
        cmt_commitment({**doc, "x": "é"})


def test_unknown_field_or_value_rejected_by_schema():
    doc = compile_cmt().manifest.model_dump(mode="json")
    with pytest.raises(ValueError):
        CMTManifest.model_validate({**doc, "surprise": 1})
    bad = copy.deepcopy(doc)
    bad["operations"]["instance_expiry"] = "3600"  # must stay not_in_v0_1
    with pytest.raises(ValueError):
        CMTManifest.model_validate(bad)
    bad = copy.deepcopy(doc)
    bad["adoption_status"] = "ADOPTED"
    with pytest.raises(ValueError):
        CMTManifest.model_validate(bad)


def test_profile_commitment_mismatch_fails_closed(monkeypatch):
    with pytest.raises(CMTCompileError, match="differs from the expected"):
        compile_cmt(expected_profile_commitment="sha256:" + "1" * 64)
    assert compile_cmt(expected_profile_commitment=IC_PROFILE_COMMITMENT)
    pid = "IC-FIRST-LIGHT-MIN-1"
    cls, domain, _ = profile.REGISTRY[pid]
    monkeypatch.setitem(profile.REGISTRY, pid, (cls, domain, "sha256:" + "2" * 64))
    with pytest.raises(CMTCompileError, match="does not resolve"):
        compile_cmt()


def test_unsupported_family_fails_closed():
    for family in ("TYPE-C-RELEASE", "", "unknown"):
        with pytest.raises(CMTCompileError, match="unsupported"):
            compile_cmt(task_family=family)


def test_declared_limits_and_generator_match_the_code():
    manifest = compile_cmt().manifest
    limits = {x.name: x.value for x in manifest.operations.resource_limits}
    case = IC.generate("stale_authority", 1)
    assert limits["wire_max_bytes"] == IC.profile.document["wire_max_bytes"]
    assert case["policy"]["grammar"] == manifest.renewal.generator_version

    def with_events(n):
        c = copy.deepcopy(case)
        c["events"] = [{**c["events"][0], "event_id": f"e{i}"} for i in range(n)]
        c["evidence_commitment"] = evidence_commitment(c)
        return c

    def with_sources(n):
        c = copy.deepcopy(case)
        c["source_commitments"] = ["sha256:" + f"{i:064x}" for i in range(n)]
        c["evidence_commitment"] = evidence_commitment(c)
        return c

    ev, src = limits["capsule_events_max"], limits["capsule_source_commitments_max"]
    for cap, over in ((with_events(ev), with_events(ev + 1)),
                      (with_sources(src), with_sources(src + 1))):
        # the cap itself passes the bound checks (a later typed-event check may still fire)
        try:
            ic.validate_capsule(cap)
        except ValueError as exc:
            assert str(exc) not in ("event bounds", "source commitments")
        with pytest.raises(ValueError, match="event bounds|source commitments"):
            ic.validate_capsule(over)
    assert set(manifest.question.claim_ontology) == set(ic.DEFECT_SEVERITY)
    assert set(manifest.question.response_states) == ic.STATES
    assert canonical_bytes(manifest.model_dump(mode="json"))


# Mutation checks: with a guard removed, the matching guard test's condition is met by the
# mutant (so the guard test is sensitive to it).
def test_mutation_profile_expectation_guard(monkeypatch):
    wrong = "sha256:" + "3" * 64
    with pytest.raises(CMTCompileError):
        compile_cmt(expected_profile_commitment=wrong)
    monkeypatch.setattr(compiler, "_load_profile",
                        lambda expected: profile.load(compiler.PROFILE_ID))
    assert compile_cmt(expected_profile_commitment=wrong)  # mutant: mismatch goes unnoticed


def test_mutation_duplicate_key_guard(monkeypatch):
    dup = b'{"a":1,"a":2}'
    with pytest.raises(ValueError, match="duplicate"):
        hashing.parse_canonical(dup)
    monkeypatch.setattr(hashing, "parse_canonical", lambda data: json.loads(data))
    manifest = cmt_canonical_bytes(compile_cmt().manifest)
    dup_manifest = manifest[:-1] + b',"schema_version":"sn87-cmt/0.1"}'
    assert parse_cmt(dup_manifest)  # mutant: duplicate key silently accepted


def test_mutation_commitment_guard(monkeypatch):
    data = cmt_canonical_bytes(compile_cmt().manifest)
    with pytest.raises(ValueError):
        verify_cmt(data, "sha256:" + "4" * 64)
    monkeypatch.setattr(hashing, "cmt_commitment", lambda manifest: "sha256:" + "4" * 64)
    assert verify_cmt(data, "sha256:" + "4" * 64)  # mutant: any commitment verifies


def test_mutation_domain_separation(monkeypatch):
    doc = compile_cmt().manifest.model_dump(mode="json")
    from sn87_provenonce.canonical import object_commitment
    assert object_commitment(doc, "SN87:SCORING_PROFILE:gra/0.1") != cmt_commitment(doc)
