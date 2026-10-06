# AGENTS.md

Rules for agents and humans working in `sn87-provenonce`.

## Ownership

- Owner: Provenonce, Inc., under Will O'Brien, Founder & CEO. `.github/CODEOWNERS` names the reviewer.
- This repository holds protocol contracts, the reference implementation, the miner kit, public-safe
  fixtures, tests, docs and the public attestation verifier. Hidden challenge truth, validator
  scoring, the reference executors and production operations are maintained privately; do not
  add them here.
- One canonicalizer (`gra/0.1`), one profile family, one scorer, one bundle. Do not add a second.

## Run tests

```bash
uv sync --locked --all-extras
uv run python scripts/export_schemas.py --check
uv run ruff check .
uv run pytest
```

Tests that need the private reference executors skip with that reason. The signed-HTTP transport
tests need a Valkey server and run in Provenonce's private suite; the design is in
`docs/architecture/ADR-0005-signed-http-and-replay-boundary.md`.

## Data boundaries

- No private challenge truth, sealed answers or salts, Tenant Evidence, customer data, secrets,
  wallet material, keys, tokens or production topology in this repository, its history or its
  artifacts.
- Fixtures must be synthetic. Docs cite the evidence bundle, not hand-copied numbers.
- Do not state mainnet, production, performance, adoption or competition claims. Existing testnet
  rows are conformance evidence ([LIMITATIONS.md](LIMITATIONS.md)).

## Forbidden without approval from Provenonce

- Any chain, wallet, key, registration or weight-setting action, including testnet.
- Pushes to protected branches, visibility or security-setting changes, publishing.
- Changing a committed profile in place (a change is a new profile version and commitment).
- Moving or recreating a published tag.
