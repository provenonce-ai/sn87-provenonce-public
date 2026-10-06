# ADR-0012: Describe estimator sensitivity without ranking

- Status: Accepted
- Date: 2026-09-04

## Context

Transparent estimator candidates can be compared mechanically, but a comparison alone does not
show how their outputs respond to disclosed component changes. Selecting an estimator before
that behavior is visible would embed a difficult-to-revise policy choice in implementation.

## Decision

SN87 will provide an exact, non-normative sensitivity layer before any production estimator is
selected. The layer binds a baseline and scenarios to versioned estimator specs and one committed
task profile. It reports exact baseline deltas and pairwise componentwise relations.

Componentwise dominance is strictly a relation between disclosed component vectors. It does not
select a winner, rank a miner, endorse an estimator, infer a scoring policy, or authorize a chain
action. All input and output order is canonical, all arithmetic is rational, and the analysis is
self-committing. Input cardinality, JSON byte length, identifier length, and integer bit length
are bounded so pairwise analysis has a predictable maximum workload.

## Consequences

- Estimator tradeoffs can be inspected and reproduced before protocol policy is fixed.
- Compensability and low-component sensitivity remain visible rather than implicit.
- The analysis can identify incomparable vectors without forcing a total order.
- Production estimator selection, coefficients, thresholds, epochs, rankings, and weights remain
  unresolved and require separate evidence and a separate decision by Provenonce.
