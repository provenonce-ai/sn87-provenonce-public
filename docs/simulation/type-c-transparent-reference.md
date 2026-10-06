# Transparent Type-C reference oracle

This executable local simulation implements only the reference-oracle side of the whitepaper's
Type-C concept without creating sealed benchmark truth. It does not yet compare a candidate
miner Differential with the reference outcome. It evaluates a synthetic release workflow through two
independently coded reference implementations:

- an incremental state machine; and
- a relational evaluator over indexed event positions.

Both references evaluate the complete outcome: response state plus sorted defect codes. Any
disagreement fails closed and prevents report generation.

The local reference contract requires exactly one `SUBMIT`, `REVIEW`, `VALIDATE`, and `RELEASE`
in that order. The review must be approved, the release must be terminal, and commitments must
form a contiguous chain. `OBSERVE` is the only optional event and is permitted only after
submission and before release. This grammar is a transparent fixture-local contract, not a
claim that every production workflow must use these event names.

## Run it

```bash
uv run sn87-provenonce simulate-type-c-reference
uv run sn87-provenonce simulate-type-c-reference \
  --output-dir ./evidence/type-c-run-001
uv run sn87-provenonce verify-type-c-bundle ./evidence/type-c-run-001
```

Bundle creation is create-only and descriptor-anchored. The verifier retains the directory and
both bounded regular-file descriptors through complete opening and closing snapshots. It rejects
links, path substitution, membership changes, concurrent mutation, changed report bytes,
claim-state drift, and semantic-commitment drift. It also independently
enforces the transparent operational boundary, reconstructs every fixture from its disclosed
events, and reruns both reference algorithms. It rejects a self-consistent report that enables
hidden fixtures, scoring, networking, chain submission, production evidence, or fabricated or
disagreeing reference results.

## Transparent fixtures

The committed public-safe corpus contains:

| Fixture | Expected state | Reference truth |
|---|---|---|
| Clean control | `NO_MATERIAL_DEVIATION` | No defect |
| Deleted review event | `FINDINGS` | `MISSING_REVIEW_GATE` |
| Equivalent no-op mutation | `FINDINGS` | Preserves `MISSING_REVIEW_GATE` |
| Substituted review input | `FINDINGS` | `EVIDENCE_CHAIN_BREAK` |
| Redacted required events | `INSUFFICIENT_EVIDENCE_ABSTAIN` | Evidence explicitly incomplete |
| Deleted submit event | `FINDINGS` | `MISSING_SUBMIT_EVENT` |
| Submit/validation kind swap | `FINDINGS` | `INVALID_WORKFLOW_ORDER` |
| Inserted duplicate submit | `FINDINGS` | `DUPLICATE_SUBMIT_EVENT` |

Every fixture records its source fixture, executable mutation operator, expected invariant,
exact event data, and a canonical input commitment. The corpus is built by applying those
operators, and report generation replays each source-to-mutant derivation. The equivalent
mutation inserts an observation that does not alter workflow state, testing that superficial
sequence changes do not erase the material missing-review result.

## Claim boundary

The report declares `IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_REFERENCE_ORACLE_ONLY`. All inputs and expected
outcomes are public and deterministic. It performs no miner scoring, ranking, weight planning,
network access, model inference, wallet access, chain submission, production assurance, or
hidden evaluation. Passing it is software conformance, not G1 evidence or proof that Lane One
will outperform a baseline.
