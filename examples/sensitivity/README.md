# Public sensitivity conformance vector

This directory contains one disclosed, deterministic example for the transparent sensitivity CLI.
It demonstrates contract composition and exact reconstruction; it does not recommend an estimator,
component set, weight, score, threshold, ranking, or production policy.

## Files

- `illustrative-policy-identities.json` discloses the two example-only policy-identity preimages
  and their domain-separated commitments.
- `illustrative-task-profile.json` is a canonical experimental Lane One task profile. Its policy
  bindings are `IDENTITY_ONLY`; they do not prove that any policy was applied.
- `illustrative-sensitivity-spec.json` is the exact canonical CLI input. Both estimators and their
  equal illustrative weights are intentionally disclosed and explicitly non-normative.
- `illustrative-golden.json` records the expected exact rational results and commitments.

The example uses two components and three synthetic scenarios to expose increase, decrease,
componentwise dominance, and a tradeoff where the illustrative estimators move in different
directions. That disagreement is observable sensitivity, not a preference or winner.

## Run

```bash
uv run sn87-provenonce analyze-sensitivity \
  examples/sensitivity/illustrative-sensitivity-spec.json
uv run sn87-provenonce analyze-sensitivity \
  examples/sensitivity/illustrative-sensitivity-spec.json \
  --output-dir ./evidence/illustrative-sensitivity
uv run sn87-provenonce verify-sensitivity-bundle \
  ./evidence/illustrative-sensitivity
```

The repository test suite verifies the disclosed policy-identity preimages, canonical profile and
specification bytes, profile-to-spec commitment, complete golden result, CLI output, create-only
bundle, and reconstruction result.
