# Transparent estimator comparison

This module compares candidate component estimators without selecting a production scoring
function. It currently implements two exact estimators:

- weighted arithmetic mean; and
- weighted harmonic mean.

Each `EstimatorSpec` binds an estimator kind and positive exact component weights to one task-
profile commitment. Every external field is required, and reserved boundaries explicitly
prohibit normative scoring, winner selection, ranking, weight policy, and chain actions.
The scalar output is labeled `EXPERIMENTAL_COMPONENT_AGGREGATE`; it is not a production score.

The comparison requires at least two uniquely identified estimators bound to the same task
profile and the same exact component names. It canonicalizes estimator and component order,
uses rational arithmetic throughout, and emits no winner or preference ordering.

## Interpreting results

Arithmetic and harmonic estimates answer different experimental questions. The arithmetic
mean permits compensation between components. The harmonic mean is more sensitive to low
components and returns zero when any positively weighted component is zero. Neither behavior
is endorsed as SN87 production policy by this implementation.

The result reports boundedness, exact arithmetic, and order independence. These are software
invariants, not statistical validation, incentive calibration, or evidence of miner quality.

## Boundary

The module does not define the component set, coefficients, benchmark distribution, epoch
estimator, eligibility threshold, rank transform, weight plan, or chain action. Those choices
require separate versioned protocol and empirical evidence.
