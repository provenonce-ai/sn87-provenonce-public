"""Export deterministic JSON Schemas for the implemented protocol models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sn87_provenonce.cmt.models import CMTManifest, CompatibilityReport
from sn87_provenonce.protocol.v0alpha1.models import (
    AdmissibilityDeclaration,
    AssuranceCapsule,
    AssuranceFinding,
    AssuranceRequest,
    AssuranceResponse,
)
from sn87_provenonce.simulation.estimator_comparison import EstimatorSpec
from sn87_provenonce.simulation.lane_one_profile import LaneOneTaskProfile
from sn87_provenonce.simulation.sensitivity_analysis import (
    SensitivityAnalysisResult,
    SensitivityAnalysisSpec,
)
from sn87_provenonce.simulation.sensitivity_evidence_models import (
    SensitivityEvidenceManifest,
    SensitivityEvidenceReport,
)
from sn87_provenonce.simulation.type_c_candidate_artifact import TypeCCandidateArtifact

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "protocol" / "v0alpha1" / "schemas"
MODELS = {
    "admissibility-declaration.schema.json": AdmissibilityDeclaration,
    "assurance-capsule.schema.json": AssuranceCapsule,
    "assurance-finding.schema.json": AssuranceFinding,
    "assurance-request.schema.json": AssuranceRequest,
    "assurance-response.schema.json": AssuranceResponse,
    "cmt-compatibility-report.schema.json": CompatibilityReport,
    "cmt-manifest.schema.json": CMTManifest,
    "estimator-spec.schema.json": EstimatorSpec,
    "lane-one-task-profile.schema.json": LaneOneTaskProfile,
    "sensitivity-analysis-result.schema.json": SensitivityAnalysisResult,
    "sensitivity-analysis-spec.schema.json": SensitivityAnalysisSpec,
    "sensitivity-evidence-manifest.schema.json": SensitivityEvidenceManifest,
    "sensitivity-evidence-report.schema.json": SensitivityEvidenceReport,
    "type-c-candidate-artifact.schema.json": TypeCCandidateArtifact,
}


def rendered_schema(model: type) -> str:
    schema = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True)
    return schema + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches: list[str] = []
    if not args.check:
        SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS.items():
        target = SCHEMA_DIR / filename
        expected = rendered_schema(model)
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != expected:
                mismatches.append(filename)
        else:
            target.write_text(expected, encoding="utf-8")
    if mismatches:
        parser.error(f"generated schemas are stale: {', '.join(mismatches)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
