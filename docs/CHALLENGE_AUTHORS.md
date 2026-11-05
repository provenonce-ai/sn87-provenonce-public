# Challenge authors

> Propose a new task for SN87 in terms the system can check: who uses it, where truth comes from,
> how it is scored and what it must beat.

Quick links: [propose a challenge](guides/propose-a-challenge.md) | [ADR-0021: truth fixed at build time](architecture/ADR-0021-published-truth-for-public-fixtures.md) | [glossary](GLOSSARY.md) | [limits](../LIMITATIONS.md)

**Status.** Testnet 582, alpha. A proposal is always `PROPOSED`. Passing the check changes no
weight, profile, class binding or miner admission, and promises no uptake.

## The short version

A new task family is a new **class binding**, never a new scorer. It supplies the capsule and
response validators, defect severities, a generator and a baseline, and it is scored by the
existing code under a committed profile ([CONTRIBUTING.md](../CONTRIBUTING.md)). Truth must be
stated: say where it comes from, and say it honestly.

## What a proposal must answer

| Question | Field | Why it matters |
|---|---|---|
| Who will use the result? | `intended_consumer` | A challenge nobody uses measures nothing. |
| Who may see which evidence? | `evidence_rights` | Raw source records must not leave the source by default. |
| Where does truth come from? | `truth_source.oracle_class` (A to D) | Decides whether the truth can be checked by others. |
| What does a submission look like? | `submission_format` | It must fit the wire rules. |
| How is it scored? | `scoring` | A pinned committed profile, or `PROPOSED_UNPINNED`. An unpinned rule is never activated. |
| What must it beat? | `baselines` | A matched public-contract baseline. Without one, headroom cannot be shown. |
| What does it cost? | `resource_budget` | Cost is recorded beside scores. |
| Is there room above the baseline? | `headroom` | A family where the baseline already scores the maximum is `NULL_NO_HEADROOM`. |

## Oracle classes in one table

| Class | Truth comes from | Self-verifying |
|---|---|---|
| A | Fixed when the instance is built, such as a planted defect list | Yes (decision pending) |
| B | A public source; not defined further here | Yes (decision pending) |
| C | Comparison with a reference execution, at least two independent ones | No |
| D | A recorded adjudication with measured reliability | Never |

For a family whose truth is computed from the capsule, the private reference executors are
load-bearing: if published they would answer any instance whose capsule is known. The design rule
for new families is truth fixed at build time (class A), so validator code can be open while
instances stay hidden. No such family exists in this repository yet
([LIMITATIONS.md](../LIMITATIONS.md), item 17).

## Run the check

```bash
uv run sn87-provenonce challenge check examples/challenge-proposals/TEMPLATE.json
```

| Verdict | Exit code | Meaning |
|---|---|---|
| `ADMISSIBLE` | 0 | No rule in this check fired. It does not show headroom, correct truth or uptake. |
| `NEEDS_DECISION` | 3 | A person must decide, for example a prior null result or an unpinned scoring rule. |
| `INADMISSIBLE` | 1 | A rule failed, for example no baseline, or a Type D proposal described as self-verifying. |

Reason codes are listed in [propose a challenge](guides/propose-a-challenge.md#verdicts-and-reason-codes).
The two existing families both return `NEEDS_DECISION`, because both are recorded as having no
headroom over the baseline today.

## Before you write one

- Read how a pool can bound what a constant answer scores
  ([LIMITATIONS.md](../LIMITATIONS.md), item 18; [ADR-0022](architecture/ADR-0022-constant-bound-fixed-outcome-profile.md)).
- Read how a window is committed, opened and revealed ([timeline](diagrams/04-contest-window-timeline.md)).

## Where to go next

[Propose a challenge](guides/propose-a-challenge.md) | [Architecture decisions](architecture) |
[Profile application](./protocol/profile-application.md) | [Wire rules](./protocol/wire-rules.md) |
[Issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose)
