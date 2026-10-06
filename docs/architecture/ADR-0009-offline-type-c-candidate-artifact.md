# ADR-0009: Preserve exact offline candidate bytes and separate them from test expectations

**Status:** Accepted for transparent local conformance

**Date:** 2026-09-04

**Decider:** Will O'Brien, Provenonce Founder & CEO

## Context

ADR-0008 proves the comparison mechanics with a 17-case internal harness. That harness contains
known pass/fail expectations and adversarial reference answers. Treating it as a candidate
submission format would mix test truth into the candidate boundary and create a false claim of
external execution.

The next safe increment must accept actual candidate response data while remaining offline,
transparent, deterministic, bounded, reconstructable, and separate from scoring or identity.

## Decision

Define a dedicated extra-forbid JSON envelope containing one `AssuranceResponse` for each of
the eight transparent Type-C fixtures. It contains no expected outcome and no candidate-supplied
reference truth. The envelope binds exact artifact, protocol, conformance, reference-oracle,
and reference-report versions to local constants.

Read the source exactly once through a no-follow, regular-file-only descriptor with a 262,144
byte inclusive ceiling. Reject a UTF-8 BOM, invalid UTF-8 or Unicode scalar values, duplicate or
NFC-colliding keys, non-finite numbers, excessive nesting or strings, excessive findings or
Evidence references, malformed response models, duplicate fixtures, and any missing or extra
fixture. Validate fully before creating evidence output.

Input case order and ordinary JSON whitespace are nonsemantic. The raw SHA-256 preserves exact
source bytes; the domain-separated normalized artifact commitment uses the canonical `FIXTURES`
order. Validated `1` and `1.0` converge to the same floating-point representation under the
v0alpha1 object-canonicalization profile. That profile is not the future normative whitepaper
Evidence commitment.

Use a dedicated create-only three-file evidence bundle containing `candidate-artifact.json`,
`report.json`, and `manifest.json`. Preserve the exact source bytes. Verification must reconstruct
the normalized artifact, every candidate comparison, the summary, and the report commitment
from that exact bundled source. The existing general two-file evidence contract remains intact.

## Consequences

- A real offline candidate response set can now exercise the transparent Type-C comparator.
- Raw source identity, normalized semantic identity, and per-case candidate identity are named
  separately.
- A source byte hash proves byte identity, not miner identity, authorship, provenance, or origin.
- Limits are local ingestion-safety controls, not protocol economics or scoring policy.
- Hidden truth, semantic grading, calibration, scoring, ranking, weights, signatures, G1,
  transport, wallet, network, chain, and testnet behavior remain unimplemented and held.
