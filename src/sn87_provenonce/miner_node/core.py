"""The one miner method interface, shared by the signed endpoint and the loopback server.

A method is ``Callable[[dict], dict]``: one capsule in, one differential out. Both wires call
the same method object and serialise its answer with ``canonical_bytes``, so a capsule that is
answered on loopback is answered with the same bytes behind the signed endpoint. Nothing here
imports the chain SDK, touches a chain, or reads a key.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sn87_provenonce import miners
from sn87_provenonce.baselines import BASELINES
from sn87_provenonce.canonical import canonical_bytes, parse_canonical
from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY
from sn87_provenonce.cmt import (
    CompiledCMT,
    cmt_canonical_bytes,
    cmt_commitment,
    compile_cmt,
    verify_cmt,
)
from sn87_provenonce.institutional_v02.contracts import validate_capsule

Method = Callable[[dict[str, Any]], dict[str, Any]]

CANDIDATE = "approval_witness"  # the same ids the staging harness uses
BASELINE_MINER = "baseline_miner"
ROLES = {"candidate": CANDIDATE, "baseline": BASELINE_MINER}
METHOD_PATH = re.compile(r"[A-Za-z_][\w.]*:[A-Za-z_]\w*")


class StagingError(RuntimeError):
    """CMT verification failed closed."""


class GrammarMismatch(ValueError):
    """The capsule grammar is not the one the CMT names."""


class MethodError(ValueError):
    """A ``module:function`` method path could not be loaded."""


def verify_compiled(compiled: CompiledCMT, binding=IC_APPROVAL_APPLICABILITY) -> str:
    """Same checks as the validator side's CMT verification (kept local so this module imports
    nothing from bittensor): commitment reproduces, profile and class match the binding."""
    manifest = compiled.manifest
    commitment = compiled.compatibility.manifest_commitment
    try:
        verify_cmt(cmt_canonical_bytes(manifest), commitment)
    except ValueError as error:
        raise StagingError(f"CMT_HASH_VERIFICATION_FAILED: {error}") from error
    if cmt_commitment(manifest) != commitment:
        raise StagingError("CMT_HASH_VERIFICATION_FAILED: commitment mismatch")
    if manifest.evaluation.profile_commitment != binding.profile.commitment:
        raise StagingError("CMT_PROFILE_COMMITMENT_MISMATCH")
    if manifest.identity.class_id != binding.class_id:
        raise StagingError("CMT_CLASS_MISMATCH")
    return commitment


def role_method(role: str) -> Method:
    if role == "candidate":
        return miners.for_class(IC_APPROVAL_APPLICABILITY.class_id)[CANDIDATE]
    if role == "baseline":
        return BASELINES[IC_APPROVAL_APPLICABILITY.class_id]
    raise ValueError(f"unknown role: {role}")


def check_capsule(capsule: Any, grammar: str | None) -> None:
    """Validate a capsule against the ``institution/0.2`` contract (recomputing
    ``evidence_commitment``) and, when ``grammar`` is given, against the CMT's generator
    grammar. Raises ``ValueError`` for a malformed capsule and ``GrammarMismatch`` for a
    grammar the CMT does not name."""
    validate_capsule(capsule)
    if grammar is not None and capsule["policy"].get("grammar") != grammar:
        raise GrammarMismatch(f"expected {grammar}")


def load_method(path: str) -> Method:
    """Import ``package.module:function``. The operator names their own code; nothing is
    fetched. The function must take one capsule dict and return one differential dict."""
    if METHOD_PATH.fullmatch(path) is None:
        raise MethodError("METHOD_PATH_INVALID: expected package.module:function")
    module_name, _, attribute = path.partition(":")
    try:
        fn = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise MethodError(f"METHOD_NOT_FOUND: {type(error).__name__}") from None
    if not callable(fn):
        raise MethodError("METHOD_NOT_CALLABLE")
    return fn


@dataclass
class MinerCore:
    """One miner method plus the checks both wires apply before calling it.

    ``grammar`` and ``cmt_commitment`` are set for the reference roles (the CMT is compiled and
    verified at construction, fail closed) and ``None`` for a custom ``module:function``
    method, which validates its own input.
    """

    label: str
    method_id: str
    method: Method
    grammar: str | None = None
    cmt_commitment: str | None = None
    compiled: CompiledCMT | None = None

    @classmethod
    def from_role(cls, role: str, compiled: CompiledCMT | None = None) -> MinerCore:
        method = role_method(role)
        compiled = compiled or compile_cmt()
        return cls(
            label=f"role={role}", method_id=ROLES[role], method=method,
            grammar=compiled.manifest.renewal.generator_version,
            cmt_commitment=verify_compiled(compiled), compiled=compiled,
        )

    @classmethod
    def from_path(cls, path: str) -> MinerCore:
        return cls(label=f"method={path}", method_id=path, method=load_method(path))

    def handle(self, capsule: dict[str, Any]) -> dict[str, Any]:
        """The signed endpoint's handler: validate (reference roles), then call the method."""
        if self.grammar is not None:
            check_capsule(capsule, self.grammar)
        return self.method(capsule)

    def answer(self, body: bytes) -> bytes:
        """The byte boundary: canonical capsule bytes in, canonical response bytes out."""
        return canonical_bytes(self.handle(parse_canonical(body)))
