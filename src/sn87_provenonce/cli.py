"""Local commands for validating the SN87 protocol baseline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import timedelta
from importlib.resources import files
from pathlib import Path

from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable
from sn87_provenonce.protocol.v0alpha1 import (
    AssuranceRequest,
    AssuranceResponse,
    evaluate_integrity_gate,
    parse_json_strict,
)
from sn87_provenonce.runtime import (
    ContentVerification,
    InMemoryMinerGateway,
    LocalMinerEndpoint,
    execute_validator_round,
    seal_validator_report,
    verify_validator_evidence_bundle,
    write_validator_evidence_bundle,
)
from sn87_provenonce.simulation import (
    run_lane_one_simulation,
    run_sensitivity_analysis,
    run_type_c_candidate_artifact,
    run_type_c_candidate_conformance,
    verify_evidence_bundle,
    verify_sensitivity_evidence_bundle,
    verify_type_c_candidate_artifact_evidence_bundle,
    verify_type_c_conformance_evidence_bundle,
    verify_type_c_evidence_bundle,
    write_evidence_bundle,
    write_sensitivity_evidence_bundle,
    write_type_c_candidate_artifact_evidence_bundle,
    write_type_c_conformance_evidence_bundle,
    write_type_c_evidence_bundle,
)

DEFAULT_VECTORS = files("sn87_provenonce.protocol.v0alpha1").joinpath("test_vectors")


def _load(path: object) -> object:
    return parse_json_strict(path.read_bytes())


def run_demo(vectors: object = DEFAULT_VECTORS) -> dict[str, object]:
    request = AssuranceRequest.model_validate(_load(vectors / "request.metadata-clean.json"))
    response = AssuranceResponse.model_validate(_load(vectors / "response.findings.json"))
    result = evaluate_integrity_gate(
        request,
        response,
        received_at=request.expires_at - timedelta(seconds=1),
        signature_valid=True,
        nonce_valid=True,
        policy_valid=True,
        evidence_valid=True,
    )
    return {
        "protocol_version": request.protocol_version,
        "challenge_id": request.challenge_id,
        "response_state": response.response_state,
        "integrity_gate": result.model_dump(mode="json") | {"passed": result.passed},
        "mode": "synthetic_local_conformance",
    }


def run_local_validator_demo(vectors: object = DEFAULT_VECTORS) -> dict[str, object]:
    """Exercise the local validator boundary with explicit synthetic integrity facts."""

    request = AssuranceRequest.model_validate(_load(vectors / "request.metadata-clean.json"))
    responses = {
        "miner-findings": AssuranceResponse.model_validate(
            _load(vectors / "response.findings.json")
        ),
        "miner-clean": AssuranceResponse.model_validate(
            _load(vectors / "response.no-material-deviation.json")
        ),
        "miner-abstain": AssuranceResponse.model_validate(_load(vectors / "response.abstain.json")),
        "miner-invalid-signature": AssuranceResponse.model_validate(
            _load(vectors / "response.findings.json")
        ),
    }

    async def findings(_request: AssuranceRequest) -> AssuranceResponse:
        return responses["miner-findings"]

    async def clean(_request: AssuranceRequest) -> AssuranceResponse:
        return responses["miner-clean"]

    async def abstain(_request: AssuranceRequest) -> AssuranceResponse:
        return responses["miner-abstain"]

    async def invalid_signature(_request: AssuranceRequest) -> AssuranceResponse:
        return responses["miner-invalid-signature"]

    received_at = request.expires_at - timedelta(seconds=1)
    gateway = InMemoryMinerGateway(
        {
            "miner-findings": LocalMinerEndpoint(findings, received_at, True, True),
            "miner-clean": LocalMinerEndpoint(clean, received_at, True, True),
            "miner-abstain": LocalMinerEndpoint(abstain, received_at, True, True),
            "miner-invalid-signature": LocalMinerEndpoint(
                invalid_signature, received_at, False, True
            ),
        }
    )

    class SyntheticVerifier:
        async def verify(self, miner_id, request, response):
            return ContentVerification(policy_valid=True, evidence_valid=True)

    result = asyncio.run(
        execute_validator_round(
            request,
            tuple(responses),
            gateway,
            SyntheticVerifier(),
            timeout_seconds=1.0,
        )
    )
    return seal_validator_report(result.to_dict())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sn87-provenonce")
    subcommands = parser.add_subparsers(dest="command", required=True)
    demo = subcommands.add_parser("demo", help="run the local synthetic conformance demo")
    demo.add_argument("--vectors", type=Path, default=DEFAULT_VECTORS)
    simulation = subcommands.add_parser(
        "simulate-lane-one",
        help="run the transparent local Lane One architecture simulation",
    )
    simulation.add_argument(
        "--force-no-valid-row",
        action="store_true",
        help="exercise the explicit no-valid-weight-row branch",
    )
    simulation.add_argument(
        "--output-dir",
        type=Path,
        help="create a new evidence bundle instead of printing the full report",
    )
    verify = subcommands.add_parser(
        "verify-simulation-bundle",
        help="verify a transparent simulation evidence bundle",
    )
    verify.add_argument("path", type=Path)
    type_c = subcommands.add_parser(
        "simulate-type-c-reference",
        help="run transparent Type-C reference-oracle fixtures",
    )
    type_c.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "create a new Type-C reference-oracle evidence bundle instead of printing "
            "the full report"
        ),
    )
    verify_type_c = subcommands.add_parser(
        "verify-type-c-bundle",
        help="verify a transparent Type-C reference-oracle evidence bundle",
    )
    verify_type_c.add_argument("path", type=Path)
    type_c_conformance = subcommands.add_parser(
        "conform-type-c-candidates",
        help="run deterministic candidates against the transparent Type-C reference oracle",
    )
    type_c_conformance.add_argument(
        "--output-dir",
        type=Path,
        help="create a new candidate-conformance evidence bundle instead of printing the report",
    )
    verify_type_c_conformance = subcommands.add_parser(
        "verify-type-c-conformance-bundle",
        help="verify a transparent Type-C candidate-conformance evidence bundle",
    )
    verify_type_c_conformance.add_argument("path", type=Path)
    type_c_artifact = subcommands.add_parser(
        "conform-type-c-artifact",
        help="evaluate one bounded offline candidate artifact against transparent Type-C",
    )
    type_c_artifact.add_argument("path", type=Path)
    type_c_artifact.add_argument(
        "--output-dir",
        type=Path,
        help="preserve the exact input and create a reconstructable evidence bundle",
    )
    verify_type_c_artifact = subcommands.add_parser(
        "verify-type-c-artifact-bundle",
        help="reconstruct and verify an offline candidate-artifact evidence bundle",
    )
    verify_type_c_artifact.add_argument("path", type=Path)
    validator = subcommands.add_parser(
        "run-local-validator",
        help="run the transport-neutral local validator demo",
    )
    validator.add_argument(
        "--output-dir",
        type=Path,
        help="create a new local-validator evidence bundle instead of printing the report",
    )
    verify_validator = subcommands.add_parser(
        "verify-validator-bundle",
        help="verify a local-validator evidence bundle",
    )
    verify_validator.add_argument("path", type=Path)
    sensitivity = subcommands.add_parser(
        "analyze-sensitivity",
        help="analyze one bounded offline sensitivity specification",
    )
    sensitivity.add_argument("path", type=Path)
    sensitivity.add_argument(
        "--output-dir",
        type=Path,
        help="preserve the exact input and create a reconstructable evidence bundle",
    )
    verify_sensitivity = subcommands.add_parser(
        "verify-sensitivity-bundle",
        help="reconstruct and verify an offline sensitivity-analysis evidence bundle",
    )
    verify_sensitivity.add_argument("path", type=Path)
    return parser


def _run_type_c_simulation() -> dict[str, object]:
    try:
        from sn87_provenonce.simulation.type_c_reference import run_type_c_simulation
    except ImportError as exc:
        raise PrivateReferenceExecutorUnavailable from exc
    return run_type_c_simulation()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main(argv)
    except PrivateReferenceExecutorUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _main(argv: Sequence[str] | None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        print(json.dumps(run_demo(args.vectors), indent=2, sort_keys=True))
        return 0
    if args.command == "simulate-lane-one":
        report = run_lane_one_simulation(force_no_valid_row=args.force_no_valid_row)
        if args.output_dir is not None:
            print(
                json.dumps(write_evidence_bundle(report, args.output_dir), indent=2, sort_keys=True)
            )
            return 0
        print(
            json.dumps(
                report,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "verify-simulation-bundle":
        print(json.dumps(verify_evidence_bundle(args.path), indent=2, sort_keys=True))
        return 0
    if args.command == "simulate-type-c-reference":
        report = _run_type_c_simulation()
        if args.output_dir is not None:
            print(
                json.dumps(
                    write_type_c_evidence_bundle(report, args.output_dir),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-type-c-bundle":
        print(json.dumps(verify_type_c_evidence_bundle(args.path), indent=2, sort_keys=True))
        return 0
    if args.command == "conform-type-c-candidates":
        report = run_type_c_candidate_conformance()
        if args.output_dir is not None:
            print(
                json.dumps(
                    write_type_c_conformance_evidence_bundle(report, args.output_dir),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-type-c-conformance-bundle":
        print(
            json.dumps(
                verify_type_c_conformance_evidence_bundle(args.path),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "conform-type-c-artifact":
        if args.output_dir is not None:
            result = write_type_c_candidate_artifact_evidence_bundle(args.path, args.output_dir)
        else:
            result = run_type_c_candidate_artifact(args.path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-type-c-artifact-bundle":
        print(
            json.dumps(
                verify_type_c_candidate_artifact_evidence_bundle(args.path),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "run-local-validator":
        report = run_local_validator_demo()
        if args.output_dir is not None:
            print(
                json.dumps(
                    write_validator_evidence_bundle(report, args.output_dir),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-validator-bundle":
        print(json.dumps(verify_validator_evidence_bundle(args.path), indent=2, sort_keys=True))
        return 0
    if args.command == "analyze-sensitivity":
        if args.output_dir is not None:
            result = write_sensitivity_evidence_bundle(args.path, args.output_dir)
        else:
            result = run_sensitivity_analysis(args.path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "verify-sensitivity-bundle":
        print(json.dumps(verify_sensitivity_evidence_bundle(args.path), indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
