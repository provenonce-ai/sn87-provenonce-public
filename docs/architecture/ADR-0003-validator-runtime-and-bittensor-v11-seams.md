# ADR-0003: Separate validator runtime, signed HTTP, and chain intent seams

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** Will O'Brien, Provenonce Founder & CEO; SN87 protocol maintainer

## Canonical constraint

The SN87 protocol specification assigns the subnet its own server, client, and message models; assigns the
signed HTTP envelope to Bittensor v11 `bittensor.http_auth`; places the non-compensable
integrity gate before scoring; and places weight submission behind the pinned v11
`set_weights` intent. It forbids fabricated weights when no valid preference row exists and
requires version, target, transport, dry-run, and chain-reconciliation evidence before
testnet submission.

## Current-source findings

The official Bittensor Python SDK was inspected at Subtensor commit
[`823bdcbc58a29f60b243be4737a7c72b34ac7d93`](https://github.com/RaoFoundation/subtensor/tree/823bdcbc58a29f60b243be4737a7c72b34ac7d93/sdk/python):

- [`http_auth.py`](https://github.com/RaoFoundation/subtensor/blob/823bdcbc58a29f60b243be4737a7c72b34ac7d93/sdk/python/bittensor/http_auth.py)
  implements `btauth/1` over the raw body, sender, receiver, method, path, freshness, nonce,
  crypto type, and signature. The default replay store is process-local, so a production
  multi-process or multi-host service requires a shared replay store.
- [`intents/weights.py`](https://github.com/RaoFoundation/subtensor/blob/823bdcbc58a29f60b243be4737a7c72b34ac7d93/sdk/python/bittensor/intents/weights.py)
  provides one `SetWeights` entry point, preflights current chain state, normalizes and
  quantizes weights, rejects all-zero input, and selects the configured plaintext or
  commit-reveal path.
- [`intents/plan.py`](https://github.com/RaoFoundation/subtensor/blob/823bdcbc58a29f60b243be4737a7c72b34ac7d93/sdk/python/bittensor/intents/plan.py)
  separates a serializable transaction preview from execution and applies policy bounds.

Technically relevant subnet implementations were inspected at immutable commits:

- [Ridges](https://github.com/ridgesai/ridges/tree/9397a57e3d03756b9c6c4df29ceaef7ecb2063a0)
  isolates evaluation work, uses bounded concurrency, and runs weight submission in a
  background seam. Its missing-target path is subnet-specific and is not adopted by SN87.
- [Glyph](https://github.com/glyph-research/glyph-subnet/tree/35ffbb1a8a203df366743a219d2f9b8fa2cd1a77)
  separates evaluation, validator orchestration, and weight setting; provides an offline
  demo; uses exact round-trip checks; and makes `--dry-run` an explicit operator path.
- [Targon](https://github.com/manifold-inc/targon/tree/9fb0722dd0af8f4b5f45eb3270ae5e628c5a2101)
  uses a modular service layout rather than coupling every concern to one neuron process.
- [Chutes miner](https://github.com/rayonlabs/chutes-miner/tree/e32943ec1616f4f592209a613fa08001eb79d3e5)
  demonstrates that deployment and operational concerns warrant their own boundary.

These are implementation references, not protocol authorities. Their incentive rules,
burn policies, deployment assumptions, and legacy SDK usage do not enter SN87 canon.

## Decision

Use three explicit seams:

1. A subnet-owned miner gateway returns a typed response plus transport-established
   signature, nonce, and receipt-time facts.
2. A separate content verifier establishes visible-policy and Evidence facts.
3. A deterministic validator orchestrator combines those facts in the whitepaper integrity
   gate and emits integrity-passed, integrity-failed, timeout, transport-error, or verification-error
   outcomes in requested miner order.

The first implementation is in-memory only. It has no HTTP framework, Bittensor dependency,
wallet, chain client, scorer, ranker, weight planner, hidden challenge data, or production
configuration. One timeout bounds each complete miner exchange. Verification is asynchronous;
exceptions are isolated per miner and their messages are not exposed.

## Deferred decisions

The following remain absent until their canonical inputs are locked:

- target Subtensor runtime and endpoint qualification (the SDK pin is resolved by ADR-0004);
- HTTP framework, routes, deployment topology, shared nonce store, and service identity;
- testnet target, wallet handling, version key, hyperparameters, and transaction policy;
- rule scores, challenge aggregation, epoch update, normalization, and no-valid-row action;
- hidden Lane One supply, truth, thresholds, and advance criteria.

## Consequences

SN87 can now run the request/response and integrity portion of the validator pipeline as
code. That proves local orchestration and failure behavior only. It cannot be mistaken for a
miner service, a benchmark, an incentive design, a testnet dry-run, or a chain-capable build.
