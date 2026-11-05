# Reviewers and researchers

> Check SN87's claims yourself, and know what you cannot check from the public files.

Quick links: [reviewer test guide](guides/reviewer-test-guide.md) | [limits](../LIMITATIONS.md) | [trust chain diagram](diagrams/05-trust-chain.md) | [attestation](../attestation/README.md) | [glossary](GLOSSARY.md)

**Status.** Testnet 582, alpha. Every row so far is conformance evidence for transport, integrity
and arithmetic, not method competition. Read [LIMITATIONS.md](../LIMITATIONS.md) before you cite
any result.

## Three ways in

| You want to | Do this | Time |
|---|---|---|
| Run it and verify the chain proof | Follow the [reviewer test guide](guides/reviewer-test-guide.md); it needs no wallet or key | 30 to 40 minutes |
| See the first hour of a newcomer | [Start here](guides/start-here.md) | 20 minutes |
| Read how claims are bounded | [Trust chain](diagrams/05-trust-chain.md), then [LIMITATIONS.md](../LIMITATIONS.md) | 15 minutes |

## What you can check, and the word you will see

| Claim | How to check | Last recorded result |
|---|---|---|
| The attestation file is intact | `uv run --extra transport python scripts/verify_attestation.py` | PASS |
| The validator digest recomputes from published truth | same command | PASS |
| The weight rows match what the chain recorded | same command (reads the public test node) | PASS |
| The plan digest | same command | UNVERIFIED, built by private operator tooling |
| Overall | same command | UNVERIFIED, exit code 3 |
| A committed window regenerates from its commitments | `scripts/contest_window.py --phase verify` | PASS or FAIL per window |
| A closed window's scores and derived rows follow from its published files | `scripts/reproduce_window.py` ([guide](guides/reproduce-a-window.md)) | PASS or FAIL per step; signatures and hidden-instance truth stay UNVERIFIED, so the exit code is 3 |
| The scorer matches published truth on public fixtures | `uv run sn87-provenonce demo` | three rows |
| A uid is a given method | cannot be checked | UNVERIFIED (private naming binding) |
| Truth of a hidden instance is correct | cannot be checked | UNVERIFIED (private reference executors) |

PASS means it ran and the claim holds. FAIL means it ran and the claim does not hold. UNVERIFIED
means it could not run here and nothing is claimed.

## What to look at hardest

1. **The operator is also the author of the instances.** Provenonce builds the instances and holds
   the reference executors. The opening block removes advance knowledge only. Trust in scoring
   still needs independent validators that construct their own challenges
   ([timeline](diagrams/04-contest-window-timeline.md)).
2. **The public baseline ties the reference methods** (`NULL_NO_HEADROOM`,
   [LIMITATIONS.md](../LIMITATIONS.md) item 8). A score of 1 shows agreement, not skill.
3. **Weights.** Only uids 1 and 2 are weighted, and both are operated by Provenonce
   ([weight flow](diagrams/06-weight-flow.md)).
4. **Scoring limits** are listed in items 3, 16 and 18, with the committed, inactive profiles
   that go further ([ADR-0019](architecture/ADR-0019-state-payoff-wrong-scope-and-citation-precision-profile.md),
   [ADR-0022](architecture/ADR-0022-constant-bound-fixed-outcome-profile.md)).
5. **Small samples.** First Light scores 12 assignments per method (item 10).

## Where the records are

| You want | Read |
|---|---|
| What is implemented, enabled, tested, deployed | [implementation status](./protocol/implementation-status.md) |
| Which method holds which uid, and the basis | [README uid table](../README.md#which-methods-hold-uids-1-and-2) |
| Why a field is shaped as it is | [wire rules](./protocol/wire-rules.md), [profile application](./protocol/profile-application.md) |
| Why a design choice was made | [architecture decisions](architecture) |
| Provenance of the first weight row | [PROVENANCE.md](../PROVENANCE.md) |
| What a second validator would need | [second-validator readiness](./protocol/second-validator-readiness.md) |
| Who may be scored and how | [admission](./protocol/admission.md) |

## Report what you find

Open an issue from the [issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose)
(setup failure or scoring question). For a suspected vulnerability, do not open an issue: follow
[SECURITY.md](../SECURITY.md) and write privately. Never include secrets, wallet material or
hidden challenge material in a report.
