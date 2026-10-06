# ADR-0008: Compare candidate Differentials without importing scoring

**Status:** Accepted for transparent local conformance

**Date:** 2026-09-04

**Decider:** Will O'Brien, Provenonce Founder & CEO

## Context

The SN87 protocol specification defines a Type-C rule as comparison of a miner response with a reference
execution on held-out or generated inputs. ADR-0007 implements and cross-checks only the
transparent reference-oracle side. Calling reference agreement complete Type-C evaluation
would exceed the implementation.

The next safe slice must prove candidate comparison mechanics without importing hidden truth,
settling the whitepaper's scoring mathematics, or coupling local conformance to transport,
identity, wallets, chain behavior, or testnet configuration.

## Decision

Add a pure deterministic comparator between a typed `AssuranceResponse` and one transparent
reference-oracle fixture. The comparator emits named booleans and failures, never a scalar
score. A pass requires exact protocol, challenge, state, finding-type cardinality, unique
finding identity, Type-C oracle, and fixture-Evidence binding.

Defensively serialize and revalidate every supplied `AssuranceResponse` at the candidate-case
boundary. Runtime type identity alone is insufficient because unchecked model-copy operations
can construct an instance whose nested fields violate the declared model invariants.

Exercise that comparator with a versioned corpus containing both known-pass and known-fail
candidates. Commit each complete candidate Differential and the complete report with separate
domains. Bind the report to the exact reference-oracle report commitment and every fixture
input commitment. Evidence verification reconstructs and reruns the entire corpus and rejects
any self-consistent alternative report.

Natural-language semantic quality, severity, confidence calibration, counterfactual utility,
signatures, hidden truth, scoring, ranking, and weights are explicit non-checks. They cannot be
inferred from conformance.

## Options considered

### Named pass/fail checks: selected

This exposes precisely why a candidate passes or fails and avoids inventing a normative score.

### Reuse the transparent toy scoring constants

Rejected. Those constants are local architecture demonstrations and are not approved Type-C
evaluation parameters.

### Accept reference agreement as candidate conformance

Rejected. Reference agreement establishes oracle consistency, not miner-response quality.

### Load hidden or Foundry fixtures now

Rejected. Hidden truth, custody, leakage controls, and G1 acceptance remain held.

## Consequences

- The transparent Type-C path now contains both a reference oracle and an explicit candidate
  comparison boundary.
- False negatives, false positives, abstention, wrong binding, duplicate claims, incompatible
  versions, and wrong oracle class are executable negative controls.
- The output is auditable conformance evidence, not a score or benchmark result.
- External candidate ingestion is outside this decision and is governed separately by
  ADR-0009. Signatures, operationally independent references, hidden fixtures, calibration,
  and G1 require separate bounded work and evidence.
- No network, wallet, chain, testnet, Foundry, Operations, publication, or launch path is added.
