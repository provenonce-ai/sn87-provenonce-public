# Documentation map

> Every public page, who it is for, and what it is for. Start with the row for your role.

Quick links: [README](../README.md) | [start here](guides/start-here.md) | [glossary](GLOSSARY.md) | [diagrams](diagrams/README.md) | [limits](../LIMITATIONS.md)

New to SN87? Read the [README](../README.md), then [start here](guides/start-here.md). Unsure of a
word? It is in the [glossary](GLOSSARY.md). Agents working in this repository: read
[AGENTS.md](../AGENTS.md) first.

## Pick your role

| You are | Read first | Then |
|---|---|---|
| A miner | [Miners](MINERS.md) | [miner guide](guides/miner-guide.md), [shadow cohort](guides/shadow-cohort.md) |
| A validator | [Validators](VALIDATORS.md) | [validator quickstart](quickstart/validator.md), [admission](./protocol/admission.md) |
| A challenge author | [Challenge authors](CHALLENGE_AUTHORS.md) | [propose a challenge](guides/propose-a-challenge.md) |
| A reviewer or researcher | [Reviewers](REVIEWERS.md) | [reviewer test guide](guides/reviewer-test-guide.md), [LIMITATIONS.md](../LIMITATIONS.md) |

## Start and orient

| Page | Audience | One-line purpose |
|---|---|---|
| [README](../README.md) | everyone | What SN87 is, who it is for, how it works, current status |
| [Glossary](GLOSSARY.md) | newcomers | Every term in plain English, in tables |
| [Diagrams](diagrams/README.md) | everyone | Eight pictures of the system, each tied to the code |
| [Start here](guides/start-here.md) | newcomers | A fresh clone to a result you can read, in about 20 minutes |
| [LIMITATIONS](../LIMITATIONS.md) | everyone | What the results do and do not show |

## Role pages

| Page | Audience | One-line purpose |
|---|---|---|
| [Miners](MINERS.md) | miners | The route from a demo to a published, unweighted record |
| [Validators](VALIDATORS.md) | validators | What you can run here and what stays private |
| [Challenge authors](CHALLENGE_AUTHORS.md) | challenge authors | What a proposal must answer, and the check |
| [Reviewers](REVIEWERS.md) | reviewers, researchers | What you can verify, and what stays UNVERIFIED |

## Guides (steps you can run)

| Page | Audience | One-line purpose |
|---|---|---|
| [Start here](guides/start-here.md) | newcomers | First clone to first result; the four levels |
| [Miner guide](guides/miner-guide.md) | miners | Install, write a method, serve it signed, announce it |
| [Reviewer test guide](guides/reviewer-test-guide.md) | reviewers | Verify the testnet proof and try a tamper demo |
| [Shadow cohort](guides/shadow-cohort.md) | miners | How to apply to be scored with weight 0, and the proposed criteria |
| [Propose a challenge](guides/propose-a-challenge.md) | challenge authors | Describe a new task and run the admissibility check |
| [Reproduce a window](guides/reproduce-a-window.md) | reviewers, validators | Recompute a closed window from its published files; it says what it could not check |


## Quickstarts (drafts)

| Page | Audience | One-line purpose |
|---|---|---|
| [Miner quickstart](quickstart/miner.md) | miners | A request against a fixture, wire rules, the signed endpoint |
| [Validator quickstart](quickstart/validator.md) | validators | Score against published truth, check what a validator did |
| [Contest windows quickstart](quickstart/contest-windows.md) | validators, reviewers | Run a dry-run window and verify a committed one |

## Protocol and reference

| Page | Audience | One-line purpose |
|---|---|---|
| [Contest windows](./protocol/contest-windows.md) | validators, reviewers | Generator, phases, commitments, protocol 0.2 |
| [Window results](./protocol/window-results.md) | validators, miners | The per-window result record, field by field |
| [Admission](./protocol/admission.md) | validators, miners | Local, shadow, weighted: stages, plan versions, criteria |
| [Profile application](./protocol/profile-application.md) | validators, reviewers | How committed profiles drive scoring |
| [Wire rules](./protocol/wire-rules.md) | miners, validators | Canonical bytes, numbers, NA, rationale |
| [Miner announcement](./protocol/miner-announcement.md) | miners, validators | How an endpoint is published and found |
| [Evidence bundle](./protocol/evidence-bundle.md) | reviewers | The record of a run and its replay trust boundary |
| [Implementation status](./protocol/implementation-status.md) | reviewers | Implemented, enabled, tested, deployed |
| [Second-validator readiness](./protocol/second-validator-readiness.md) | validators | A checklist of what another validator needs |
| [Guide format](./protocol/guide-format.md) | contributors | How guides are written so CI can run them |
| [CMT v0.1](./protocol/cmt-v0.1.md) | challenge authors | A candidate task specification schema |
| [v0alpha1 traceability](./protocol/v0alpha1-field-traceability.md) | reviewers | Field-level source of legacy objects |

## Decisions and research code

| Page | Audience | One-line purpose |
|---|---|---|
| [Architecture decisions](architecture) | reviewers | ADR-0001 to ADR-0024: why each design choice was made |
| [Local validator](runtime/local-validator.md), [reference miner](runtime/reference-miner.md) | contributors | Local research runtime |
| [Simulation](simulation) | researchers | Transparent local simulations; on no weight path |
| [Whitepaper policy](whitepaper/README.md) | everyone | Why the whitepaper is not distributed here |
| [Releasing](releases/RELEASING.md) | maintainers | How a release is cut from change notes |

## Project files

[CONTRIBUTING](../CONTRIBUTING.md) | [SECURITY](../SECURITY.md) | [PROVENANCE](../PROVENANCE.md) |
[CHANGELOG](../CHANGELOG.md) | [AGENTS](../AGENTS.md)
