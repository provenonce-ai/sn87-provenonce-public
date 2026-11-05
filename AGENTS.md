# AGENTS.md

Rules for agents and humans working in `sn87-provenonce`.

## Ownership

- Owner: Provenonce, Inc., under Will O'Brien, Founder & CEO. `.github/CODEOWNERS` names the reviewer.
- This repository holds protocol contracts, the reference implementation, the miner kit, public-safe
  fixtures, tests, docs, the one scorer (`scoring.py`), the committed profiles, the signed
  transport, the published truth of the public fixtures and the public attestation verifier.
  Hidden challenge truth, the reference executors (the code that computes expected truth for
  hidden instances) and operator tooling are maintained privately; do not add them here.
- One canonicalizer (`gra/0.1`), one profile family, one scorer, one bundle. Do not add a second.

## Run tests

```bash
uv venv
uv pip install --require-hashes -r requirements/build.txt
uv sync --locked --all-extras --no-build-isolation-package sn87-provenonce
uv run --no-sync python scripts/export_schemas.py --check
uv run --no-sync ruff check .
uv run --no-sync pytest
uv build --wheel --build-constraints requirements/build.txt --require-hashes
```

The build environment (hatchling, `editables` and their dependencies) is hash-pinned in
`requirements/build.txt`, generated from `requirements/build.in`. A change to the hatchling pin in
`pyproject.toml` updates both files in the same commit.

This is the locked developer route, and CI and the exported workflow use it for every sync and run
step (a test checks that). It closes the gap that `uv sync` and
`uv run` build the project (editable) in an isolated environment that uv resolves itself, and uv
has no hash-checked build constraint for that (`UV_BUILD_CONSTRAINT` with wrong hashes and
`UV_REQUIRE_HASHES=1` still synced). The route removes uv's build environment from the picture:

1. `uv pip install --require-hashes -r requirements/build.txt` installs the build backend into the
   project environment and fails on any hash mismatch (a tampered hash was tested: the install
   fails with `Hash mismatch for hatchling==1.33.0` and no backend is installed).
2. `--no-build-isolation-package sn87-provenonce` makes `uv sync` build the project with that
   installed backend. Without step 1 the sync fails (`No module named 'hatchling'`), so the route
   fails closed. The runtime dependencies are pinned and hashed by `uv.lock`.
3. `uv run --no-sync` runs in the synced environment and never rebuilds the project with an
   isolated build. A plain `uv run` would re-sync without the flag.
4. `uv build` is separate and unchanged: its build constraint is verified by `--require-hashes`.
   Do not set `no-build-isolation-package` in `pyproject.toml`: it would also apply to `uv build`
   (which then fails to find hatchling) and to every plain `uv sync` in the README and guides.

Remaining gap: the plain `uv sync --locked` shown in the README, the guides and `CONTRIBUTING.md`
(the newcomer route, also used inside the guide runners) still builds the project with an unhashed
isolated build environment whose backend version is pinned by `pyproject.toml`. Installing
anything over step 1 by hand (for example `uv pip install hatchling` without hashes) also
bypasses it; running step 1 again restores the pinned, hashed versions.

Tests that need the private reference executors skip with that reason; the scorer tests that can
run against the published truth (`protocol/golden_truth/`) do. The signed-HTTP transport
tests (`tests/transport`) are public. They need a Valkey-compatible server: set
`SN87_TEST_VALKEY_URL` to one (CI uses a pinned Valkey container), or put `valkey-server` or
`redis-server` on PATH; otherwise they skip with that reason (`SN87_REQUIRE_TRANSPORT_TESTS=1`
makes the skip a failure). The design is in
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
