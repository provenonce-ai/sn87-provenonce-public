# Contributing

SN87 is alpha protocol software on public testnet netuid 582; results so far are conformance
evidence only (see [LIMITATIONS.md](LIMITATIONS.md)). Contributions must preserve these rules:

1. Source precedes synthesis; label proposals and unresolved behavior explicitly.
2. Do not weaken schema, Evidence, response-state, privacy, or integrity invariants for convenience.
3. Do not add secrets, raw Tenant Evidence, hidden challenge instances, production topology, or proprietary runtime code.
4. Add or update conformance tests and traceability for every protocol change.
5. Keep the full history safe for public reading.
6. Do not claim mainnet, production, performance, adoption, or universal assurance without direct evidence and approval.

## Development setup

```bash
uv sync --locked --all-extras   # Python 3.12+, versions pinned by uv.lock
uv run ruff check .
uv run pytest -q                # tests that need the private reference executors skip
```

Scoring has one scorer, one canonicalizer and one profile loader (`scoring.py`, `canonical.py`,
`profile.py`); a new task family is a new `ClassBinding` in `classes.py`, never a new scorer, and
scorers carry no default parameters ([migration note](docs/releases/MIGRATION-scorer-rebuild.md)).
Cost coefficients stay 0 until Provenonce approves a profile that activates them. New files must
be classified in `PUBLIC_MANIFEST.json` (deny > private > review_required > allow);
`scripts/check_manifest.py` checks this and runs in CI.

Changes to protocol objects or canonical bytes require an accepted architecture decision and new
reference vectors. Scoring parameters live only in committed profiles; a change is a new profile
version, never hidden configuration ([profile application](docs/protocol/profile-application.md)).
No chain or wallet writes without approval from Provenonce.

## Pull requests

1. Fork the repository and branch from `main`.
2. Make the change with its test; run `uv run ruff check .` and `uv run pytest` (both must pass).
3. Open a pull request that says what changed and why. There is no sign-off or CLA step; by
   contributing you agree your change is under the MIT License. Maintainers review for the rules
   above, and CI must be green.

## Good first issues

- Add a second worked example to `docs/quickstart/miner.md` that sends
  `build_case("fresh_review")` to the localhost server, and record the response you get.
- Add miner test vectors: a capsule whose evidence commitment is broken, and the exact 4xx the
  localhost server (`scripts/miner_serve.py`) returns for it, in `tests/test_miner_serve.py`.
- Add filtering to the `--json` output of `scripts/verify_attestation.py` (for example only the failing or
  unverified runs) with a test in `tests/test_verify_attestation_public.py`.
- Add a `--run RUN_ID` option to the verifier that checks one attested run, with a test.
- Fill gaps in `docs/protocol/v0alpha1-field-traceability.md` where a field names no test.
