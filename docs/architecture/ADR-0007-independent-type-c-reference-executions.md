# ADR-0007: Require independent executions for the Type-C reference oracle

**Status:** Accepted for transparent local fixtures

**Date:** 2026-09-03

**Decider:** Will O'Brien, Provenonce Founder & CEO

## Context

The SN87 protocol specification defines Type C as comparison against a reference execution on held-out or
generated inputs. It also states the central risk: a reference implementation can silently
become centralized product truth. The reference must therefore be inspectable after reveal,
and multiple implementations should be possible where feasible.

SN87 needs executable Type C architecture before sealed benchmark creation, but public code
must not expose future hidden truth or imply that one implementation proves semantic
correctness. A single reference could faithfully reproduce its own defect.

## Decision

For transparent local Type-C reference-oracle fixtures, require at least two named, independently structured
reference executors. Compare their complete outputs, not only their top-level response state,
and fail closed if any response state or defect code differs.

The first bounded fixture family is a synthetic release workflow. One executor uses an
incremental state machine; the other derives results from event-position relations. Shared
data models and stable defect-code names are allowed, but the algorithms do not call each
other or a shared evaluation helper.

The fixture-local grammar requires exactly one `SUBMIT`, `REVIEW`, `VALIDATE`, and `RELEASE`
in that order; an approved review; a terminal release; and a contiguous commitment chain.
Optional `OBSERVE` events are allowed only between submission and release. Each reference must
enforce the grammar independently so agreement cannot hide a shared omitted rule.

Every fixture must record:

1. a unique fixture and event identity;
2. complete public-safe input events;
3. whether Evidence is complete;
4. source fixture, executable mutation operator, and expected invariant;
5. a domain-separated canonical input commitment; and
6. both reference results plus the agreed outcome.

The corpus must be constructed from its baseline through the declared mutation operators, and
report generation must replay every derivation. Invalid commitments, duplicate event IDs,
invalid approval placement, missing provenance, too
few executors, duplicate executor names, and reference disagreement fail before a report can
be emitted. Generated reports use a separate domain and create-only evidence-bundle version.

## Options considered

### Two structurally independent reference implementations: selected

This makes correlated implementation error less likely and turns disagreement into visible
evidence rather than silently selecting one answer.

### One canonical reference implementation

Rejected as the only control. It is simpler but cannot distinguish a correct result from a
self-consistent implementation defect.

### Majority vote across many similar implementations

Deferred. More implementations add cost without independence if they share the same logic or
origin. Independence and complete-output comparison matter more than raw implementation count.

### Use miner consensus as reference truth

Rejected. Miner agreement is an observation to score or investigate; it is not Type C ground
truth.

## Consequences

- The Type-C reference-oracle architecture is executable and inspectable before sealed benchmark work.
- Equivalent mutations carry executable, replay-validated provenance and an invariant to test.
- This decision does not implement Type C end to end: candidate miner Differential comparison remains pending.
- Reference disagreement becomes a hard failure instead of an averaged result.
- Adding a future sealed fixture requires separate Foundry custody, reveal, audit, and
  protected benchmark policy; this public corpus cannot substitute for it.
- This decision adds no scoring constants, network transport, wallet, testnet, or chain path.
