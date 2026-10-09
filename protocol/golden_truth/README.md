# Golden truth for the committed public fixtures

Per-case agreed truth (`state` and `defects`, the two fields the scorer reads) for the capsules
that the public generators build at fixed identifiers and seeds. With these files the public scorer
can be run, and the attested validator digest recomputed, without a reference executor.

| File | Class | Cases |
| --- | --- | --- |
| `ic_fixture_set.json` | `IC-APPROVAL-APPLICABILITY` | the profile's full fixture run (also the attested validator's seed-0 instances) and the three default-identifier capsules |
| `type_c_fixture_set.json` | `TYPE-C-RELEASE` | the profile's full fixture run and the eight default-identifier capsules built from the public Type C fixtures |
| `oracle/type_c_reference_oracle.json` | Type C | the transparent reference-oracle report; its commitment is pinned in `simulation/type_c_candidate_artifact.py` |

Each case is bound to its capsule by the capsule's evidence commitment, which
`scripts/golden_truth.py` recomputes from the capsule content. A capsule that is not listed has no
published truth and the loader refuses to guess. Each file carries `set_digest`, a SHA-256 over its
canonical JSON without that field.

Check them: `uv run python scripts/golden_truth.py`, `uv run pytest tests/test_golden_truth.py`.
Use them: `uv run python scripts/staging_subnet.py --out DIR --truth golden`, or
`uv run --extra transport python scripts/verify_attestation.py`.

## What these files are not

- They hold no hidden instance. Only seed 0 (the attested validator seed) is covered. Later
  windows draw fresh instances, and their truth is not published.
- They contain no reference executor code and no rule for deriving truth. The executors stay
  private: for a family whose truth is computed from the capsule, an executor is a perfect miner
  on hidden instances.
- The `set_digest` is tamper evidence, not proof. The evidence that this truth is the truth the
  validator used is that the scorer, fed with it, reproduces the attested validator digest.

## Rule for hidden windows

Seed 0 is the only seed published, and the committed public generator is the only generator whose
output is covered. A run for a hidden window must use fresh seeds and a non-public instance
generator, never seed 0 and never the committed public generator for non-public windows. No script
in this repository generates a hidden-window run; any script added for that must refuse seed 0 and
the public generator. Truth for a window is published only after the window closes and its seed is
revealed.

## Regenerating

The files are written by a generator script that calls the private reference executors and is
not part of the public tree. A private test regenerates them and compares, so a
change to an executor, a generator, a profile or the scorer cannot silently move the truth.
Contributions should not edit these files by hand.
