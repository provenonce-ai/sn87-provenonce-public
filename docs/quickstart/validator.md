# Validator quickstart (draft)

**Draft.** Target: public testnet netuid 582, alpha protocol, conformance evidence only
([LIMITATIONS.md](../../LIMITATIONS.md)). This repository holds the validator-side contracts and
the public checks. The per-case truth of the committed public fixtures is published, so the public
scorer and the staging validator run against it here. The reference executors that compute truth
for any capsule are private, so a validator for hidden instances cannot be run from this
repository alone: it also needs a source of truth for those instances, which is an open decision.
Today a third party can run these here: the staging validator on the public fixtures, scoring of a
miner response on a public fixture against the published truth, recomputation of the attested
validator digest, and the verifier. Nothing here
registers, stakes or sets weights.

## What a validator does

Dispatches capsules, integrity-gates responses (schema, policy, signature, nonce, evidence,
deadline), scores them with the one scorer under the committed profile, and forms a weight row or
`NO_VALID_PREFERENCE_ROW`. Evaluation fails closed (`PROFILE_NOT_APPLIED`) if the run's profile
commitment differs from the profile used ([profile application](../protocol/profile-application.md)).

## Install

```bash
git clone <this repository> sn87-provenonce && cd sn87-provenonce
uv sync --locked --all-extras          # Python 3.12 or later; versions pinned by uv.lock
uv run pytest
```

The signed transport (`src/sn87_provenonce/pilot/`) needs the `transport` extra and, for replay
protection, a Valkey-compatible server that runs `maxmemory-policy noeviction` and is dedicated to
it; the client checks that on every admission. The design is in
[ADR-0005](../architecture/ADR-0005-signed-http-and-replay-boundary.md).

## Score against the published truth

`protocol/golden_truth/` holds the agreed truth of the committed public fixtures, each case bound
to its capsule by the capsule's evidence commitment ([README](../../protocol/golden_truth/README.md)).
The staging validator runs one validator and two in-process miners on the 16 public instances of
seed 0, scores them with the one scorer and quantizes the row, with no network and no chain:

```bash
uv run python scripts/staging_subnet.py --out /tmp/staging-run --truth golden
```

It prints the receipt's pinned digest. For seed 0 that digest equals the validator pinned digest in
every attested run. `tests/test_scoring_public.py` runs the scorer on the same truth. To use the
truth in your own validator code, `scripts/golden_truth.py` loads the files and
`GoldenTruth.truth_for(capsule)` returns the truth of a listed capsule or raises.

What this covers: those fixtures only. A capsule that is not listed has no published truth, and
only seed 0 is published: later windows draw fresh instances whose truth is not.

## Check what a validator already did

The public verifier re-reads the chain and compares every attested weight-set with what the chain
recorded (no wallet, no key):

```bash
uv run --extra transport python scripts/verify_attestation.py
```

It recomputes the validator pinned digest of every attested run from the published truth and the
public scorer: PASS if equal, FAIL if different. It cannot recompute the plan digest, which covers
a plan document built by private operator tooling, so the plan check and the overall verdict are
UNVERIFIED (exit 3) outside Provenonce. See [attestation/README.md](../../attestation/README.md)
for what each check proves and what it does not.

## Dry run (no wallet, no broadcast)

`src/sn87_provenonce/weights_dry_run.py` quantizes a preference row to u16 weights against explicit
target constraints and never broadcasts. Check that an evidence bundle's `mode` is `FIXTURE` or
`REPLAY`, not `LIVE` ([evidence bundle](../protocol/evidence-bundle.md)).

## Setting weights

Plain weight mode only (commit-reveal is off on the testnet target; the commit-reveal path is tested against a fake chain and has no submitter, see [second-validator readiness](../protocol/second-validator-readiness.md)). Applying
a row is an operator chain action requiring your own validator hotkey, permit and an explicit
approval; this document does not perform or authorize it. Integrity predicates for authenticated
runs come from a private harness that is not in this repository.

## What remains private

- The reference executors, which compute truth for any capsule and are the answer key for hidden
  instances. Their SHA-256 commitments are in the README.
- The plan document and the operator tooling that builds it.
- The truth of every instance other than the committed public fixtures at seed 0.

For new families the design rule is that truth is fixed when the instance is built, so that
validator code can be open while instances stay hidden:
[ADR-0021](../architecture/ADR-0021-published-truth-for-public-fixtures.md).

## Resources

No resource numbers are published here; Provenonce's local measurements are kept in private
records. Not measured: disk, bandwidth, chain round-trip time, end-to-end validator round time and
concurrency.
