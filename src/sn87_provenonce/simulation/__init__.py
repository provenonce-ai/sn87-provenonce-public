"""Transparent local simulations for SN87 development.

Exports resolve lazily (PEP 562), so importing one submodule, such as the public Type C
data model, never loads the evaluator-only reference executors as a side effect.
"""

from importlib import import_module

_EXPORTS = {
    "ComponentValue": "estimator_comparison",
    "EstimatorKind": "estimator_comparison",
    "EstimatorSpec": "estimator_comparison",
    "UnitRatio": "estimator_comparison",
    "compare_estimators": "estimator_comparison",
    "create_estimator_spec": "estimator_comparison",
    "estimate_components": "estimator_comparison",
    "parse_estimator_spec": "estimator_comparison",
    "verify_evidence_bundle": "evidence",
    "write_evidence_bundle": "evidence",
    "NO_VALID_WEIGHT_ROW": "lane_one",
    "WEIGHT_SCALE": "lane_one",
    "build_weight_intent": "lane_one",
    "run_lane_one_simulation": "lane_one",
    "FalsePositiveAssessment": "lane_one_measurement",
    "FindingClaim": "lane_one_measurement",
    "PlantedDefect": "lane_one_measurement",
    "measure_lane_one_case": "lane_one_measurement",
    "PROFILE_VERSION": "lane_one_profile",
    "ExactRatio": "lane_one_profile",
    "LaneOneTaskProfile": "lane_one_profile",
    "MatchingPolicy": "lane_one_profile",
    "MeasurementComponent": "lane_one_profile",
    "PolicyBinding": "lane_one_profile",
    "create_lane_one_task_profile": "lane_one_profile",
    "parse_lane_one_task_profile": "lane_one_profile",
    "ChangeDirection": "sensitivity_analysis",
    "ComponentVector": "sensitivity_analysis",
    "ComponentwiseRelation": "sensitivity_analysis",
    "ComponentwiseRelationResult": "sensitivity_analysis",
    "EstimatorSensitivityResult": "sensitivity_analysis",
    "SensitivityAnalysisResult": "sensitivity_analysis",
    "SensitivityAnalysisSpec": "sensitivity_analysis",
    "SensitivityScenarioResult": "sensitivity_analysis",
    "SignedRatio": "sensitivity_analysis",
    "analyze_sensitivity": "sensitivity_analysis",
    "create_sensitivity_analysis_spec": "sensitivity_analysis",
    "parse_sensitivity_analysis_spec": "sensitivity_analysis",
    "SensitivityEvidenceError": "sensitivity_evidence",
    "run_sensitivity_analysis": "sensitivity_evidence",
    "run_sensitivity_analysis_bytes": "sensitivity_evidence",
    "verify_sensitivity_evidence_bundle": "sensitivity_evidence",
    "write_sensitivity_evidence_bundle": "sensitivity_evidence",
    "SensitivityEvidenceManifest": "sensitivity_evidence_models",
    "SensitivityEvidenceReport": "sensitivity_evidence_models",
    "parse_sensitivity_evidence_manifest": "sensitivity_evidence_models",
    "parse_sensitivity_evidence_report": "sensitivity_evidence_models",
    "FIXTURES": "type_c",
    "TypeCFixture": "type_c",
    "ReferenceOutcome": "type_c_reference",
    "compare_reference_executions": "type_c_reference",
    "execute_relational": "type_c_reference",
    "execute_state_machine": "type_c_reference",
    "run_type_c_simulation": "type_c_reference",
    "ARTIFACT_TYPE": "type_c_candidate_artifact",
    "ARTIFACT_VERSION": "type_c_candidate_artifact",
    "CandidateArtifactError": "type_c_candidate_artifact",
    "TypeCCandidateArtifact": "type_c_candidate_artifact",
    "parse_candidate_artifact": "type_c_candidate_artifact",
    "run_type_c_candidate_artifact": "type_c_candidate_artifact",
    "run_type_c_candidate_artifact_bytes": "type_c_candidate_artifact",
    "CandidateArtifactEvidenceError": "type_c_candidate_artifact_evidence",
    "verify_type_c_candidate_artifact_evidence_bundle": "type_c_candidate_artifact_evidence",
    "write_type_c_candidate_artifact_evidence_bundle": "type_c_candidate_artifact_evidence",
    "CANDIDATE_CASES": "type_c_conformance",
    "CandidateCase": "type_c_conformance",
    "evaluate_candidate": "type_c_conformance",
    "run_type_c_candidate_conformance": "type_c_conformance",
    "verify_type_c_conformance_evidence_bundle": "type_c_conformance_evidence",
    "write_type_c_conformance_evidence_bundle": "type_c_conformance_evidence",
    "verify_type_c_evidence_bundle": "type_c_evidence",
    "write_type_c_evidence_bundle": "type_c_evidence",
}
__all__ = sorted(_EXPORTS)


def __dir__() -> list[str]:
    return __all__


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{_EXPORTS[name]}"), name)
