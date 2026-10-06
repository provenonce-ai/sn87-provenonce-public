# Validator quickstart (draft)

**Draft.** Target: public testnet netuid 582, alpha protocol, conformance evidence only
([LIMITATIONS.md](../../LIMITATIONS.md)). This repository holds the validator-side contracts and
the public checks; validator scoring and the reference executors that compute the expected truth
are private, so a complete validator cannot be run from this repository alone. Nothing here
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

## Check what a validator already did

The public verifier re-reads the chain and compares every attested weight-set with what the chain
recorded (no wallet, no key):

```bash
uv run --extra transport python scripts/verify_attestation.py
```

See [attestation/README.md](../../attestation/README.md) for what it proves.

## Dry run (no wallet, no broadcast)

`src/sn87_provenonce/weights_dry_run.py` quantizes a preference row to u16 weights against explicit
target constraints and never broadcasts. Check that an evidence bundle's `mode` is `FIXTURE` or
`REPLAY`, not `LIVE` ([evidence bundle](../protocol/evidence-bundle.md)).

## Setting weights

Plain weight mode only (commit-reveal is off on the testnet target and not implemented). Applying
a row is an operator chain action requiring your own validator hotkey, permit and an explicit
approval; this document does not perform or authorize it. Integrity predicates for authenticated
runs come from a private harness that is not in this repository.

## Resources

No resource numbers are published here; Provenonce's local measurements are kept in private
records. Not measured: disk, bandwidth, chain round-trip time, end-to-end validator round time and
concurrency.
