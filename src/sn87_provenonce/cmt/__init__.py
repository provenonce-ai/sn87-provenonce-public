"""Canonical Miner Task (CMT) v0.1: a CANDIDATE schema, not an adopted wire object.

See ``docs/protocol/cmt-v0.1.md``. Public API: ``compile_cmt``, ``cmt_commitment``,
``cmt_canonical_bytes``, ``parse_cmt``, ``verify_cmt``.
"""

from sn87_provenonce.cmt.compiler import CMTCompileError, compile_cmt, compiled_bytes
from sn87_provenonce.cmt.hashing import (
    CMT_DOMAIN,
    cmt_canonical_bytes,
    cmt_commitment,
    parse_cmt,
    verify_cmt,
)
from sn87_provenonce.cmt.models import CMTManifest, CompatibilityReport, CompiledCMT

__all__ = [
    "CMT_DOMAIN", "CMTCompileError", "CMTManifest", "CompatibilityReport", "CompiledCMT",
    "cmt_canonical_bytes", "cmt_commitment", "compile_cmt", "compiled_bytes", "parse_cmt",
    "verify_cmt",
]
