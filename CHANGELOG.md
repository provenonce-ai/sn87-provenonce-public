# Changelog

This file records durable product milestones. Development chronology and internal operating
notes are maintained outside the repository.

## Unreleased

- Public export: the miner kit (`miners/`, `scripts/miner_serve.py`), the protocol, schemas and
  canonical modules, the scorer and evidence bundle, the local simulations and the attestation
  verifier are published. `scripts/verify_attestation.py` and the read-only chain client
  `scripts/chain_read.py` check every attested weight-set against the chain; the plan and
  validator-scoring checks need the private reference executors and report UNVERIFIED. Validator
  scoring, the reference executors and the operator tooling stay private.
- `PUBLIC_MANIFEST.json` classifies every tracked file of the source repository exactly once
  (allow, private, review_required, deny); `scripts/check_manifest.py` enforces it.
- Evidence bundle schema 0.3 (additive): `manifest.profile_document` and `profile_commitment_domain` carry the
  committed profile so readers verify the Eq. 13-15 gate values against `profile_commitment` instead of
  copying them.
- Evidence bundle schema 0.2 (additive): FIXTURE bundles carry per-case records (`cases`) so the
  equations can be recomputed from public data; REPLAY/LIVE never do.
- Status matrix: the composite row is relabelled "Eq.12 composite (Eq.9 per-perturbation base:
  no separate code)", correcting an overclaim found by the whitepaper audit.

### Release notes draft (scorer rebuild; not a release)

- Scorer rebuild: one profile family, one canonicalizer, one scorer, one evidence bundle. Breaking for code
  written against the earlier layout: removed `pilot/scoring.py`, `pilot/serialization.py`,
  `pilot/fixtures.py`, `institutional_v02/scoring.py`, `institutional_v02/serialization.py`;
  scorers have no defaults; `score_response(binding, ...)`, `epoch_estimate(..., profile)`,
  `preference_row(..., profile)`, `wire`. See `docs/releases/MIGRATION-scorer-rebuild.md`.

### Changed

- Added `LIMITATIONS.md`, `PROVENANCE.md`, `PUBLIC_MANIFEST.json`, `AGENTS.md`, draft miner and
  validator quickstarts, and protocol docs for profile application, wire rules and the evidence bundle.
- Rebuilt the implementation-status matrix as implemented / enabled / tested / deployed.
- Replaced "not testnet-ready" and "pre-release" wording with the actual status: alpha protocol,
  public testnet netuid 582, conformance evidence only.

## milestone/source-preserving-evidence-integrity-v0alpha1

### Changed

- Unified every evidence-bundle shape on one fail-closed filesystem boundary.
- Added componentwise no-follow parent traversal, mandatory platform controls, normalized
  descriptor and path failures, and bounded source-file reads.
- Pinned exact compatibility hashes for all files in the disclosed sensitivity and reference
  Type-C candidate bundles.
- Added adversarial coverage for parent-link races, intermediate parent links, unavailable
  platform controls, invalid paths, and descriptor metadata failures.

## milestone/shared-evidence-integrity-v0alpha1

### Changed

- Anchored every reusable two-file evidence writer and verifier to retained directory and file
  descriptors.
- Added bounded reads, exact canonical-snapshot checks, exclusive no-follow creation, single-link
  enforcement, and final path-identity verification.
- Added adversarial coverage for entry races, membership injection, concurrent mutation,
  directory substitution, hard links, and output ceilings.

## milestone/type-c-artifact-evidence-integrity-v0alpha1

### Changed

- Anchored offline Type-C evidence creation and verification to one directory descriptor.
- Added exclusive no-follow entry creation, single-link checks, stable closing snapshots, and
  directory-identity verification.
- Added caller-safe evidence failures and adversarial coverage for raced links, path substitution,
  membership injection, and concurrent mutation.

## milestone/strict-sensitivity-evidence-schemas-v0alpha1

### Added

- Strict typed contracts for sensitivity analysis results, evidence reports, and manifests.
- Generated JSON Schemas for the complete output structures.
- Bounded public parsers and internal binding validation for specifications, estimators,
  scenarios, relations, source hashes, and commitments.

## milestone/public-sensitivity-conformance-vector-v0alpha1

### Added

- A disclosed, non-normative task profile and sensitivity-analysis specification.
- Exact rational golden results and commitments for the public CLI path.
- End-to-end conformance coverage from policy-identity preimages through evidence reconstruction.

## milestone/transparent-sensitivity-evidence-v0alpha1

### Added

- Bounded offline sensitivity-spec ingestion and deterministic analysis CLI.
- Create-only evidence bundles that preserve exact source bytes and reconstruct results.
- Verification for exact membership, canonical report and manifest bytes, raw hashes, and
  semantic commitments.

## milestone/transparent-sensitivity-analysis-v0alpha1

### Added

- Exact, committed sensitivity analysis over disclosed component vectors.
- Pairwise componentwise dominance relations without winner selection or ranking.
- Strict analysis specification and generated schema.

## milestone/transparent-estimator-comparison-v0alpha1

### Added

- Exact comparison of weighted arithmetic and weighted harmonic component estimators.
- Versioned estimator specifications, generated schema, and fail-closed artifact parsing.
- Immutable milestone-tag policy.

## milestone/lane-one-task-profile-v0alpha1

### Added

- Versioned Lane One task profiles with canonical commitments.
- Explicit component enablement and identity-only upstream policy bindings.
- Required closed boundaries for scoring, ranking, weights, and chain actions.
- Generated task-profile JSON Schema and profile-bound component measurements.
