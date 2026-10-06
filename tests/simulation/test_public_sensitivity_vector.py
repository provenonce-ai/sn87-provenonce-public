from __future__ import annotations

import json
from pathlib import Path

from sn87_provenonce.cli import main
from sn87_provenonce.protocol.v0alpha1 import (
    canonical_json_bytes,
    canonical_sha256,
    parse_json_strict,
)
from sn87_provenonce.simulation.lane_one_profile import parse_lane_one_task_profile
from sn87_provenonce.simulation.sensitivity_analysis import parse_sensitivity_analysis_spec
from sn87_provenonce.simulation.sensitivity_evidence import (
    raw_sha256,
    verify_sensitivity_evidence_bundle,
)

EXAMPLE_DIRECTORY = Path(__file__).parents[2] / "examples" / "sensitivity"


def _golden_projection(report: dict, profile_commitment: str) -> dict:
    canonical_report = canonical_json_bytes(report) + b"\n"
    result = report["analysis_result"]
    return {
        "canonical_report_sha256": raw_sha256(canonical_report),
        "claim_state": report["claim_state"],
        "componentwise_relations": result["componentwise_relations"],
        "normalized_spec_commitment": report["normalized_spec_commitment"],
        "profile_commitment": profile_commitment,
        "report_commitment": report["report_commitment"],
        "result_commitment": result["result_commitment"],
        "sensitivity_results": result["sensitivity_results"],
        "source_spec_sha256": report["source_spec_sha256"],
        "vector_state": "ILLUSTRATIVE_NON_NORMATIVE",
        "vector_version": "sn87/public-sensitivity-conformance-vector/0alpha1",
    }


def test_public_sensitivity_vector_is_reconstructable(tmp_path, capsys) -> None:
    policy_path = EXAMPLE_DIRECTORY / "illustrative-policy-identities.json"
    profile_path = EXAMPLE_DIRECTORY / "illustrative-task-profile.json"
    spec_path = EXAMPLE_DIRECTORY / "illustrative-sensitivity-spec.json"
    golden_path = EXAMPLE_DIRECTORY / "illustrative-golden.json"

    policies = parse_json_strict(policy_path.read_bytes())
    assert policies["state"] == "ILLUSTRATIVE_IDENTITY_ONLY"
    assert policies["commitment_domain"] == "SN87:EXAMPLE_POLICY_IDENTITY:v0alpha1"
    for identity in policies["identities"]:
        assert identity["identifier"] == identity["preimage"]["policy_id"]
        assert identity["preimage"]["purpose"] == "example-only"
        assert identity["commitment"] == canonical_sha256(
            identity["preimage"], domain=policies["commitment_domain"]
        )

    profile_bytes = profile_path.read_bytes()
    profile = parse_lane_one_task_profile(profile_bytes)
    assert profile_bytes == canonical_json_bytes(profile.to_payload()) + b"\n"
    bindings = {
        profile.severity_policy_binding.identifier: profile.severity_policy_binding.commitment,
        profile.false_positive_policy_binding.identifier: (
            profile.false_positive_policy_binding.commitment
        ),
    }
    assert bindings == {
        identity["identifier"]: identity["commitment"] for identity in policies["identities"]
    }

    spec_bytes = spec_path.read_bytes()
    spec = parse_sensitivity_analysis_spec(spec_bytes)
    assert spec_bytes == canonical_json_bytes(spec.to_payload()) + b"\n"
    assert spec.task_profile_commitment == profile.commitment
    assert {component.component for component in spec.baseline.components} == {
        component.value for component in profile.enabled_components
    }
    assert spec.production_policy_selected is False
    assert spec.estimator_preference_defined is False
    assert spec.normative_scoring is False
    assert spec.ranking_defined is False
    assert spec.weight_policy_defined is False
    assert spec.chain_action_defined is False

    assert main(["analyze-sensitivity", str(spec_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    golden = parse_json_strict(golden_path.read_bytes())
    assert all(value is False for value in report["boundaries"].values())
    assert _golden_projection(report, profile.commitment) == golden

    destination = tmp_path / "evidence"
    assert main(["analyze-sensitivity", str(spec_path), "--output-dir", str(destination)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "VERIFIED"
    assert created["source_spec_sha256"] == golden["source_spec_sha256"]
    assert created["normalized_spec_commitment"] == golden["normalized_spec_commitment"]
    assert created["result_commitment"] == golden["result_commitment"]
    assert created["report_commitment"] == golden["report_commitment"]
    assert destination.joinpath("sensitivity-spec.json").read_bytes() == spec_bytes
    assert verify_sensitivity_evidence_bundle(destination) == created
