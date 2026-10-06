# Lane One transparent component measurement

This module closes three concrete measurement exploits without selecting SN87's normative
scoring function:

- each planted defect can match at most one finding;
- every duplicate, missing, or unknown defect reference becomes a false positive; and
- false-positive cost is the maximum of a positive floor, claimed cost, and a sealed
  rule-based assessment, so understating severity cannot erase the cost.

The calculator uses exact rational arithmetic for precision, recall, F-beta detection,
Evidence quality, and Brier calibration quality. Every run includes the complete versioned
task profile and its commitment. Only components named by that profile appear in the result.
The report explicitly states that no clean-control penalty function, composite, epoch
estimator, ranking, weight plan, or chain behavior has been defined.

## Task profiles

A `LaneOneTaskProfile` binds the run to:

- a profile, challenge class, and challenge-class version;
- the enabled measurement components;
- an exact one-to-one matching policy;
- identifiers and commitments for the upstream severity and false-positive policies;
- an exact F-beta parameter when detection is enabled; and
- an identifier and commitment for the upstream calibration policy when Brier calibration is
  enabled.

Policy bindings identify the rules that produced the supplied measurement inputs. This module
does not prove that an upstream system applied those rules correctly.

## Example

```python
from sn87_provenonce.protocol.v0alpha1 import ResponseState, canonical_sha256
from sn87_provenonce.simulation import (
    ExactRatio,
    FindingClaim,
    MeasurementComponent,
    PlantedDefect,
    PolicyBinding,
    create_lane_one_task_profile,
    measure_lane_one_case,
)

severity_rule = {"critical": 100, "major": 40}
false_positive_rule = {"minimum_cost_units": 5}

profile = create_lane_one_task_profile(
    profile_id="lane-one-transparent-example",
    challenge_class="LANE_ONE",
    challenge_class_version="0alpha1",
    enabled_components=(
        MeasurementComponent.SEVERITY_WEIGHTED_PRECISION,
        MeasurementComponent.SEVERITY_WEIGHTED_RECALL,
        MeasurementComponent.F_BETA_DETECTION,
    ),
    severity_policy_binding=PolicyBinding(
        identifier="example-severity/0alpha1",
        commitment=canonical_sha256(
            severity_rule, domain="SN87:EXAMPLE_SEVERITY_POLICY:v0alpha1"
        ),
    ),
    false_positive_policy_binding=PolicyBinding(
        identifier="example-false-positive/0alpha1",
        commitment=canonical_sha256(
            false_positive_rule,
            domain="SN87:EXAMPLE_FALSE_POSITIVE_POLICY:v0alpha1",
        ),
    ),
    minimum_fp_cost_units=5,
    beta_squared=ExactRatio(numerator=1, denominator=1),
)

result = measure_lane_one_case(
    profile=profile,
    response_state=ResponseState.FINDINGS,
    planted_defects=(PlantedDefect("defect-1", severity_units=100),),
    claims=(
        FindingClaim(
            claim_id="finding-1",
            defect_ref="defect-1",
            claimed_fp_cost_units=5,
            evidence_valid=True,
            confidence_bps=9000,
        ),
    ),
)
```

The result contains the exact profile payload, its commitment, raw matched/unmatched totals,
the three enabled components, and the measurement commitment. It contains no composite score.

Profiles are canonicalized before commitment, so component order and reducible exact ratios
cannot create distinct identities for equivalent configurations. Invalid partial
configurations fail at construction.

The module preserves the three canonical response states. `NO_MATERIAL_DEVIATION` on a clean
control is distinct from `INSUFFICIENT_EVIDENCE_ABSTAIN`; abstention receives no detection
credit and is not silently converted into a correct negative.

## Boundary

This is a transparent implementation and test instrument. It is not a calibrated scoring
policy, protected benchmark truth, or testnet behavior. Numeric severity schedules, semantic
matching equivalence classes, clean-control penalties, composite weights, epoch estimators,
eligibility thresholds, ranking transforms, and chain policies are outside this interface.
