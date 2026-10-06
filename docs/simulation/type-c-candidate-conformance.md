# Transparent Type-C candidate conformance

This deterministic local runner implements the comparison step that the whitepaper's Type-C
definition requires: a typed candidate Assurance Differential is compared with the outcome of
the transparent reference oracle. It is public-safe software conformance, not hidden benchmark
evaluation, calibrated scoring, or G1 evidence.

## Machine-checkable contract

For every candidate and fixture pair, the runner checks:

1. the candidate uses protocol version `sn87/0alpha1`;
2. the candidate challenge identity equals the fixture identity;
3. every nested finding challenge identity equals the response challenge identity;
4. the candidate response state equals the independently agreed reference state;
5. candidate finding types exactly equal the sorted reference defect codes, including
   cardinality;
6. finding identities are unique;
7. every finding declares Type C as its oracle class; and
8. every finding contains exactly one Evidence reference bound to the fixture input commitment
   under predicate `type_c_fixture_input`.

The boundary defensively serializes and revalidates every supplied `AssuranceResponse`, even if
the object was copied through a mechanism that bypasses normal model validation. The response
models reject structurally invalid Differentials. The runner does not
judge natural-language claim quality, confidence calibration, severity calibration,
counterfactual utility, or miner signatures. Those non-checks are explicit in the committed
report.

## Versioned candidate corpus

The transparent corpus contains one conformant candidate for each of the eight reference-oracle
fixtures and nine adversarial candidates:

- false negative on a planted defect;
- false positive on a clean control;
- indiscriminate abstention despite complete disclosed Evidence;
- wrong defect code;
- wrong Evidence commitment;
- wrong challenge identity;
- duplicate finding type;
- incompatible protocol version; and
- wrong oracle class.

The report succeeds only when every conformant candidate passes and every adversarial candidate
fails for its disclosed reason. It emits no scalar score, rank, calibration result, or weight.
The report also records the exact reference-oracle report commitment and each fixture input
commitment, so version labels cannot conceal corpus drift.

## Run it

```bash
uv run sn87-provenonce conform-type-c-candidates
uv run sn87-provenonce conform-type-c-candidates \
  --output-dir ./evidence/type-c-conformance-001
uv run sn87-provenonce verify-type-c-conformance-bundle \
  ./evidence/type-c-conformance-001
```

Bundle creation is create-only and descriptor-anchored. Verification retains the directory and
both bounded regular-file descriptors through complete opening and closing snapshots. It checks
exact membership, stable raw report bytes, the domain-separated report commitment, every
boundary, and full equality with a freshly reconstructed and re-executed versioned corpus.

## Claim boundary

The report declares
`IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_CANDIDATE_CONFORMANCE_ONLY`. It contains no hidden truth,
normative scoring, ranking, weight planning, network access, wallet access, chain submission,
testnet activity, or production Evidence. Passing the corpus does not establish miner quality,
rank stability, economic value, or G1 acceptance.

ADR-0009 and `type-c-offline-candidate-artifact.md` define the separate external-data boundary.
That boundary deliberately excludes this harness's known pass/fail expectations.
