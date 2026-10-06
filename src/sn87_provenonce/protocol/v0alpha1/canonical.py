"""Draft canonical JSON utilities for protocol objects.

This module intentionally does not implement the whitepaper's Evidence commitment
formula: the width and exact encoding of LP(x) are not yet specified. The object
commitment here has its own v0alpha1 domain and cannot be confused with that future
normative commitment.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are not canonical JSON")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("duplicate key after Unicode normalization")
            normalized[normalized_key] = _normalize(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [_normalize(item) for item in value]
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes under the v0alpha1 draft profile."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any, *, domain: str) -> str:
    """Commit to canonical object bytes with an explicit caller-supplied domain."""

    clean_domain = unicodedata.normalize("NFC", domain).strip()
    if not clean_domain or "\x00" in clean_domain:
        raise ValueError("domain must be nonempty and cannot contain NUL")
    payload = clean_domain.encode("utf-8") + b"\x00" + canonical_json_bytes(value)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def parse_json_strict(value: str | bytes) -> Any:
    """Parse JSON while rejecting duplicate keys before normalization."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    parsed = json.loads(value, object_pairs_hook=reject_duplicates)
    return _normalize(parsed)
