# Provenance of First Light

First Light is the first applied SN87 weight row: run `e6ffa76e6f8a14bc0625fc2caf92e2cc`, profile
`IC-FIRST-LIGHT-MIN-1`, public testnet netuid 582, block 8,102,381, extrinsic
`set_mechanism_weights`. It is conformance evidence only ([LIMITATIONS.md](LIMITATIONS.md)).
Golden row facts: [docs/protocol/evidence-bundle.md](docs/protocol/evidence-bundle.md).

## What can be checked from this repository

- The row is public: anyone with a testnet node that serves history can read the weights uid 0
  set at block 8,102,381 and compare them with the golden row in the evidence-bundle document.
- The profile that scored it is committed in
  [src/sn87_provenonce/profiles/IC-FIRST-LIGHT-MIN-1.json](src/sn87_provenonce/profiles), and
  `profile.py` pins its commitment, so the scoring parameters cannot change without a new
  commitment.
- The later testnet runs are checked by the public verifier
  ([attestation/README.md](attestation/README.md)): `scripts/verify_attestation.py` reads the
  chain for every attested weight-set.

## What cannot

- The sealed run behind First Light (private cases, salts, signed transport receipts) is held
  privately. Replaying it, and so re-deriving the row from its inputs, is possible only at
  Provenonce.
- The scorer that produced the row has since been rebuilt into one scorer, one canonicalizer, one
  profile loader and one evidence bundle (see the
  [migration note](docs/releases/MIGRATION-scorer-rebuild.md)). The rebuilt scorer reproduces the
  same row on replay of the sealed run; that check also needs the private custody.
- The reference executors are private. The expected truth of the committed public fixtures is
  published (`protocol/golden_truth/`), but the truth behind the First Light row and for any
  hidden instance is not recomputable outside Provenonce.
