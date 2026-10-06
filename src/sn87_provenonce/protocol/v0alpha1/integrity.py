"""Non-compensable integrity gate for validated protocol objects."""

from __future__ import annotations

from datetime import datetime

from sn87_provenonce.protocol.v0alpha1.models import (
    AssuranceRequest,
    AssuranceResponse,
    IntegrityGateResult,
    ResponseState,
)


def evaluate_integrity_gate(
    request: AssuranceRequest,
    response: AssuranceResponse,
    *,
    received_at: datetime,
    signature_valid: bool,
    nonce_valid: bool,
    policy_valid: bool,
    evidence_valid: bool,
) -> IntegrityGateResult:
    """Evaluate explicit gate factors without replacing transport or oracle checks.

    The caller supplies signature, nonce, policy, and Evidence verification facts.
    This function does not claim that structural validation proves source truth.
    """

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must include a timezone")

    failures: list[str] = []
    schema_valid = True
    if response.protocol_version != request.protocol_version:
        schema_valid = False
        failures.append("PROTOCOL_VERSION_MISMATCH")
    if response.challenge_id != request.challenge_id:
        schema_valid = False
        failures.append("CHALLENGE_ID_MISMATCH")

    deadline_valid = received_at <= request.expires_at
    if not deadline_valid:
        failures.append("DEADLINE_EXPIRED")
    if not signature_valid:
        failures.append("SIGNATURE_INVALID")
    if not nonce_valid:
        failures.append("NONCE_INVALID")
    if not policy_valid:
        failures.append("POLICY_INVALID")

    requires_evidence = response.response_state is ResponseState.FINDINGS
    effective_evidence_valid = evidence_valid if requires_evidence else True
    if not effective_evidence_valid:
        failures.append("EVIDENCE_INVALID")

    return IntegrityGateResult(
        schema_valid=schema_valid,
        policy_valid=policy_valid,
        signature_valid=signature_valid,
        nonce_valid=nonce_valid,
        evidence_valid=effective_evidence_valid,
        deadline_valid=deadline_valid,
        failures=tuple(failures),
    )
