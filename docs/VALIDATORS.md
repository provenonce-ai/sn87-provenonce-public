# Validators

> Send capsules, check answers, score them with the one public scorer, and see what can and
> cannot be run from this repository.

Quick links: [validator quickstart](quickstart/validator.md) | [second-validator readiness](./protocol/second-validator-readiness.md) | [profile application](./protocol/profile-application.md) | [weight flow](diagrams/06-weight-flow.md) | [glossary](GLOSSARY.md)

**Status.** Testnet 582, alpha. This repository holds the validator-side contracts and checks.
It does not hold the reference executors, so a validator for hidden instances cannot be run from
it alone. Applying weights is an operator action with the operator's own hotkey, permit and an
explicit approval; nothing here performs or authorizes it.

## What a validator does

1. **Dispatch** capsules to miners over the signed client.
2. **Gate** each reply: schema, policy, signature, nonce, evidence, deadline.
3. **Score** with the one scorer under a committed profile.
4. **Form a preference row**, or `NO_VALID_PREFERENCE_ROW`.
5. **Quantize** to u16 weights (no broadcast) for the uids a plan names.

If the run's profile commitment differs from the profile used, evaluation stops with
`PROFILE_NOT_APPLIED`.

## What you can run here, and what you cannot

| Task | Can you run it from this repository? | How |
|---|---|---|
| Score a miner response on a public fixture against published truth | Yes | [quickstart](quickstart/validator.md#score-against-the-published-truth) |
| Run the staging validator on the 16 public instances of seed 0 | Yes, no chain | `scripts/staging_subnet.py --truth golden` |
| Recompute the attested validator digest | Yes | `scripts/verify_attestation.py` |
| Read the chain and compare attested weight-sets | Yes, read only | `scripts/verify_attestation.py` |
| Quantize a row to u16 | Yes, no broadcast | `src/sn87_provenonce/weights_dry_run.py` |
| Verify a contest window from its commitments | Yes | `scripts/contest_window.py --phase verify` |
| Check shadow-to-weighted criteria on published results | Yes | `scripts/admission_plan.py check` |
| Recompute a closed window from its published files | Yes, with the files (a fixture is included); some steps stay UNVERIFIED | [reproduce a window](guides/reproduce-a-window.md) |
| Score hidden instances | No | needs the private reference executors or another truth source (open decision) |
| Recompute the plan digest | No | built by private operator tooling |
| Submit weights with commit-reveal | No | tested against a fake chain; no submitter exists |
| Set weights | Operator only | needs your hotkey, permit and an approval |

## Requirements

| Requirement | Detail |
|---|---|
| Platform | Linux or macOS (Windows through WSL2) |
| Python and uv | Python 3.12 or later, [uv](https://docs.astral.sh/uv/); `uv sync --locked --all-extras` |
| Replay store | A Valkey-compatible server with `maxmemory-policy noeviction`, dedicated to it |
| Chain access | Read-only for the checks above. No wallet or key is needed to verify |
| Resource sizing | Not published. No disk, bandwidth or round-time figure has been measured |

## If you see this

| You see | Meaning |
|---|---|
| Verifier ends `OVERALL UNVERIFIED`, exit 3 | Expected outside Provenonce: the plan check cannot run. Integrity, validator and chain checks should still PASS. |
| `NO_VALID_PREFERENCE_ROW` | No estimate is above theta. Nothing is submitted. |
| `VOID_SAMPLE_FLOOR` | Fewer admitted cases than the profile minimum. The window does not count and says nothing about miners. |
| `RESPONSE_LATE`, `REMOTE_REJECTED_<status>`, `MINER_REJECTED_ENVELOPE` | Recorded as unavailability, not integrity failure. |
| `TRUTH_HASH_DIFFERS_FROM_OPEN` | The truth file does not match the hash published at open. Refuse it. |

## Go deeper

- [Scoring pipeline](diagrams/03-scoring-pipeline.md) and [weight flow](diagrams/06-weight-flow.md)
- [Contest windows](./protocol/contest-windows.md) and [window results](./protocol/window-results.md)
- [Admission of outside uids](./protocol/admission.md)
- [ADR-0005: signed HTTP and the replay boundary](architecture/ADR-0005-signed-http-and-replay-boundary.md)
- [Evidence bundle](./protocol/evidence-bundle.md)

Issues and questions: the [issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose).
Security reports go privately ([SECURITY.md](../SECURITY.md)).
