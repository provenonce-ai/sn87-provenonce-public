# ADR-0011: Compare estimators without selecting production policy

**Status:** Accepted

**Date:** 2026-09-04

**Deciders:** Will O'Brien, Provenonce Founder & CEO; SN87 protocol maintainer

## Context

Component measurement and committed task profiles make candidate aggregation behavior
testable. Selecting one aggregation rule prematurely would turn an experiment into incentive
policy without distributional, adversarial, calibration, or rank-stability evidence.

## Decision

Provide an exact comparison harness for weighted arithmetic and weighted harmonic estimators.
Every estimator is a complete, versioned artifact bound to one task-profile commitment. A
comparison accepts only estimators with unique IDs, the same task-profile commitment, and an
exact match between component values and configured weight names.

The result must be deterministic under estimator and component reordering. It must expose the
complete specifications, exact component vector, exact estimates, and domain-separated
commitments. It must not select a winner, create a rank, define production scoring, produce a
weight plan, or expose a chain action.

## Consequences

- Candidate aggregation behavior can be exercised and reproduced before policy selection.
- Compensating and low-component-sensitive behavior can be compared explicitly.
- Coefficients remain experiment inputs rather than protocol constants.
- Statistical selection, benchmark calibration, epoch aggregation, and incentive policy remain
  separate future decisions.
