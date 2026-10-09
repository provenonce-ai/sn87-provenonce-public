# ADR-0019: Published truth for public fixtures, truth fixed at build time for new families

Status: accepted for the committed public fixtures. The second half is a design rule for families
not yet built; no such family exists in this repository.

## Context

The attested validator digest and the scorer tests used to need the reference executors, which are
not published, so an outsider could not check scoring: the scorer tests skipped and the verifier
ended UNVERIFIED. The executors have to stay private for hidden instances. For a family whose truth is
computed from the capsule by a reference execution, publishing the executor publishes a perfect
miner for every hidden instance.

The two things are separable. On the committed public fixtures the public-contract baseline already
reproduces the truth and scores 1, so the per-case truth of those fixtures is no secret. Only the
executors, which generalise to unseen capsules, are.

## Decision

1. Publish per-case truth for the committed public fixtures as golden vectors
   (`protocol/golden_truth/`): state and defects only, each case bound to its capsule by the
   evidence commitment recomputed from the capsule. Cover the attested seed (0) and the fixed
   fixture runs, nothing else.
2. Keep the reference executors private. A private generator writes the vectors and a private test
   regenerates and compares them, so the vectors cannot drift from the executors unnoticed.
3. The public staging validator takes its truth from the vectors when no executor is present. The
   attestation verifier always does, so the validator check recomputes the attested pinned digest
   from published truth and the public scorer: PASS if equal, FAIL if different, UNVERIFIED only
   when no truth is published for the attested seed.
4. The plan digest is not covered. It hashes a plan document built by private operator tooling
   from unpublished files, not from truth, so that check stays UNVERIFIED with that reason.
   Publishing the plan document itself is a separate decision.

## Consequences

- Public scorer tests (`tests/test_scoring_public.py`) and the attested validator digest
  (`tests/test_staging_golden.py`) run in the public tree.
- A public verifier run still ends UNVERIFIED (exit 3) because of the plan check.
- The vectors are evidence that the scorer reproduces the attested digest from this truth. They do
  not prove the truth is right where two truths score every method the same way, and they say
  nothing about hidden instances.
- Rule for later seeds: a window's truth is published only after the window is closed and its seed
  revealed, if ever. Nothing about an unrevealed seed is added to these files.

## Truth fixed at build time for new families

A new family should not need a reference execution to say what the answer is. Two ways give truth
at the moment an instance is made, so validator code can be open while instances stay hidden:

- Planted defects (oracle class Type A; the toy cases in
  [lane-one-transparent-toy.md](../simulation/lane-one-transparent-toy.md) are examples). The generator builds the instance from a
  clean base and plants a known defect, or none. The defect list is the truth, recorded by the
  generator in the same step. A validator that holds the generator output and its record scores
  responses by comparing them with the record. There is no function from capsule to truth to
  publish, so publishing the validator code does not give a miner an answer key.
- Adjudication. For instances whose truth is a judgement, the truth is fixed by a recorded
  adjudication (who decided, on what evidence, when) before scoring, and is not recomputed from the
  capsule.

For both, instances and their truth records are committed (hash) before a window and revealed after
it. The rule that follows for any new binding in `classes.py`: it must state where its truth comes
from. "A reference executor computes it from the capsule" is allowed only if that executor stays
private, and then the family's public fixtures get golden vectors as in this ADR. No new family is
built here.
