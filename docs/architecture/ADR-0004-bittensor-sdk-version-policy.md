# ADR-0004: Pin Bittensor 11.1.0 as the optional integration baseline

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** Will O'Brien, Provenonce Founder & CEO; SN87 protocol maintainer

## Context

The SN87 protocol specification requires the v11 `bittensor.http_auth` envelope and the v11
`set_weights` intent, while requiring exact package and Subtensor runtime revisions before
testnet. The core SN87 models and local validator runtime do not require Bittensor to run.
The repository nevertheless needs a reproducible SDK contract before a real transport or
chain adapter can be built.

On 2026-09-03, the
official PyPI release record (bittensor 11.1.0) and
[RaoFoundation Subtensor repository](https://github.com/RaoFoundation/subtensor) reported:

- PyPI's latest stable `bittensor` release was `11.1.0`, uploaded 2026-08-14, supporting
  Python 3.10 through 3.14. The wheel SHA-256 was
  `d84e33169249c56c41b4b43f6b2f4ed80bc2fd98afcb69a3d5844720a4d72b58`; it was not
  yanked.
- The wheel contained `bittensor/http_auth.py`, `bittensor/intents/weights.py`, and
  `bittensor/intents/plan.py`. Its metadata required `bittensor-core>=0.1.3,<0.2.0`.
- An isolated Python 3.12 installation resolved `bittensor-core==0.1.3`. Direct tests proved
  `btauth/1` happy-path verification and rejection of replay, receiver substitution, body
  mutation, and path mutation. `SetWeights`, `Policy`, and `Plan` were importable.
- A point-in-time vulnerability audit reported no known vulnerabilities in the resolved
  environment. This is a dated observation, not a continuing security guarantee.
- Monorepo [`main` at `823bdcbc58a29f60b243be4737a7c72b34ac7d93`](https://github.com/RaoFoundation/subtensor/tree/823bdcbc58a29f60b243be4737a7c72b34ac7d93/sdk/python)
  declared
  `11.3.0.dev0`. That is research evidence for the direction of development, not a stable
  package release.
- The latest non-prerelease
  [Subtensor GitHub release observed was runtime `v445`](https://github.com/RaoFoundation/subtensor/releases/tag/v445), target
  commit `d3f40e44bda9019c606aeb0c907bb52ba7fe386c`. Newer runtime releases through
  `v453` were marked proposed/prerelease. GitHub release state is not proof of the runtime
  currently deployed at a future target endpoint.

## Decision

Declare `bittensor==11.1.0` as an exact optional dependency named `bittensor` and lock its
complete resolution in `uv.lock`. Keep it out of the base installation so the protocol,
canonicalization, transparent simulation, and transport-neutral runtime remain lightweight
and chain-independent.

Run SDK contract tests in CI through the existing `uv sync --locked --all-extras` path. The
tests must remain offline and prove only the imported API and cryptographic envelope behavior.
They may construct a `SetWeights` intent but must not create a client, load a wallet, contact
an endpoint, plan an extrinsic, or execute a transaction.

The reproducible local checks are:

```bash
uv sync --locked --all-extras
uv run pytest tests/bittensor
uv run pytest
uv build --wheel
```

Do not pin the moving monorepo main branch. Do not use a compatible-release range for the SDK.
Dependency-update automation may propose a new exact version, but a human-readable ADR update,
contract-test pass, vulnerability check, and migration review are required before merge.

Treat runtime compatibility as a target-specific qualification, not a Python dependency:

1. Record the target endpoint, observed genesis hash, runtime `spec_version`, block hash,
   netuid, mechanism ID, and relevant hyperparameters in a create-only manifest.
2. Record the Subtensor release tag and source commit that correspond to the observed runtime,
   or explicitly record that the mapping is unresolved.
3. Run signed-HTTP conformance and `SetWeights` plan-only tests against that exact target.
4. Refuse execution on manifest drift. A plan result is not transaction authority.

## Options considered

### Exact stable PyPI pin: selected

Reproducible, installable on both repository Python versions, hash-locked, and already exposes
the whitepaper-required surfaces.

### Moving Git commit

Rejected for implementation. It exposes newer work but identifies as a development version
and can move ahead of published dependencies, runtime deployment, and migration guidance.

### Version range such as `bittensor>=11,<12`

Rejected. It allows silent API and behavior drift in authentication and transaction code.

### Defer every SDK dependency

Rejected. A stable v11 release exists, and postponing the compatibility contract would push
avoidable uncertainty into the transport and testnet phases.

## Consequences

- SN87 gains a reproducible SDK integration target without coupling its core package to chain
  libraries.
- CI will detect removal or incompatible change of the exact v11 surfaces before adapter work
  merges.
- Upgrades are intentionally explicit rather than automatic.
- Runtime `v445` remains a dated research baseline only. No target runtime, endpoint, netuid
  configuration, wallet, or transaction authority is selected by this ADR.
- The future HTTP framework and shared replay-store implementation remain separate decisions.
