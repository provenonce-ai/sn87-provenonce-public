# ADR-0014: Publish strict sensitivity evidence schemas

- Status: Accepted
- Date: 2026-09-04
- Decider: Will O'Brien, Provenonce

## Context

The sensitivity specification already has a generated JSON Schema, while the deterministic
analysis result, evidence report, and evidence manifest were represented only by implementation
dictionaries. Reconstruction protected the bundle, but an integrator could not validate these
outputs against versioned machine-readable contracts before invoking the full verifier.

The output schemas must describe the complete existing structure. A permissive object wrapper
would create the appearance of interoperability while leaving nested results unspecified.

## Decision

Define frozen, extra-field-forbidden models for the analysis result, report boundaries and limits,
complete evidence report, fixed bundle file map, and evidence manifest. Validate internal
specification, estimator, scenario, relation, source-hash, and commitment bindings. Use these
models on both production and verification paths while preserving the existing JSON bytes and
commitments.

Generate and check three schemas:

- `sensitivity-analysis-result.schema.json`;
- `sensitivity-evidence-report.schema.json`; and
- `sensitivity-evidence-manifest.schema.json`.

Public report and manifest parsers enforce their existing byte ceilings before JSON decoding.

## Options considered

### Publish documentation only

This has low implementation cost but provides no machine validation and allows documentation to
drift from executable behavior.

### Publish schemas with untyped nested objects

This is superficially convenient but does not constrain the analysis result and therefore does
not meet the interoperability requirement.

### Publish complete generated schemas

This adds model maintenance but keeps schemas, runtime construction, parsing, commitments, and
tests derived from one strict contract. This option was selected.

## Consequences

- Integrators can validate exact output shapes without interpreting implementation code.
- Unknown fields, numeric substitutes for reserved false values, broken internal bindings, and
  oversized parser inputs fail closed.
- Schema changes require an explicit contract-version decision.
- These schemas describe transparent evidence mechanics only. They do not define production
  scoring, ranking, weights, G1, hidden truth, networking, chain, or testnet behavior.
