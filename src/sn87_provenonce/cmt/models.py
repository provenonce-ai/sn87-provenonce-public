"""CMT v0.1 manifest and compatibility models (CANDIDATE schema; not an approved wire schema).

Source: the CMT specification candidate, sections 2-4 and 6. A spec item that cannot be backed by
existing committed code is the literal ``not_in_v0_1``; nothing is invented to fill it. Only
integers and strings appear (gra/0.1 has no floats; decimals are strings, as in profiles).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION = "sn87-cmt/0.1"
COMPAT_SCHEMA_VERSION = "sn87-cmt-compat/0.1"
NOT_IN_V0_1 = "not_in_v0_1"

Text = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
Commitment = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Int53 = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
NotInV01 = Literal["not_in_v0_1"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Identity(Strict):
    task_id: Text
    class_id: Text
    task_version: Text
    canonicalization_id: Text
    capsule_schema: Text
    differential_schema: Text
    normative_source_references: tuple[Text, ...]
    compatible_capsule_versions: tuple[Text, ...]
    compatible_differential_versions: tuple[Text, ...]


class Question(Strict):
    plain_language_task: Text
    claim_ontology: tuple[Text, ...]  # defect codes the contract can assert, sorted
    response_states: tuple[Text, ...]  # the three Differential states, sorted
    required_evidence: tuple[Text, ...]  # event kinds the capsule may declare coverage for
    allowed_transformations: NotInV01
    supported_source_mappings: NotInV01
    exclusions: tuple[Text, ...]


class Disclosure(Strict):
    supported_modes: tuple[Text, ...]
    declared_limits: tuple[Text, ...]
    private_data_embedded: Literal[False] = False
    evidence_access_policy_references: NotInV01
    benchmark_reuse_grant: NotInV01


class RuleReference(Strict):
    rule_code: Text
    severity: Text
    oracle_reference: Text  # name only; reference code is evaluator-only and not embedded


class Evaluation(Strict):
    measurement_profile_id: Text
    profile_commitment: Commitment  # from the committed, pinned profile document
    profile_commitment_domain: Text
    rule_references: tuple[RuleReference, ...]
    # Copied verbatim from the committed profile document (decimal strings stay strings).
    finding_equivalence: Text
    false_positive_floor: Text
    abstention_state: Text
    no_valid_row_behavior: Text
    evidence_quality: Text
    applicability_minimum_assignments: Int53
    maximum_raw_invalid_or_missing_rate: Text
    equivalent_diagnostics: Text
    score_epoch_weight_policy_references: NotInV01


class Limit(Strict):
    name: Text
    value: Int53
    unit: Text


class Operations(Strict):
    resource_limits: tuple[Limit, ...]
    time_limits: NotInV01
    instance_expiry: NotInV01
    method_capabilities: NotInV01
    authentication_rules: NotInV01
    replay_rules: tuple[Text, ...]
    lease_and_retry_identity: NotInV01
    feedback_reveal_rules: NotInV01


class Renewal(Strict):
    generator_reference: Text
    generator_version: Text  # the grammar id the generated capsules declare
    baseline_comparator: Text
    exposure_retirement_note: Text
    holdout_rules: NotInV01
    observable_view_admission_tests: NotInV01


class IdentityJoin(Strict):
    stage: Text
    identity_field: Text
    status: Literal["bound", "not_in_v0_1"]


class Observability(Strict):
    identity_chain: tuple[IdentityJoin, ...]
    aggregation_boundaries: NotInV01


class CMTManifest(Strict):
    schema_version: Literal["sn87-cmt/0.1"] = SCHEMA_VERSION
    adoption_status: Literal["CANDIDATE_SCHEMA_NOT_ADOPTED"] = "CANDIDATE_SCHEMA_NOT_ADOPTED"
    lifecycle_state: Literal["draft"] = "draft"
    identity: Identity
    question: Question
    disclosure: Disclosure
    evaluation: Evaluation
    operations: Operations
    renewal: Renewal
    observability: Observability
    not_in_v0_1: tuple[Text, ...]  # spec items left unspecified on purpose


class Binding(Strict):
    surface: Text
    reference: Text
    version: Text
    status: Literal["RESOLVED", "UNRESOLVED", "NOT_BOUND"]
    detail: Text


class Diagnostic(Strict):
    code: Text
    severity: Literal["INFO", "WARNING", "BLOCKING"]
    message: Text


class CompatibilityReport(Strict):
    schema_version: Literal["sn87-cmt-compat/0.1"] = COMPAT_SCHEMA_VERSION
    manifest_commitment: Commitment
    manifest_commitment_domain: Text
    bindings: tuple[Binding, ...]
    diagnostics: tuple[Diagnostic, ...]
    establishes: Text  # what compilation does and does not establish


class CompiledCMT(Strict):
    manifest: CMTManifest
    compatibility: CompatibilityReport
