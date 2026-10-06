# v0alpha1 protocol field traceability

This register maps every implemented field to the corresponding requirement in the SN87
protocol specification. Field names are transport-neutral implementation choices unless the
specification names them directly.

Status meanings:

- **direct**: the specification names the object or semantic requirement.
- **derived**: required to make a directly specified invariant machine-readable.
- **provisional**: a bounded v0alpha1 choice that a future protocol version may replace.
- **held**: intentionally not implemented because the specification leaves a normative choice open.

## Shared constraints

| Field or rule | Status | Protocol source | Implementation boundary |
|---|---|---|---|
| `protocol_version` | direct | Message Flow; Formal Object Model; Proposed Signed Request / Response Contract | Fixed to `sn87/0alpha1`; incompatible protocol changes require a new version or migration. |
| strict unknown-field rejection | derived | Reader's Contract; Canonicalization as an Attack Surface | Prevents undeclared extensions from silently changing the contract. |
| immutable validated models | provisional | Canonicalization as an Attack Surface | Local safety choice; not a claim that the specification mandates Pydantic immutability. |
| `sha256:` commitment syntax | direct | Cryptographic Humility; Evidence commitment equations 18a–18c | Syntax is stable; v0alpha1 object commitments are not the unresolved Evidence commitment formula. |

## Source and Evidence bindings

| Object.field | Status | Protocol source | Implementation boundary |
|---|---|---|---|
| `SourceBinding.source_id` | derived | Source Precedes Synthesis; Assurance Capsule reconstructability | Transport-neutral source identifier; identifier registry is provisional. |
| `SourceBinding.commitment` | direct | Assurance Capsule; Cryptographic Humility | Binds the declared source bytes without claiming they describe reality. |
| `EvidenceReference.commitment` | direct | Digital Commodity; Assurance Finding; Hard Integrity Gate | References committed Evidence; large Evidence remains outside the response. |
| `EvidenceReference.predicate` | derived | Evidence as Commodity; Assurance Finding | States the bounded proposition the Evidence supports. Predicate vocabulary is provisional. |

## Disclosure policy and Assurance Capsule

| Object.field | Status | Protocol source | Implementation boundary |
|---|---|---|---|
| `DisclosurePolicy.policy_id` | derived | Privacy-Preserving Assurance | Versionable identifier for the governing disclosure policy. |
| `DisclosurePolicy.mode` | direct | Metadata Assurance; Selective Evidence; Confidential Challenge | Exactly one declared disclosure mode for the Capsule. |
| `DisclosurePolicy.allowed_evidence_predicates` | derived | Privacy Budget; Data Retention | Explicit allow-list; predicate registry remains provisional. |
| `DisclosurePolicy.privacy_budget` | direct | Privacy Budget | Unit-interval representation is provisional pending final calibration. |
| `AssuranceCapsule.capsule_id` | derived | Assurance Capsule | Stable transport identifier; generation rule is provisional. |
| `AssuranceCapsule.signal` | direct | Canonical Model of Work; Assurance Capsule | Bounded representation of Signal or Signal class. |
| `AssuranceCapsule.orchestration` | direct | Canonical Model of Work; Canonical Boundary | Does not redefine the source-system Orchestration. |
| `AssuranceCapsule.constraints` | direct | Canonical Model of Work; Assurance Capsule | Relevant CPC constraints only. |
| `AssuranceCapsule.observed_paths` | direct | Canonical Model of Work; Assurance Capsule | Observed Path executions, not inferred ideal paths. |
| `AssuranceCapsule.pipeline` | direct | Canonical Model of Work; Assurance Capsule | Pipeline trace, not a recursively redefined CPC. |
| `AssuranceCapsule.evidence` | direct | Assurance Capsule; Reconstructability | Only admissible Evidence references under policy. |
| `AssuranceCapsule.context` | direct | Assurance Capsule | Policy, entitlement, and environmental context needed to interpret the run. |
| `AssuranceCapsule.source_bindings` | direct | Source Precedes Synthesis; Reconstructability | At least one binding is required. |
| `AssuranceCapsule.disclosure_policy` | direct | Disclosure transform; Privacy-Preserving Assurance | Policy is part of the transport object. |
| `AssuranceCapsule.mapping_confidence` | direct | Canonicalization as an Attack Surface | Confidence is explicit for external-system mapping. |
| `AssuranceCapsule.limitations` | derived | Reconstructability; Public Limitations | Unknowns and mapping loss remain visible. |

## Oracle, admissibility, and cost

| Object.field | Status | Protocol source | Implementation boundary |
|---|---|---|---|
| `OracleBinding.oracle_class` | direct | Oracle Taxonomy | One of Type A, B, C, or D. Residual claims are declared separately. |
| `OracleBinding.identifier` | derived | Admissibility Declaration | Transport-neutral rule-set, public source, reference, or adjudication identifier. |
| `OracleBinding.commitment` | direct | Type D; Admissibility Declaration | Required for Type D; optional for other classes in v0alpha1. |
| `OracleBinding.reliability` | direct | Type D | Required for Type D and bounded to `(0, 1]`. |
| `OracleBinding.reliability_method` | direct | Type D; example admissibility object | Required for Type D so reliability is not an unexplained scalar. |
| `CostBudget.seconds` | direct | Admissibility Declaration | Positive execution-time ceiling. |
| `CostBudget.credits` | direct | Admissibility Declaration | Nonnegative abstract credit ceiling; unit economics are unresolved. |
| `CostBudget.privacy_budget` | direct | Admissibility Declaration; Privacy Budget | Unit-interval v0alpha1 representation. |
| `AdmissibilityDeclaration.challenge_class` | direct | Challenge Object; Admissibility Declaration | Visible class identifier. |
| `AdmissibilityDeclaration.challenge_class_version` | direct | Formal Object Model | Explicit version separated from the class name. |
| `AdmissibilityDeclaration.claim_types` | direct | Admissibility Declaration | Declares the claim types a miner is asked to make. |
| `AdmissibilityDeclaration.oracle_bindings` | direct | Admissibility Declaration | At least one declared truth source. |
| `AdmissibilityDeclaration.residual_fields` | direct | Residual: documented, not silently scored | Excluded from silent scoring. |
| `AdmissibilityDeclaration.disclosure_modes` | direct | Admissibility Declaration | Modes admissible for this class. |
| `AdmissibilityDeclaration.max_cost` | direct | Admissibility Declaration | Makes resource and privacy ceilings inspectable. |

## Request, Differential, and Finding

| Object.field | Status | Protocol source | Implementation boundary |
|---|---|---|---|
| `AssuranceRequest.challenge_id` | direct | Challenge Object; Proposed Signed Contract | Binds response and findings to one challenge. |
| `AssuranceRequest.challenge_class` | direct | Challenge Object; Proposed Signed Contract | Must equal the visible-policy class. |
| `AssuranceRequest.capsule` | direct | Message Flow; Proposed Signed Contract | The policy-minimized evaluation object. |
| `AssuranceRequest.visible_policy` | direct | Challenge Object; Admissibility Declaration | v0alpha1 implements admissibility, oracle, disclosure, and cost fields; scoring parameters and reveal/audit policy remain held. |
| `AssuranceRequest.hidden_commitment` | direct | Challenge Object; Formal Object Model | Commits to hidden state without revealing it. |
| `AssuranceRequest.nonce` | direct | Message Flow; Hard Integrity Gate | Transport freshness verification remains outside this model. |
| `AssuranceRequest.expires_at` | direct | Challenge Object; Hard Integrity Gate | Requires an explicit timezone. Canonical timestamp spelling remains held. |
| `AssuranceFinding.finding_id` | direct | Assurance Finding | Stable finding identifier; generation rule is provisional. |
| `AssuranceFinding.challenge_id` | derived | Message Flow; Miner Differential | Must match the response challenge. |
| `AssuranceFinding.finding_type` | direct | Assurance Finding | Vocabulary remains provisional. |
| `AssuranceFinding.claim` | direct | Assurance Finding | Nonempty bounded claim. |
| `AssuranceFinding.severity` | direct | Assurance Finding | Unit-interval representation; calibration is unresolved. |
| `AssuranceFinding.confidence` | direct | Miner Differential; Proposed Signed Contract | Required per finding unless a nonempty response-level calibration report exists. |
| `AssuranceFinding.oracle_class` | direct | Oracle Taxonomy; Assurance Finding | Declares how the finding can be judged. |
| `AssuranceFinding.evidence` | direct | Miner Differential; Assurance Finding | At least one Evidence reference is required. |
| `AssuranceFinding.counterfactual_path` | direct | Miner Differential | Optional and conditional on support. |
| `AssuranceFinding.limitations` | direct | Miner Differential; Public Limitations | Keeps claim limits reviewable. |
| `AssuranceFinding.recommended_action` | direct | Assurance Finding | Action is advice, not execution authority. |
| `CalibrationReport.method` | derived | Calibrated Confidence; Required Experiment Report | Names the calibration method. |
| `CalibrationReport.claim_confidences` | direct | Miner Differential; Proposed Signed Contract | Nonempty per-claim confidence map; when present, keys must exactly equal the response finding IDs so unrelated, incomplete, or ghost calibration claims cannot satisfy the contract. |
| `AssuranceResponse.challenge_id` | direct | Proposed Signed Contract | Must match the request. |
| `AssuranceResponse.response_state` | direct | Digital Commodity; Response States | Exactly one of the three first-class states. |
| `AssuranceResponse.rationale` | direct | Digital Commodity; Proposed Signed Contract | Nonempty for every state. |
| `AssuranceResponse.findings` | direct | Miner Differential; Proposed Signed Contract | Nonempty only for `FINDINGS`; absent or empty otherwise. |
| `AssuranceResponse.counterfactual_paths` | direct | Miner Differential; Proposed Signed Contract | Optional and conditional. Element type is a provisional string representation. |
| `AssuranceResponse.confidence_report` | direct | Miner Differential; Proposed Signed Contract | Required only when findings omit per-finding confidence. |
| `AssuranceResponse.evidence_requests` | direct | Proposed Signed Contract | Optional bounded request; element type is provisional. |
| `AssuranceResponse.miner_commitment` | direct | Formal Object Model; Message Flow | Commitment is modeled; signed HTTP response metadata remains transport-owned and held. |

## Integrity result

| Object.field | Status | Protocol source | Implementation boundary |
|---|---|---|---|
| `IntegrityGateResult.schema_valid` | direct | Hard Integrity Gate | Includes version and challenge binding after structural model validation. |
| `IntegrityGateResult.policy_valid` | direct | Hard Integrity Gate | Supplied by the policy evaluator; not fabricated locally. |
| `IntegrityGateResult.signature_valid` | direct | Hard Integrity Gate; Message Flow | Supplied by the future pinned `bittensor.http_auth` envelope verifier. |
| `IntegrityGateResult.nonce_valid` | direct | Hard Integrity Gate; Message Flow | Supplied by the future replay/freshness verifier. |
| `IntegrityGateResult.evidence_valid` | direct | Hard Integrity Gate | Applies when Evidence is asserted; negative/abstention states do not invent Evidence requirements. |
| `IntegrityGateResult.deadline_valid` | direct | Hard Integrity Gate | Computed from timezone-aware receipt and expiry times. |
| `IntegrityGateResult.failures` | derived | Hard Integrity Gate | Machine-readable non-compensable failure reasons. |

## Explicit protocol holds

The following are not part of v0alpha1 and must not be inferred:

- the byte width and exact encoding of `LP(x)` in the Evidence commitment;
- canonical numeric and timestamp spellings beyond the current bounded JSON profile;
- Merkle leaf/node domains and canonical tree construction;
- complete visible scoring parameters and their calibrated constants;
- reveal/audit-policy fields and challenge hidden-state representation;
- signed HTTP request/response metadata and a pinned Bittensor v11 transport;
- validator scoring, epoch aggregation, normalization, weight intent, and chain behavior;
- Lane One preregistration thresholds, sealed fixtures, and benchmark truth; and
- any public-license, package-publication, testnet, deployment, or launch decision.

These holds remain controlling even when the implemented v0alpha1 fields pass local tests.
