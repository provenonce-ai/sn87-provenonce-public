from __future__ import annotations

from pathlib import Path

import pytest

from sn87_provenonce.protocol.v0alpha1 import (
    canonical_json_bytes,
    canonical_sha256,
    parse_json_strict,
)

VECTORS = Path(__file__).resolve().parents[2] / "protocol" / "v0alpha1" / "test-vectors"


def test_canonical_json_sorts_keys_and_normalizes_unicode() -> None:
    decomposed = "Cafe\u0301"
    assert canonical_json_bytes({"z": 1, "a": decomposed}) == '{"a":"Café","z":1}'.encode()


def test_commitment_is_domain_separated() -> None:
    value = {"challenge_id": "q-1"}
    first = canonical_sha256(value, domain="SN87:REQUEST:v0alpha1")
    second = canonical_sha256(value, domain="SN87:RESPONSE:v0alpha1")
    assert first.startswith("sha256:")
    assert first != second


def test_parser_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_json_strict('{"challenge_id":"q-1","challenge_id":"q-2"}')


def test_canonical_json_rejects_nonfinite_numbers() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json_bytes({"score": float("nan")})


@pytest.mark.parametrize(
    ("name", "domain", "expected"),
    [
        (
            "request.metadata-clean.json",
            "SN87:REQUEST:v0alpha1",
            "sha256:90ff4dd4d5f2579ae4be2e6584cf67df77e735a31cf3cb906d46de972f228e6a",
        ),
        (
            "response.findings.json",
            "SN87:RESPONSE:v0alpha1",
            "sha256:72eaba64f8ec6ddc9f49b32294106791a13baed083e9068f34c703337de15b07",
        ),
        (
            "response.no-material-deviation.json",
            "SN87:RESPONSE:v0alpha1",
            "sha256:aa5a014c679eb7a3670034d95fd2b12925b01e8272728e7bcaa243a31d4b0b11",
        ),
        (
            "response.abstain.json",
            "SN87:RESPONSE:v0alpha1",
            "sha256:30e355a50b7bf18c502a8c971e4c22b29b72b8e3984e15d88467289475c09fb6",
        ),
    ],
)
def test_reference_vector_commitments_are_stable(
    name: str, domain: str, expected: str
) -> None:
    payload = parse_json_strict((VECTORS / name).read_bytes())
    assert canonical_sha256(payload, domain=domain) == expected
