# ADR-0002: Build transparent local simulation before hidden benchmark supply

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** Will O'Brien, Provenonce Founder & CEO; SN87 protocol maintainer

## Context

The protocol contract can support executable development before the final whitepaper locks
scoring semantics and before the private Benchmark Foundry is authorized. Waiting would leave
important seams untested. Creating plausible hidden truth or presenting draft scoring as
normative would cross the repository boundary and make weak assumptions durable.

## Decision

Implement a transparent, deterministic toy simulation inside `sn87-provenonce`. Reuse the
v0alpha1 Differential model; exercise planted-defect, clean-control, equivalent-mutation, and
insufficient-Evidence states; preserve an explicit no-valid-weight-row result; and emit a
self-committed report. Keep all score constants under the simulation namespace and label them
local, provisional, and non-normative.

The simulation must not contain hidden fixtures, production Evidence, external model calls,
network traffic, wallets, chain submission, or a claim of benchmark validity. Protocol-release
dependencies remain absent rather than guessed.

## Options considered

- Wait for final canon: rejected because protocol-model integration, deterministic reporting,
  failure behavior, and test architecture can be validated now.
- Put toy cases in the private foundry: rejected because that would initialize a held control
  plane and confuse transparent examples with renewable hidden truth.
- Implement provisional chain transport: rejected because package/runtime pins, identity,
  target configuration, credentials, and transaction authority remain unresolved.

## Consequences

- Local code can now produce and test a complete request-adjacent evaluation report.
- Scoring and normalization mechanics can change without migrating the v0alpha1 protocol.
- Passing results establish software behavior only; they do not establish benchmark quality,
  incentive calibration, testnet readiness, or production assurance.
- The next safe build slices are a validator dry-run boundary and local miner/validator
  process seams, provided neither introduces held truth, transport, or chain choices.
