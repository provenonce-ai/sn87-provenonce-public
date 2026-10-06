# Transparent sensitivity analysis

This module makes experimental estimator behavior inspectable without choosing an SN87
production-scoring policy. A strict `SensitivityAnalysisSpec` binds:

- one task-profile commitment;
- one or more versioned estimator specifications;
- one disclosed baseline component vector; and
- one or more disclosed scenario vectors with exactly the same component names.

The analysis uses exact rational arithmetic. For each estimator and scenario it reports the
estimate, signed delta from the baseline, direction of change, and exact set of changed
components. Inputs are canonicalized by identifier and component name, and the specification
and result are domain-separated and self-committing. Cardinality is bounded to 16 estimators,
256 scenarios, and 64 components per vector. The JSON ingress is limited to 1,000,000 bytes,
identifiers are length-bounded, and integers within an analysis are limited to 4,096 bits.

## Componentwise relations

Every unique pair of disclosed vectors receives one descriptive relation:

- left componentwise dominates;
- right componentwise dominates;
- componentwise equal; or
- componentwise incomparable.

Here, dominance means only that every component value on one disclosed vector is at least the
corresponding value on the other, with at least one strict improvement. It does not mean that a
miner, estimator, strategy, or policy wins. The module produces no total ordering and does not
convert these relations into ranks or weights.

## Boundary

The output semantics are `DESCRIPTIVE_ESTIMATOR_SENSITIVITY`. Every external specification
explicitly sets production-policy selection, normative scoring, winner selection, ranking, and
chain action to false; estimator preference and weight policy are also explicitly undefined. The
analysis does not establish coefficients, benchmark distributions,
calibration thresholds, epoch aggregation, incentive compatibility, G1 acceptance, or testnet
readiness.
