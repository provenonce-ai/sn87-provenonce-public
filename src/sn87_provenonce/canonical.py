"""The one SN87 canonicalizer: strict ``gra/0.1`` JSON and whitepaper Eq.18 commitments.

Rejects floats, non-NFC text, duplicate keys, out-of-range integers and noncanonical bytes.
It never normalizes. Every weight-producing path uses it and records CANONICALIZER_ID.
``sn87_provenonce/protocol/v0alpha1/canonical.py`` (NFC-normalizing, float-accepting) is a separate,
historical profile for ``runtime/`` and ``simulation/`` readers only; no semantic mapping
from it exists, so v0alpha1 objects are rejected here rather than translated.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import unicodedata
from datetime import datetime
from typing import Any

CANONICALIZER_ID = "gra/0.1"
MAX_BYTES = 262144


def _check(value: Any) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not -(2**53 - 1) <= value <= 2**53 - 1:
            raise ValueError("integer outside exact interoperable range")
        return
    if type(value) is str:
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError("non-NFC text")
        value.encode("utf-8", errors="strict")
        return
    if type(value) is list:
        for item in value:
            _check(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("object key must be a string")
            _check(key)
            _check(item)
        return
    raise ValueError("canonical profile accepts no floating-point JSON numbers")


def canonical_bytes(value: Any, *, max_bytes: int = MAX_BYTES) -> bytes:
    if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("invalid canonical storage bound")
    _check(value)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if len(data) > max_bytes:
        raise ValueError("canonical object exceeds byte limit")
    return data


def parse_canonical(data: bytes, *, max_bytes: int = MAX_BYTES) -> Any:
    if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("invalid canonical storage bound")
    if len(data) > max_bytes:
        raise ValueError("JSON exceeds byte limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, val in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = val
        return result

    value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=pairs)
    if canonical_bytes(value, max_bytes=max_bytes) != data:
        raise ValueError("noncanonical JSON bytes")
    return value


def lp(value: Any) -> bytes:
    data = canonical_bytes(value)
    return struct.pack(">I", len(data)) + data


# Capsule schemas whose commitment domains are recorded evidence (First Light used 0.2).
SCHEMAS = ("gra/0.1", "institution/0.2")


def object_commitment(value: Any, domain: str) -> str:
    if re.fullmatch(r"SN87:[A-Z0-9_/-]+:(gra/0\.1|institution/0\.2)", domain) is None:
        raise ValueError("invalid object commitment domain")
    return "sha256:" + hashlib.sha256(domain.encode("ascii") + b"\x00" + lp(value)).hexdigest()


def check_timestamp(value: str) -> None:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None:
        raise ValueError("timestamp must be UTC whole-second RFC3339")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def evidence_commitment(capsule: dict[str, Any]) -> str:
    """Eq.18: each LP payload is the canonical JSON bytes of the named field.

    The completeness boundary and qid are bound through the policy's task context.
    """
    schema = capsule["schema_version"]
    if schema not in SCHEMAS:
        raise ValueError("unknown capsule schema")
    check_timestamp(capsule["timestamp"])
    fields = ("schema_version", "pipeline_id", "events", "source_commitments", "policy",
              "nonce", "timestamp")
    message = f"SN87:EVIDENCE-COMMITMENT:{schema}".encode() + b"".join(
        lp(capsule[k]) for k in fields
    )
    return "sha256:" + hashlib.sha256(message).hexdigest()
