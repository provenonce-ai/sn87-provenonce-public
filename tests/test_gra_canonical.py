"""The one canonicalizer (gra/0.1) and its boundary with the historical v0alpha1 profile."""

import ast
from pathlib import Path

import pytest

from sn87_provenonce.canonical import (
    CANONICALIZER_ID,
    canonical_bytes,
    check_timestamp,
    lp,
    object_commitment,
    parse_canonical,
)

SRC = Path(__file__).parents[1] / "src" / "sn87_provenonce"
WEIGHT_PATH = ["canonical.py", "profile.py", "scoring.py", "bundle.py", "classes.py",
               "pilot/contracts.py", "institutional_v02/contracts.py",
               "institutional_v02/references.py", "institutional_v02/fixtures.py"]
PRIVATE_EXECUTORS = {"institutional_v02/references.py"}


@pytest.mark.parametrize(
    "data",
    [b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":1e0}', b'{"a":-0}', b'{"a":NaN}', b'{ "a":1}',
     b'{"a":"e\\u0301"}', b"\xef\xbb\xbf{}", b'{"a":9007199254740992}', b'{"a":"\\ud800"}'],
)
def test_canonical_attacks_rejected(data):
    with pytest.raises((ValueError, UnicodeError)):
        parse_canonical(data)


@pytest.mark.parametrize("value", [{"a": 0.5}, {"a": "é"}, [1.0]])
def test_floats_and_non_nfc_rejected_not_normalized(value):
    with pytest.raises(ValueError):
        canonical_bytes(value)


def test_lp_known_vector_and_object_order():
    assert CANONICALIZER_ID == "gra/0.1"
    assert lp("é").hex() == "0000000422c3a922"
    assert canonical_bytes({"z": 1, "a": True}) == b'{"a":true,"z":1}'
    assert parse_canonical(b'{"a":true,"z":1}') == {"a": True, "z": 1}


@pytest.mark.parametrize("timestamp", ["2026-09-27T22:25:00+00:00", "2026-09-27T22:25:00.0Z",
                                       "2026-02-30T22:25:00Z", "2026-09-27T22:25:60Z"])
def test_timestamp_noncanonical(timestamp):
    with pytest.raises(ValueError):
        check_timestamp(timestamp)


def test_commitment_domains_are_the_recorded_schemas_only():
    for domain in ("SN87:SCORING_PROFILE:gra/0.1", "SN87:SCORING_PROFILE:institution/0.2"):
        assert object_commitment({}, domain).startswith("sha256:")
    with pytest.raises(ValueError):
        object_commitment({}, "SN87:SCORING_PROFILE:v0alpha1")


def test_weight_path_never_imports_the_v0alpha1_canonicalizer():
    """Import-graph proof: v0alpha1 objects cannot reach a weight row by translation."""
    for name in WEIGHT_PATH:
        if name in PRIVATE_EXECUTORS and not (SRC / name).exists():
            continue  # exported tree: the private executor is not shipped
        tree = ast.parse((SRC / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "v0alpha1.canonical" not in node.module, name
                if node.module.endswith("v0alpha1"):
                    assert {a.name for a in node.names} <= {"ResponseState"}, name
