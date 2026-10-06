# ADR-0010: Bind Lane One measurement to versioned task profiles

**Status:** Accepted

**Date:** 2026-09-04

**Deciders:** Will O'Brien, Provenonce Founder & CEO; SN87 protocol maintainer

## Context

Transparent component measurement is useful before SN87 has selected a production scoring
function. Without an explicit task profile, however, a result cannot prove which components,
matching rule, severity policy, false-positive policy, calibration policy, or exact F-beta
parameter produced it. Function defaults are insufficient as a durable evaluation contract.

The configuration boundary must support reproducible experiments without becoming a route for
silently introducing composite scoring, epoch aggregation, eligibility thresholds, ranking,
weights, or chain behavior.

## Decision

Every Lane One component-measurement run must accept a `LaneOneTaskProfile` and embed both its
canonical payload and domain-separated commitment in the result.

A profile must declare:

1. its profile and challenge-class versions;
2. the exact enabled component set;
3. the one-to-one reference-matching policy;
4. identifiers and commitments for the upstream severity and false-positive policies;
5. a positive exact rational beta-squared value when F-beta detection is enabled; and
6. an identifier and commitment for the upstream calibration policy when Brier calibration
   is enabled.

Policy bindings establish configuration identity only. The component calculator does not
prove that an upstream fixture generator or assessor applied the bound policy correctly.

Component order is canonicalized, and exact ratios are reduced before commitment. Artifact
parsing rejects duplicate JSON keys, missing fields, extra fields, unknown enum values, and any
attempt to set a reserved scoring or chain boundary to true.

The profile format explicitly fixes the following fields to false:

- normative scoring;
- composite definition;
- epoch-estimator definition;
- eligibility-threshold definition;
- ranking definition;
- weight-policy definition; and
- chain-action definition.

## Consequences

- Component results can be reproduced against an exact configuration identity.
- Partial configurations fail before measurement.
- Only enabled components appear in the result.
- Future scoring experiments can compare committed profiles without misrepresenting them as
  production incentive policy.
- A production scoring function requires a separate versioned contract and decision.
