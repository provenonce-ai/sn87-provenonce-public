"""CMT canonical bytes and commitment, over the one SN87 canonicalizer (``gra/0.1``).

No second canonicalizer: bytes come from ``canonical.canonical_bytes`` (floats, non-NFC text,
duplicate keys and noncanonical input are rejected there, and ``parse_canonical`` rejects
duplicate keys on read). The commitment is ``canonical.object_commitment`` under a CMT domain.
That helper only accepts domains of the form ``SN87:<NAME>:<schema>``, so the CMT domain is
``SN87:CMT:gra/0.1`` (not a free-form ``sn87/cmt/0.1`` string). CMT objects hold integers and
decimal strings only; no float, hence no ``.17g`` formatting, ever occurs in a CMT.
"""

from __future__ import annotations

from typing import Any

from sn87_provenonce.canonical import canonical_bytes, object_commitment, parse_canonical
from sn87_provenonce.cmt.models import CMTManifest

CMT_DOMAIN = "SN87:CMT:gra/0.1"


def _doc(manifest: CMTManifest | dict[str, Any]) -> dict[str, Any]:
    if isinstance(manifest, CMTManifest):
        return manifest.model_dump(mode="json")
    return manifest


def cmt_canonical_bytes(manifest: CMTManifest | dict[str, Any]) -> bytes:
    return canonical_bytes(_doc(manifest))


def cmt_commitment(manifest: CMTManifest | dict[str, Any]) -> str:
    return object_commitment(_doc(manifest), CMT_DOMAIN)


def parse_cmt(data: bytes) -> CMTManifest:
    """Strict read: canonical bytes only, duplicate keys rejected, then schema-validated."""
    return CMTManifest.model_validate(parse_canonical(data))


def verify_cmt(data: bytes, commitment: str) -> CMTManifest:
    manifest = parse_cmt(data)
    if cmt_commitment(manifest) != commitment:
        raise ValueError("CMT commitment mismatch")
    return manifest
