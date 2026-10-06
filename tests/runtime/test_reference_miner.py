from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sn87_provenonce.protocol.v0alpha1 import AssuranceRequest, AssuranceResponse, ResponseState
from sn87_provenonce.runtime import MinerContractViolation, ReferenceMiner

VECTORS = Path(__file__).resolve().parents[2] / "protocol" / "v0alpha1" / "test-vectors"


def load_model(model: type, name: str):
    return model.model_validate(json.loads((VECTORS / name).read_text(encoding="utf-8")))


class FixedAnalyzer:
    def __init__(self, response: AssuranceResponse) -> None:
        self.response = response

    async def analyze(self, request: AssuranceRequest) -> AssuranceResponse:
        return self.response


@pytest.mark.parametrize(
    "vector",
    [
        "response.findings.json",
        "response.no-material-deviation.json",
        "response.abstain.json",
    ],
)
def test_reference_miner_emits_each_canonical_response_state(vector: str) -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, vector)

    result = asyncio.run(ReferenceMiner(FixedAnalyzer(response)).answer(request))

    assert result == response


def test_reference_miner_rejects_protocol_substitution() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = load_model(AssuranceResponse, "response.findings.json").model_copy(
        update={"protocol_version": "sn87/incompatible"}
    )

    with pytest.raises(MinerContractViolation) as captured:
        asyncio.run(ReferenceMiner(FixedAnalyzer(response)).answer(request))

    assert captured.value.code == "MINER_PROTOCOL_VERSION_MISMATCH"


def test_reference_miner_rejects_challenge_substitution() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    original = load_model(AssuranceResponse, "response.findings.json")
    substituted_findings = tuple(
        finding.model_copy(update={"challenge_id": "q-different"})
        for finding in original.findings or ()
    )
    response = original.model_copy(
        update={"challenge_id": "q-different", "findings": substituted_findings}
    )

    with pytest.raises(MinerContractViolation) as captured:
        asyncio.run(ReferenceMiner(FixedAnalyzer(response)).answer(request))

    assert captured.value.code == "MINER_CHALLENGE_ID_MISMATCH"


def test_analyzer_failure_is_not_recast_as_abstention() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")

    class BrokenAnalyzer:
        async def analyze(self, request: AssuranceRequest) -> AssuranceResponse:
            raise RuntimeError("analysis unavailable")

    with pytest.raises(RuntimeError, match="analysis unavailable"):
        asyncio.run(ReferenceMiner(BrokenAnalyzer()).answer(request))


def test_reference_miner_rejects_unvalidated_response_shape() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")
    response = AssuranceResponse.model_construct(
        protocol_version=request.protocol_version,
        challenge_id=request.challenge_id,
        response_state=ResponseState.FINDINGS,
        rationale="Invalid constructed response.",
        findings=None,
    )

    with pytest.raises(MinerContractViolation) as captured:
        asyncio.run(ReferenceMiner(FixedAnalyzer(response)).answer(request))

    assert captured.value.code == "MINER_RESPONSE_SCHEMA_INVALID"


def test_reference_miner_rejects_foreign_return_type() -> None:
    request = load_model(AssuranceRequest, "request.metadata-clean.json")

    class ForeignAnalyzer:
        async def analyze(self, request):
            return {"response_state": "FINDINGS"}

    with pytest.raises(MinerContractViolation) as captured:
        asyncio.run(ReferenceMiner(ForeignAnalyzer()).answer(request))

    assert captured.value.code == "MINER_RESPONSE_TYPE_INVALID"
