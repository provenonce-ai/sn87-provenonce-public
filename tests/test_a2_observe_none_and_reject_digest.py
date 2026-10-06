"""A reference returning None fails loudly; reject digest is canonical."""

import dataclasses
import hashlib
import json

import pytest

from sn87_provenonce.bundle import observe
from sn87_provenonce.canonical import canonical_bytes
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY as IC
from sn87_provenonce.sources import mapping


def _cases():
    capsule = IC.generate(next(iter(IC.profile.document["assignment"])), 0)
    return [{"qid": capsule["qid"], "track": "scored", "capsule": capsule}], [1]


def _binding(method_returns, role):
    name = next(iter(IC.candidates))
    candidates = dict(IC.candidates)
    candidates[name] = lambda capsule: method_returns
    return dataclasses.replace(IC, candidates=candidates, role=role, roles={}), name


def test_reference_method_returning_none_raises():
    binding, _ = _binding(None, "reference")
    cases, oracle = _cases()
    with pytest.raises(ValueError, match="REFERENCE_METHOD_RETURNED_NONE"):
        observe(binding, cases, oracle)


def test_candidate_method_returning_none_is_still_scored_not_raised():
    binding, name = _binding(None, "candidate")
    cases, oracle = _cases()
    record = observe(binding, cases, oracle)[name][cases[0]["qid"]]
    assert record["response"] is None and record["integrity"].schema is False


def test_case_digest_bytes_are_unchanged_and_canonical():
    case = {"qid": "q-é", "log": [{"a": 1, "b": ["x", None, True]}], "z": {"k": "v"}}
    legacy = json.dumps(case, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = "sha256:" + hashlib.sha256(
        (mapping._DOMAIN + ":reject\x00" + legacy).encode()).hexdigest()
    assert mapping._case_digest(case) == expected
    assert expected == mapping.object_commitment(case, mapping._DOMAIN + ":reject")
    assert legacy.encode() == canonical_bytes(case)


def test_case_digest_goes_through_the_canonical_helpers(monkeypatch):
    calls = []
    real = mapping.object_commitment
    monkeypatch.setattr(mapping, "object_commitment",
                        lambda value, domain: calls.append(domain) or real(value, domain))
    mapping._case_digest({"x": 1})
    assert calls == [mapping._DOMAIN + ":reject"]


def test_unrepresentable_case_still_rejects_instead_of_crashing():
    # A float is outside the canonical profile; the digest degrades to a fixed marker, so
    # map_source keeps reporting a reject rather than raising out of the reject path.
    digest = mapping._case_digest({"x": 1.5})
    assert digest == mapping.object_commitment({"unrepresentable": True},
                                               mapping._DOMAIN + ":reject")
