"""Compile the current task family into a CMT manifest plus compatibility report.

Everything is read from committed code and the committed, pinned profile; nothing is
invented. A profile that no longer matches its pinned commitment, or a family this compiler
does not know, fails closed (``CMTCompileError``). Unresolved or unbound obligations are
reported as diagnostics, never as validity. Compilation establishes structure and
reproducibility only: not semantic truth, author authorization or useful economics.
Output is deterministic: the same inputs give byte-identical ``compiled_bytes``.
"""

from __future__ import annotations

from sn87_provenonce import bundle, classes, profile
from sn87_provenonce.canonical import CANONICALIZER_ID, MAX_BYTES, canonical_bytes
from sn87_provenonce.cmt import models as m
from sn87_provenonce.cmt.hashing import CMT_DOMAIN, cmt_commitment
from sn87_provenonce.institutional_v02 import contracts as ic

TASK_FAMILY = "IC-APPROVAL-APPLICABILITY"
PROFILE_ID = "IC-FIRST-LIGHT-MIN-1"
TASK_VERSION = "0.1.0"
GENERATOR_REFERENCE = "sn87_provenonce.institutional_v02.fixtures.build_case"
GENERATOR_GRAMMAR = "FIRST_LIGHT_MINIMAL_TYPE_C_0.2"
ORACLE_REFERENCE = "sn87_provenonce.institutional_v02.references.agreed_truth"
BASELINE_REFERENCE = "sn87_provenonce.baselines.ic_approval_applicability"
SPEC_REFERENCE = ("W08 SPECIFICATION_CANDIDATE sections 2-4 and 6 "
                  "(candidate; not an approved wire schema)")
# Spec items (sections 3-4, 6) that no committed code backs today; each is `not_in_v0_1` above.
NOT_IN_V0_1 = (
    "question.allowed_transformations", "question.supported_source_mappings",
    "disclosure.evidence_access_policy_references", "disclosure.benchmark_reuse_grant",
    "evaluation.score_epoch_weight_policy_references",
    "operations.time_limits", "operations.instance_expiry", "operations.method_capabilities",
    "operations.authentication_rules", "operations.lease_and_retry_identity",
    "operations.feedback_reveal_rules", "renewal.holdout_rules",
    "renewal.observable_view_admission_tests", "observability.aggregation_boundaries",
    "signatures", "consent_and_access_enforcement", "instance_state_machine_binding",
    "public_conformance_vectors_beyond_the_golden_cmt", "human_task_card",
)


class CMTCompileError(ValueError):
    """The task family, profile or bindings cannot be resolved; no artifact is produced."""


def _load_profile(expected_commitment: str | None) -> profile.Profile:
    try:
        bound = profile.load(PROFILE_ID)
    except profile.ProfileNotApplied as exc:
        raise CMTCompileError(f"profile does not resolve: {exc}") from exc
    if expected_commitment is not None and bound.commitment != expected_commitment:
        raise CMTCompileError("profile commitment differs from the expected commitment")
    return bound


def _manifest(bound: profile.Profile) -> m.CMTManifest:
    doc = bound.document
    registry_domain = profile.REGISTRY[PROFILE_ID][1]
    rules = tuple(
        m.RuleReference(rule_code=code, severity=sev, oracle_reference=ORACLE_REFERENCE)
        for code, sev in sorted(ic.DEFECT_SEVERITY.items())
    )
    return m.CMTManifest(
        identity=m.Identity(
            task_id="ic-approval-applicability",
            class_id=bound.class_id,
            task_version=TASK_VERSION,
            canonicalization_id=CANONICALIZER_ID,
            capsule_schema=ic.SCHEMA,
            differential_schema=ic.SCHEMA,
            normative_source_references=(
                SPEC_REFERENCE,
                f"profile:{PROFILE_ID}",
                "module:sn87_provenonce.institutional_v02.contracts",
            ),
            compatible_capsule_versions=(ic.SCHEMA,),
            compatible_differential_versions=(ic.SCHEMA,),
        ),
        question=m.Question(
            plain_language_task=(
                "Given a bounded capsule of approval, review, handoff and action events over "
                "three episodes and two agents, say whether an action relied on an approval "
                "that was stale or not applicable, or abstain when the declared evidence "
                "coverage is insufficient."),
            claim_ontology=tuple(sorted(ic.DEFECT_SEVERITY)),
            response_states=tuple(sorted(ic.STATES)),
            required_evidence=tuple(sorted(ic.FIELDS)),
            allowed_transformations=m.NOT_IN_V0_1,
            supported_source_mappings=m.NOT_IN_V0_1,
            exclusions=(
                "Not a certification of a whole business or process.",
                "Does not establish author authorization or semantic truth of source records.",
                "Fictional fixtures only; no real customer policy is described.",
            ),
        ),
        disclosure=m.Disclosure(
            supported_modes=("CAPSULE_EVENTS_WITH_ARTIFACT_COMMITMENTS",),
            declared_limits=(
                "Artifact content is represented by commitments only; a commitment cannot "
                "substantiate hidden content.",
                "No private tenant history, credentials, answer keys or reuse grants are "
                "embedded in a CMT.",
            ),
            evidence_access_policy_references=m.NOT_IN_V0_1,
            benchmark_reuse_grant=m.NOT_IN_V0_1,
        ),
        evaluation=m.Evaluation(
            measurement_profile_id=bound.profile_id,
            profile_commitment=bound.commitment,
            profile_commitment_domain=registry_domain,
            rule_references=rules,
            finding_equivalence=doc["matching"],
            false_positive_floor=doc["false_positive_floor"],
            abstention_state="INSUFFICIENT_EVIDENCE_ABSTAIN",
            no_valid_row_behavior=doc["no_valid_row"],
            evidence_quality=doc["evidence_quality"],
            applicability_minimum_assignments=doc["minimum_assignments"],
            maximum_raw_invalid_or_missing_rate=doc["maximum_raw_invalid_or_missing_rate"],
            equivalent_diagnostics=doc["equivalent_diagnostics"],
            score_epoch_weight_policy_references=m.NOT_IN_V0_1,
        ),
        operations=m.Operations(
            resource_limits=(
                m.Limit(name="wire_max_bytes", value=doc["wire_max_bytes"], unit="bytes"),
                m.Limit(name="private_storage_max_bytes",
                        value=doc["private_storage_max_bytes"], unit="bytes"),
                m.Limit(name="capsule_events_max", value=64, unit="events"),
                m.Limit(name="capsule_source_commitments_max", value=32, unit="commitments"),
            ),
            time_limits=m.NOT_IN_V0_1,
            instance_expiry=m.NOT_IN_V0_1,
            method_capabilities=m.NOT_IN_V0_1,
            authentication_rules=m.NOT_IN_V0_1,
            replay_rules=(
                "A Differential must bind the capsule qid and evidence_commitment "
                "(validate_differential).",
                "Replay rejection, lease fencing and idempotent attachment are service-level "
                "and not declared by this CMT.",
            ),
            lease_and_retry_identity=m.NOT_IN_V0_1,
            feedback_reveal_rules=m.NOT_IN_V0_1,
        ),
        renewal=m.Renewal(
            generator_reference=GENERATOR_REFERENCE,
            generator_version=GENERATOR_GRAMMAR,
            baseline_comparator=BASELINE_REFERENCE,
            exposure_retirement_note=(
                "Public fictional fixtures only; private generators, seeds and reference "
                "truth stay in protected storage. No retirement rule is declared."),
            holdout_rules=m.NOT_IN_V0_1,
            observable_view_admission_tests=m.NOT_IN_V0_1,
        ),
        observability=m.Observability(
            identity_chain=(
                m.IdentityJoin(stage="source", identity_field="capsule.source_commitments",
                               status="bound"),
                m.IdentityJoin(stage="capsule", identity_field="capsule.evidence_commitment",
                               status="bound"),
                m.IdentityJoin(stage="class_profile",
                               identity_field="evaluation.profile_commitment", status="bound"),
                m.IdentityJoin(stage="assignment", identity_field=m.NOT_IN_V0_1,
                               status="not_in_v0_1"),
                m.IdentityJoin(stage="differential",
                               identity_field="differential.capsule_commitment",
                               status="bound"),
                m.IdentityJoin(stage="evaluation", identity_field=bundle.SCHEMA,
                               status="bound"),
                m.IdentityJoin(stage="consumer_disposition", identity_field=m.NOT_IN_V0_1,
                               status="not_in_v0_1"),
            ),
            aggregation_boundaries=m.NOT_IN_V0_1,
        ),
        not_in_v0_1=NOT_IN_V0_1,
    )


def _compatibility(manifest: m.CMTManifest, bound: profile.Profile) -> m.CompatibilityReport:
    binding = classes.BINDINGS.get(bound.class_id)
    if binding is None or binding.profile.commitment != bound.commitment:
        raise CMTCompileError("class binding does not resolve to the committed profile")
    bindings = (
        m.Binding(surface="canonicalizer", reference=CANONICALIZER_ID, version=CANONICALIZER_ID,
                  status="RESOLVED",
                  detail=f"sn87_provenonce.canonical (max {MAX_BYTES} bytes)"),
        m.Binding(surface="measurement_profile", reference=bound.profile_id,
                  version=bound.commitment, status="RESOLVED",
                  detail="loaded from the committed document; equals its pinned commitment"),
        m.Binding(surface="class_binding", reference=binding.class_id, version=binding.schema,
                  status="RESOLVED", detail="sn87_provenonce.classes.IC_APPROVAL_APPLICABILITY"),
        m.Binding(surface="request_model", reference="capsule", version=ic.SCHEMA,
                  status="RESOLVED",
                  detail="institutional_v02.contracts.validate_capsule (request = capsule)"),
        m.Binding(surface="response_model", reference="differential", version=ic.SCHEMA,
                  status="RESOLVED",
                  detail="institutional_v02.contracts.validate_differential"),
        m.Binding(surface="evidence_bundle", reference="sn87_provenonce.bundle",
                  version=bundle.SCHEMA, status="RESOLVED",
                  detail="schema version the evaluation emits for this class"),
        m.Binding(surface="request_model", reference="protocol.v0alpha1.AssuranceRequest",
                  version="sn87/0alpha1", status="NOT_BOUND",
                  detail="historical draft profile; different encoding from institution/0.2"),
        m.Binding(surface="response_model", reference="protocol.v0alpha1.AssuranceResponse",
                  version="sn87/0alpha1", status="NOT_BOUND",
                  detail="historical draft profile; different encoding from institution/0.2"),
        m.Binding(surface="instance_state_machine", reference="service.queue",
                  version=m.NOT_IN_V0_1, status="NOT_BOUND",
                  detail="local queue states exist; spec section 6 state machine not bound"),
    )
    diagnostics = (
        m.Diagnostic(code="CMT_SCHEMA_NOT_ADOPTED", severity="INFO",
                     message="sn87-cmt/0.1 is a candidate schema; no wire adoption is claimed."),
        m.Diagnostic(code="V0ALPHA1_MODELS_NOT_BOUND", severity="WARNING",
                     message="Pilot/institutional encodings differ from v0alpha1 models; the "
                             "CMT binds the institution/0.2 contract only (spec section 6)."),
        m.Diagnostic(code="NOT_IN_V0_1_ITEMS", severity="WARNING",
                     message=f"{len(manifest.not_in_v0_1)} spec items are not_in_v0_1: "
                             + ", ".join(manifest.not_in_v0_1)),
        m.Diagnostic(code="INSTANCE_NOT_DISPATCHABLE", severity="WARNING",
                     message="No instance expiry, authentication or lease identity is declared; "
                             "this CMT cannot by itself bind a dispatchable instance."),
        m.Diagnostic(code="STRUCTURE_ONLY", severity="INFO",
                     message="Compilation establishes structure and reproducibility, not "
                             "semantic truth, author authorization or useful economics."),
    )
    return m.CompatibilityReport(
        manifest_commitment=cmt_commitment(manifest),
        manifest_commitment_domain=CMT_DOMAIN,
        bindings=bindings,
        diagnostics=diagnostics,
        establishes="structure and reproducibility only",
    )


def compile_cmt(*, task_family: str = TASK_FAMILY,
                expected_profile_commitment: str | None = None) -> m.CompiledCMT:
    """Compile ``task_family`` (currently only IC-APPROVAL-APPLICABILITY) deterministically."""
    if task_family != TASK_FAMILY:
        raise CMTCompileError(f"unsupported task family {task_family!r}")
    bound = _load_profile(expected_profile_commitment)
    manifest = _manifest(bound)
    return m.CompiledCMT(manifest=manifest, compatibility=_compatibility(manifest, bound))


def compiled_bytes(compiled: m.CompiledCMT) -> bytes:
    """Canonical (gra/0.1) bytes of the manifest plus compatibility artifact."""
    return canonical_bytes(compiled.model_dump(mode="json"))
