# Glossary

> Plain-English meaning of every SN87 term, defined once. If a word on another page is unclear,
> it is here.

Quick links: [docs map](README.md) | [README](../README.md) | [diagrams](diagrams/README.md) | [limits](../LIMITATIONS.md)

You do not need to learn all of this to start. A miner needs the first two tables. A reviewer
needs the third to the sixth. Terms in the last table are for people who read the scoring rules.

## The work itself

| Term | What it really is |
|---|---|
| **SN87** | A Bittensor subnet. It is called Proof of Assurance. Miners test the difference between observed autonomous work and a declared assurance contract. |
| **Bittensor** | The network SN87 runs on. A subnet has a number (a `netuid`). SN87 runs on public testnet `582`. |
| **Testnet 582** | The test network SN87 is on. Its funds have no value. No result here is a mainnet, production or adoption claim. |
| **Miner** | A person or program that answers capsules with a Differential. A miner runs its own endpoint. |
| **Validator** | The party that sends capsules, checks the answers, scores them with the public scorer and, for weighted uids, sets weights. Today the validator is operated by Provenonce. |
| **Hotkey, uid** | A hotkey is the key a miner signs with. A uid is the slot number it holds on the subnet. A weight row names uids, not methods. |
| **Capsule** | The evidence for one case: events, source commitments, a policy, a nonce and an evidence commitment. It is the input a miner receives. It is built from synthetic data in the public fixtures. |
| **Differential** | A miner's one structured answer for one capsule. It has a state, any findings (each with a code, severity, evidence references and confidence) and a rationale. |
| **State** | One of three answers: `FINDINGS`, `NO_MATERIAL_DEVIATION` or `INSUFFICIENT_EVIDENCE_ABSTAIN`. |
| **Finding** | One claimed defect, named by a code, with the evidence references that show it. |
| **Evidence reference** | A pointer to an event in the capsule, or to the completeness scope (`$completeness`). Findings must cite them. |
| **Abstention** | The answer `INSUFFICIENT_EVIDENCE_ABSTAIN`: "the evidence is not enough to say". |
| **Wrong scope** | A record whose approval covers a different mission, recipient or artifact than the action. The truth is an abstention. |
| **Family, class** | A kind of task. Two exist: `IC-APPROVAL-APPLICABILITY` (was an approval carried past a changed condition?) and `TYPE-C-RELEASE` (does a release trace break its grammar?). A class binding ties a family to its validators, generator, baseline and profile. |
| **Method** | The code a miner runs to turn a capsule into a Differential. |
| **Rationale** | Free text that explains an answer. It is required and never scored. |

## Contest windows and commitments

| Term | What it really is |
|---|---|
| **Window, contest window** | A bounded period (`opens_at` to `closes_at`) in which miners answer fresh generated capsules. Results are published after it. |
| **Schedule** | The list of windows committed up front, with a `schedule_commitment` over all of them. |
| **Generator** | The public code that builds capsules from a seed (`scripts/contest_window.py`, id `sn87-contest-generator/0.1` or `/0.2`). |
| **Master seed** | A secret the operator holds. Window seeds are derived from it. It is never published. |
| **Seed commitment** | A hash published before a window opens that fixes the window's seed. In protocol 0.2 it commits to a pre-seed. |
| **Pre-seed** | In protocol 0.2, a secret derived from the master seed. The window seed is built from the pre-seed and the opening block. |
| **Opening block** | In protocol 0.2, the first chain block at or after `opens_at`. Its hash goes into the window seed, so nobody knows the instances before that block exists (see ADR-0023 for limits). |
| **Cases commitment** | A hash over the capsule set, published at open. |
| **Truth commitment** | A salted hash over the per-case truth, bound to the seed commitment and the cases commitment. In 0.2 it is published at open and sent in every request. It hides the truth and fixes it. |
| **Reveal** | The publication, after close, of the seed (and pre-seed and block) and the specification, so anyone can regenerate every capsule. |
| **Reveal deadline** | The latest time a reveal may appear. In 0.2 it is at most 7 days after close. A window past it with no reveal is flagged `REVEAL_OVERDUE`. |
| **Reveal bundle** | One file (`sn87-reveal-bundle/0.1`) holding the reveals of a whole schedule. Each window is `OPENED`, `NOT_OPENED` or, for 0.1, `REVEALED`. `verify-bundle` checks it. |
| **Window commitments** | An optional object in each signed request: generator, window id, cases commitment and truth commitment. |
| **Protocol 0.1, 0.2** | Versions of the contest protocol. 0.2 adds the opening block, truth at open and the reveal deadline. 0.2 tooling is committed and no 0.2 schedule is deployed. |
| **Anchoring** | Publishing the commitments file somewhere independent and dated, so readers know when it existed. The operator should do this; the tool only produces the value. |
| **Shadow service** | The operator's service that queries shadow miners each window and publishes results. It is not in this repository. |

## Scoring

| Term | What it really is |
|---|---|
| **Profile** | A committed JSON document that holds every scoring parameter. Changing one is a new profile version with a new commitment. |
| **Profile commitment** | A hash of the canonical profile bytes. A result scored under a different commitment fails with `PROFILE_NOT_APPLIED`. |
| **`IC-FIRST-LIGHT-MIN-1`** | The profile on the weight path for the approval class. Binary evidence credit, 12 assigned cases minimum, theta 0.60. |
| **MIN-2** (`IC-FIRST-LIGHT-MIN-2`) | Adds a state payoff matrix (a correct abstention is paid) and evidence credit of precision times recall. Committed, not active. |
| **MIN-3** (`IC-FIRST-LIGHT-MIN-3`) | MIN-2 with a larger window: 24 scored cases against a minimum of 22, so it absorbs 2 reference failures. Committed, not active. |
| **MIN-4** (`IC-FIRST-LIGHT-MIN-4`, and `GRA-RELEASE-MIN-4` for the release class) | Rules version 4: no constant answer can reach theta minus a margin, calibration over a fixed outcome set, declared-severity credit, a price on over-citing, and identical answers share one weight. Committed, not active. |
| **`GRA-W03-3`** | The committed profile of the release class (`TYPE-C-RELEASE`). |
| **Integrity predicates** | Six yes or no checks: schema, policy, signature, nonce, evidence, deadline. All must be true or the score is 0. |
| **Detection, evidence, calibration** | The three scored dimensions: did you find the right defects, did you cite the right evidence, did your stated confidence match what happened. |
| **Composite** | The weighted geometric mean of the dimensions, floored at epsilon. |
| **Score** | A number from 0 to 1 for one response. |
| **Estimate (epoch estimate)** | A method's average score over its assigned cases. Invalid or missing answers count as 0. It needs the minimum number of cases and at most 10 percent invalid. |
| **Theta, gamma** | The threshold (0.60) below which an estimate earns nothing, and the exponent (2) that sharpens the difference above it. |
| **Preference row** | The estimates turned into shares: `z = max(estimate - theta, 0) ** gamma`, divided by the sum. If every z is 0 the result is `NO_VALID_PREFERENCE_ROW`. |
| **NA** | "Not applicable or not measured". Written `"NA"`, never `0`. |
| **Inactive term** | A scoring equation defined but not scored: Eq. 2, Eq. 8, Eq. 10 and Eq. 11 (efficiency, which stays neutral). |
| **Baseline** | A matched method that uses only the public contract (`public_contract_baseline`). It is scored beside every miner and never weighted. |
| **Reference, candidate** | Method roles. A reference is a Provenonce algorithm that also computes truth. A candidate is a Provenonce-written method (`approval_witness`) that is a replaceable stand-in. Neither is an independent outside miner. |
| **Headroom** | How far a method can score above the best public method. If the best public method already scores the maximum, there is none. |
| **`NULL_NO_HEADROOM`** | The result when a candidate does not beat a public method by at least 0.001 (or ties it exactly in a comparison). The null result is kept, not hidden. |
| **`RETIRE_RECOMMENDED`** | A family whose public methods all sit within 0.001 of the ceiling. Nothing can lead them, so more weighting measures nothing. |
| **Uplift** | A strictly higher estimate than the public baseline on the same scored instances. A tie is not uplift. The shadow-to-weighted criteria require it in every checked window. |
| **Weight gate** | The check (`candidate_gate`, `require_weight_eligible`) that a candidate beats every public method before any weighting. A weighted plan version cannot be proposed without an eligible verdict, but the gate is wired into no weight write and no live weight path. |
| **Redundancy group** | Identities whose answers have the same decision vector on every case. Under MIN-4 they share one weight. Inactive (MIN-4). |
| **Flags** | Non-scoring records: simultaneous dispatch, similar response time, identical answers on tasks that separate methods. Never scored. Inactive (MIN-4). An admission report also lists `SHARES_DECISION_GROUP_WITH` for a candidate that gave the same decisions as other uids or public methods; it changes no verdict. |
| **Constant answer** | One fixed reply given to every case. The MIN-4 profiles bound what such an answer can score (LIMITATIONS item 18). |
| **Conformance only** | The claim on every bundle: the rows test transport, integrity and arithmetic, not method competition. |

## Stages and weights

| Term | What it really is |
|---|---|
| **Local** | Stage 1: you run public code on public fixtures on your own machine. Nothing is queried or published. |
| **Shadow** | Stage 2: your endpoint is queried each window, scored and published with `stage: shadow` and `weight: 0`. A shadow result is a record, not a number in a weight row. |
| **Weighted** | Stage 3: a uid appears in an approved weight row on the chain. Today only uids 1 and 2, both operated by Provenonce. |
| **Plan, plan version** | A digested document that names the weighted uids. A new stage for a uid is a new plan version, approved outside this repository. |
| **Shadow allowlist** | `shadow/allowlist.json`, the list of outside uids that may be queried. Changed only by a reviewed pull request. |
| **Weight row** | The numbers set on the chain for each uid. |
| **u16 weights** | Weights scaled to whole numbers up to 65535, as the chain stores them. |
| **Plain weight mode, commit-reveal** | Plain mode sets weights directly. Chain commit-reveal submits a timelocked commit. SN87 testnet uses plain mode. Commit-reveal code is tested against a fake chain only. (This is a different thing from the window's commit-and-reveal of seeds.) |
| **Attestation** | A self-digested list of completed testnet runs: the block each was set in and the row. It has no signatures and no keys. |
| **Golden truth** | `protocol/golden_truth/`: published per-case truth of the committed public fixtures. It lets anyone run the scorer. |
| **Reference executor** | Private code that computes truth for any capsule. For hidden instances it is the answer key, so it is not published. |

## Trust and checks

| Term | What it really is |
|---|---|
| **PASS** | The check ran and the claim holds. |
| **FAIL** | The check ran and the claim does not hold. |
| **UNVERIFIED** | The check could not run here. Nothing is claimed. One UNVERIFIED keeps the overall verdict UNVERIFIED (exit code 3). |
| **Oracle class A** | Truth is fixed when the instance is built, such as a planted defect list. Treated as self-verifying (decision pending). |
| **Oracle class B** | Truth from a public source. The repository does not define it further. Treated as self-verifying (decision pending). |
| **Oracle class C** | Truth by comparison with a reference execution, at least two independent ones. Not self-verifying. |
| **Oracle class D** | Truth from a recorded adjudication, which must carry a measured reliability. Never self-verifying. |
| **Type C** | Careful: this is the release-trace task family `TYPE-C-RELEASE`, a different thing from oracle class C. |
| **Challenge proposal** | A JSON description of a new task checked by `sn87-provenonce challenge check`. The verdict is `ADMISSIBLE`, `NEEDS_DECISION` or `INADMISSIBLE`. It activates nothing. |
| **Trusted sender** | A hotkey you name with `--trusted-sender` so it may send to your miner without a validator permit. It is still signature-checked and rate limited. At most 8. |
| **Sender allowlist, validator permit** | By default a miner accepts only senders that hold `validator_permit` on the subnet. Others get `SENDER_NOT_PERMITTED` (403). |
| **Replay store** | A Valkey-compatible server that remembers request nonces so a replayed request is refused. It must fail closed. |
| **Announcement** | A record, signed by a miner's hotkey, that says where its endpoint is. |
| **Outcome code** | A short label for what happened to each query in a window, for example `VALID`, `REPLY_SCHEMA_INVALID`, `RESPONSE_LATE`, `TIMEOUT`, or a transport code such as `REMOTE_REJECTED_403`. Outcome codes are recorded, not scored. |
| **Integrity failure, unavailability** | An integrity failure is a reply that fails identity, binding, signature, replay or media-type checks. Unavailability is a timeout, a refused connection or a rejected request. They are counted apart. |
| **Void window** | A window that cannot count, for example because admitted cases fell below the minimum (`VOID_SAMPLE_FLOOR`). It says nothing about any miner. |
