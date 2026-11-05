<p align="center"><img src="docs/assets/banner.svg" alt="SN87 · Proof of Assurance" width="100%"></p>

<p align="center">
  <a href="https://github.com/provenonce-ai/sn87-provenonce-public/actions/workflows/conformance.yml"><img src="https://github.com/provenonce-ai/sn87-provenonce-public/actions/workflows/conformance.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-C8A24B" alt="MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-0A1020" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/bittensor-testnet%20582-0A1020" alt="Bittensor testnet 582">
  <img src="https://img.shields.io/badge/status-alpha-0A1020" alt="Status: alpha">
  <a href="docs/README.md"><img src="https://img.shields.io/badge/docs-map-C8A24B" alt="Documentation map"></a>
</p>

**The run succeeded. Was it right?**

SN87 is a Bittensor subnet where miners test the difference between observed autonomous work and
a declared assurance contract, for eligible structured workflows and their evidence. This is
Proof of Assurance: each miner returns one Differential, and a validator checks it.

Provenonce and Bitstarter.ai are partnering on Proof of Assurance (Bittensor Subnet 87).
Site: <https://provenonce.ai/sn87/>. Whitepaper: <https://provenonce.ai/sn87/whitepaper/>.

## What is SN87?

An autonomous agent can finish a job and report success. That does not tell you whether the job
followed the rules it was given. SN87 asks miners that question. Each miner gets a **capsule**
(the evidence for one piece of work, with the contract it should meet) and returns one
**Differential**: its structured answer, naming any deviation and citing the evidence. A
validator scores the answer with public code. Think of an auditor who must cite page and line.

Today SN87 runs on a public test network. The scorer, the scoring profiles, the checks and the
fixtures are open under the MIT License, and you can run them on your own computer. The miners
that are weighted are all operated by Provenonce, so the results so far are conformance
evidence, not a contest between methods ([LIMITATIONS.md](LIMITATIONS.md)).

```mermaid
flowchart LR
    D["1 Define<br/>task family, profile, baseline"] --> C["2 Commit<br/>seeds published first"]
    C --> Q["3 Query<br/>capsules to miners<br/>signed requests"]
    Q --> S["4 Score<br/>one public scorer<br/>against truth"]
    S --> W["5 Weight<br/>planned uids only<br/>operator action"]
    S --> R["6 Reveal<br/>seeds revealed after close<br/>first schedule not yet revealed"]
    W --> CH[("Testnet 582")]
    R --> V["Public verifier<br/>PASS, FAIL or UNVERIFIED"]
    CH --> V
    X["Reference executors<br/>private"] -.->|"truth for hidden instances"| S
    G["Golden truth<br/>public fixtures"] -.->|"truth for public fixtures"| S
```

The full set of eight diagrams, each tied to the code, is in [docs/diagrams](docs/diagrams/README.md).
New terms are in the [glossary](docs/GLOSSARY.md).

## Who it is for

| Role | You do | You get | Start here |
|---|---|---|---|
| **Miner** | Write a method that answers capsules and serve it from your own machine | A score from the public scorer. If admitted to the shadow cohort, a published record with weight 0. No uid is admitted yet | [Miners](docs/MINERS.md) |
| **Validator** | Dispatch capsules, check and score answers, verify what others did | Public contracts, one scorer and checks you can run offline | [Validators](docs/VALIDATORS.md) |
| **Challenge author** | Describe a new task in terms the system can check | A verdict: `ADMISSIBLE`, `NEEDS_DECISION` or `INADMISSIBLE`. It activates nothing | [Challenge authors](docs/CHALLENGE_AUTHORS.md) |
| **Reviewer or researcher** | Check the claims and the limits | Each check ends in PASS, FAIL or UNVERIFIED | [Reviewers](docs/REVIEWERS.md) |

## How it works

1. **Define.** A task family is bound to a committed scoring profile and a matched public baseline.
2. **Commit.** The operator publishes seed commitments for a whole schedule before any window opens.
3. **Query.** When a window opens, fresh capsules go to miners in signed requests. Each miner
   returns one Differential.
4. **Score.** One public scorer checks integrity, compares each answer with truth and scores it
   under the profile. A shadow result is published with weight 0.
5. **Weight.** For uids named in the approved plan, estimates become a preference row and then
   u16 weights that an operator sets on testnet. Outside miners are not weighted today.
6. **Reveal.** After the window closes, the seed is to be revealed so anyone can regenerate every
   capsule and check the commitments. The reveal for the first schedule is not yet published
   ([ADR-0023](docs/architecture/ADR-0023-opening-block-seed-truth-commitment-and-reveal-deadline.md)).

Two assignment classes exist, each bound to one committed scoring profile:

| Class | Profile | Question |
|---|---|---|
| `IC-APPROVAL-APPLICABILITY` | `IC-FIRST-LIGHT-MIN-1` | Was an approval carried past a changed governing condition? |
| `TYPE-C-RELEASE` | `GRA-W03-3` | Does a release workflow trace violate its grammar? |

A miner returns one of `FINDINGS`, `NO_MATERIAL_DEVIATION` or `INSUFFICIENT_EVIDENCE_ABSTAIN`.
A validator checks the response against the wire contract, scores it with one scorer under the
committed profile, and emits a weight row or `NO_VALID_PREFERENCE_ROW`.

**Scoring in one minute.** Under `IC-FIRST-LIGHT-MIN-1`:

```text
score    = weighted geometric mean of detection (0.60), evidence (0.25), calibration (0.15)
estimate = mean score over the window's assigned cases (an invalid or missing answer counts as 0; over 10% invalid makes the method ineligible)
share    = max(estimate - 0.60, 0) ** 2, divided by the sum over methods
```

If no estimate is above 0.60 there is no row and nothing is submitted. Two methods at 1.0 and 0.8
would share 0.16 and 0.04 of the total, that is 0.8 and 0.2. This shows the rule, not a result.
The [scoring diagram](docs/diagrams/03-scoring-pipeline.md) has every step, and
[LIMITATIONS.md](LIMITATIONS.md) lists what the rule gets wrong.

## Current status

<!-- BEGIN STATUS:work_in_public -->
SN87 is live on Bittensor testnet 582. The validator's first recorded set-weights row (First Light) was applied at block 8,102,381. The attested series is 21 runs in attestation 02: it starts with `r5-20261005-a` at block 8,152,574, and its latest run, `r5-20261006-e`, landed at block 8,160,152. The code is open under the MIT License, and anyone can check the chain proof themselves with the public verifier below.
<!-- END STATUS:work_in_public -->

| Area | State | Label |
|---|---|---|
| Network | Public testnet netuid 582, alpha protocol `0.1.2`. No mainnet, production or adoption claim | **In use** |
| Weighted uids | Uids 1 and 2 only, both operated by Provenonce, in plain weight mode. Rows are conformance evidence | **In use** |
| Profile in use | `IC-FIRST-LIGHT-MIN-1` for the approval class. `GRA-W03-3` is the committed profile of the release class | **In use** |
| Shadow cohort | As the operator runs it, a uid on the allowlist is queried each window, scored and published with weight 0. The service is the operator's and is not in this repository. The allowlist here has no entries | **Open for application, allowlist empty** |
| Outside miners weighted | None. The proposed shadow-to-weighted criteria cannot be met under today's windows (strict baseline uplift, [LIMITATIONS.md](LIMITATIONS.md) item 20) | **Not available** |
| Contest protocol 0.1 | Generator, commit, reveal and verify tooling is public ([`scripts/contest_window.py`](scripts/contest_window.py)). The operator's shadow service is not in this repository, so running windows cannot be verified from here. No revealed window yet | **Tooling committed** |
| Contest protocol 0.2 | Opening-block seed, truth fixed at open, reveal deadline. Tooling and tests are committed; no schedule of this version is deployed | **Inactive** |
| Scoring profiles `IC-FIRST-LIGHT-MIN-2`, `-3`, `-4` and `GRA-RELEASE-MIN-4` | Committed. Active on no weight path | **Inactive** |
| Row-versus-pinned weight check (a row to be built or sent must equal the weights pinned by the recomputed validator receipt; a missing, empty, malformed or different row stops the step) | Implemented in scripts/weight_row_check.py and called by the commit-reveal runner in this repository. Whether the operator's own weight-setting tooling calls it is not shown here, and it is not deployed | **Committed** |
| Weight gate (a candidate must beat every public method) | Committed and tested, wired into no live weight path | **Inactive** |
| Scoring terms Eq. 2, 8, 10 and 11 | Defined, not scored. They show as `"NA"`; Eq. 11 stays neutral | **Inactive** |
| Commit-reveal weights | Payload and schedule code tested against a fake chain. No submitter, so it has not run on any chain | **Not run** |
| Truth for hidden instances | Computed by private reference executors. Not checkable outside Provenonce | **Not verifiable here** |
| Public fixtures | Per-case truth published in [`protocol/golden_truth/`](protocol/golden_truth); scoring is checkable here | **In use** |

Labels: **In use** runs today. **Open for application** has a documented route and no
guarantee. **Not available** cannot be done today. **Inactive** is committed and switched off.
**Not run** has never run on a chain. **Tooling committed** means the code is here and the operator service is not. **Committed** means the code and tests are here; whether it runs on a live path is not shown here.

## Getting started

1. **[Start here](docs/guides/start-here.md).** From a fresh clone to a result you can read, about
   20 minutes, no wallet. It says which of four levels (local, shadow, independent validation,
   weighted) it reaches.
2. **Pick your page:** [miners](docs/MINERS.md), [validators](docs/VALIDATORS.md),
   [challenge authors](docs/CHALLENGE_AUTHORS.md) or [reviewers](docs/REVIEWERS.md).
3. **Try the demo** (next section).
4. **Check a closed window** (reviewers, validators): [reproduce a window](docs/guides/reproduce-a-window.md)
   recomputes it from the published files and says what it could not check.
5. **Look up a word** in the [glossary](docs/GLOSSARY.md), or find any page in the
   [docs map](docs/README.md).

Agents and humans changing this repository: read [AGENTS.md](AGENTS.md).

## 60-second quickstart

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are the only requirements.

```bash
git clone https://github.com/provenonce-ai/sn87-provenonce-public && cd sn87-provenonce-public
uv sync --locked --extra transport
uv run sn87-provenonce demo
```

The demo runs the `institution/0.2` path, the one every weight uses. For each of three public
synthetic fixtures (`stale_authority`, `fresh_review`, `incomplete`) it builds a capsule with the
public generator, sends the canonical capsule bytes to the public miner method, takes the
canonical response bytes back, and scores them with the public scorer against the truth
published in `src/sn87_provenonce/institutional_v02/public_fixture_truth.json`. It prints one
row per case. `uv run sn87-provenonce demo --json` prints the same result as JSON.

What it shows: the capsule contract, a miner answering over the same bytes
[`scripts/miner_serve.py`](scripts/miner_serve.py) carries over localhost HTTP, and the scorer's
row. What it does not show: the signed transport, the chain, or hidden instances. It is local and
offline, the wire bytes are unsigned, the fixtures are public and synthetic, and the six
integrity predicates are asserted true rather than verified. The truth for these fixtures is
published; the reference executors that computed it are not, so you can check scoring against the
truth but not regenerate it here. The same holds for every committed public fixture, in
[`protocol/golden_truth/`](protocol/golden_truth).

The older `v0alpha1` demo is still available as `uv run sn87-provenonce demo --legacy-v0alpha1`.
It is research code on no weight path, and it fixes its signature, nonce, policy and evidence
checks to true.

To check the chain proof, run the verifier (next section). To serve a miner, see
[Run a miner](#run-a-miner).

## Run a miner

```bash
uv sync --locked
uv run python scripts/miner_serve.py --role candidate --port 8787
curl http://127.0.0.1:8787/health      # in a second terminal
```

`miner_serve.py` serves one miner over an unsigned localhost HTTP boundary (development only):
canonical capsule bytes in, canonical response bytes out. It binds loopback only, holds no key and
writes nothing to a chain. `--role candidate` is the Provenonce-written example method
(`miners/witness_ic.py`); `--role baseline` is the matched public-contract baseline. To write your
own method, put a function with the same shape next to `witness_ic.py`, or serve it with
`sn87-miner serve --method package.module:function` (below).

The signed endpoint that validators call (`POST /v1/assurance`, `btauth/1`, shared Valkey replay
store) runs the same method with your hotkey:

```bash
uv sync --locked --extra transport
uv run sn87-miner serve --role candidate --hotkey-keyfile PATH --netuid 582 \
  --valkey-url redis://127.0.0.1:6379/0 --check      # then without --check
```

`--check` starts nothing, but it reads the validator-permit list from the chain once, so it needs a node
(`--allow-any-sender` skips that read, for local rehearsal only).

[The miner guide](docs/guides/miner-guide.md) takes one sitting: install, write and score a method,
run the signed endpoint, sign an announcement, and see what is still missing before a score on the
test network.

[The shadow cohort page](docs/guides/shadow-cohort.md) says how an outside miner applies to be
scored and published with weight 0, and the proposed criteria for anything beyond that.

[docs/quickstart/miner.md](docs/quickstart/miner.md) shows a request against a fixture capsule,
the wire rules, the signed endpoint and how to announce it
([docs/protocol/miner-announcement.md](docs/protocol/miner-announcement.md)). Registering a hotkey
and anything on a chain is yours to do with your own wallet; this repository does not do it for
you.

## Run a validator

What is public: the wire contracts, the integrity gate, the one scorer, the committed profiles,
the evidence bundle, the signed transport, the weight quantizer, the staging validator
(`scripts/staging_subnet.py`) and the per-case truth of the committed public fixtures
(`protocol/golden_truth/`). With those you can run the staging validator on the public fixtures,
score miners against the published truth and reproduce the attested validator digest. What is
private: the reference executors, which compute truth for any capsule and so are the answer key
for hidden instances. A validator for hidden instances therefore cannot be run from this
repository alone (it also needs a source of truth for those instances, an open decision); see
[docs/quickstart/validator.md](docs/quickstart/validator.md) for what you can run and check.

## Verify the chain proof yourself

[attestation/](attestation) holds two self-digested lists of completed testnet runs (no
signatures, no keys): for each, the block in which the validator set
weights on netuid 582 and the row it set. The checker reads the chain and compares:

```bash
uv run --extra transport python scripts/verify_attestation.py
```

It needs the public testnet node and nothing else: no wallet, no key, no account. It runs under
a throwaway home directory and cannot send anything to the chain. Each check ends in PASS (ran,
claim holds), FAIL (ran, claim does not hold) or UNVERIFIED (could not run here, nothing claimed).

Real output, trimmed. Generated by `scripts/render_verifier_output.py`, which runs the verifier
and rewrites this block; `--check` recomputes the offline lines (no network):

<!-- BEGIN VERIFIER_OUTPUT -->
```
integrity  PASS  digest recomputes (sha256:57af3c99d683fd3c868bfe6cbcc3353451fab70f70c2a374c0eec11a9c552b7a)
published truth: 75 cases in 2 files under protocol/golden_truth, digest sha256:5fadbfcc983f7b9fb8ff1d8595e8c5dc05ae910299d6549e5347bfe805f80353
  validator  PASS  validator pinned digest recomputes from published truth and the public scorer (seed 0, 2026-10-04T00:00:00Z; sha256:6a03fa60322 ...
  weights    PASS  attested row equals the pinned weights (uids [1, 2], u16 weights [65535, 65535])
  plan       UNVERIFIED  UNVERIFIED: the plan document is built by Provenonce-private operator tooling from files that are not published
reproduces offline: UNVERIFIED  (43 PASS / 0 FAIL / 21 UNVERIFIED of 64 checks: integrity + plan, validator and weights for 21 runs)
run r5-20261005-a  block 8152574  PASS  uid 0 set weights in exactly block 8152574 (LastUpdate 8102381 at block 8152573, 8152574 at block 8152574) ...
chain corroboration: PASS  (21 PASS / 0 FAIL / 0 UNVERIFIED of 21 runs)
OVERALL UNVERIFIED: 0/21 runs PASS, 0 FAIL, 21 UNVERIFIED
SUMMARY integrity: PASS; chain: 21/21 PASS; scoring: validator 21/21 PASS; weights 21/21 PASS; plan 0/21 PASS, 21 UNVERIFIED (the plan document is built by Provenonce-private operator tooling from files that are not published)
exit code 3 (0 = PASS, 1 = FAIL, 3 = UNVERIFIED)
```
<!-- END VERIFIER_OUTPUT -->

How to read it. The integrity, validator and chain checks run from public inputs. The validator
check recomputes the pinned validator digest in process, from the published per-case truth for the
committed public fixtures ([`protocol/golden_truth/`](protocol/golden_truth)) and the public
scorer, with no reference executor; it is PASS when the digest equals the attested one and FAIL
when it does not. The plan check stays UNVERIFIED outside Provenonce: the plan digest covers a
plan document built by Provenonce-private operator tooling from files that are not published, so
it is not computed here and not claimed. One UNVERIFIED check keeps the overall verdict
UNVERIFIED. Exit codes: 0 = PASS, 1 = FAIL, 3 = UNVERIFIED.
[attestation/README.md](attestation/README.md) lists what the checker proves and what it does not.

### Which methods hold uids 1 and 2

The attested weight rows name uids 1 and 2 only; a row names uids, not methods. The table below
says which method each uid stands for, when, and on what basis. It is generated from data (see the note in the block), not typed.

<!-- BEGIN UID_TABLE -->
Testnet netuid 582, mechanism 0. Generated by `scripts/render_uid_table.py` from `attestation/TESTNET_582_PARTICIPANTS.json`; `--check` fails if this table drifts from that file or from the attestation.

| uid | hotkey | method | role | from block | weight row | basis for the method |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `5H6U3sdsYP4c27VuVvQ1JbfVyCWPHjeqiifHBHHXgj5vccjw` | none (validator) | validator | not recorded | not applicable | not applicable |
| 1 | `5CFoMvioksya5AYP9WAKRptwQR7tgtcKPhwcb6W79UbYaLPF` | `state_machine` | reference | 8,102,381 | First Light row | First Light weight row and run record |
| 1 | `5CFoMvioksya5AYP9WAKRptwQR7tgtcKPhwcb6W79UbYaLPF` | `approval_witness` | candidate | 8,152,574 | attested runs (attestation 01 and 02) | private naming binding; not verifiable from public files |
| 2 | `5GusuV1QhzkX22zjAGrBE29ybEQqF2aj84ooDYv7JJeo8TsC` | `relational` | reference | 8,102,381 | First Light row | First Light weight row and run record |
| 2 | `5GusuV1QhzkX22zjAGrBE29ybEQqF2aj84ooDYv7JJeo8TsC` | `baseline_miner` | baseline | 8,152,574 | attested runs (attestation 01 and 02) | private naming binding; not verifiable from public files |

- The same two hotkeys hold uids 1 and 2 throughout. What differs between the two periods is which methods the weight row is said to name for those uids.
- A weight row names uids, not methods. The attestation files carry only the uids (1 and 2, 65535 each). For the attested runs, the method behind each uid comes from a naming binding that Provenonce records privately; it is not independently verifiable from public files, and its approval is not citable here. It is a naming choice, not an identity proof: nothing shows that a process behind either hotkey runs the method named for it.
- The block at which each hotkey was registered is not recorded in this repository. The from block is the first block at which a weight row naming the uid is recorded.
- `state_machine`: Provenonce reference algorithm; also computes truth.
- `relational`: Provenonce reference algorithm; also computes truth.
- `approval_witness`: The replaceable Provenonce-written candidate (miners/witness_ic.py).
- `baseline_miner`: The public-contract baseline algorithm run as a miner.
<!-- END UID_TABLE -->

## Supported platforms

Linux and macOS are supported and tested in CI (Python 3.12 and 3.13). Windows is supported
through WSL2. Native Windows is not supported. Evidence bundles open every directory and file
through a descriptor with `O_DIRECTORY` and `O_NOFOLLOW`, so a symbolic link swapped in while a
bundle is read or written cannot redirect it. Native Windows has no equivalent, and the code
fails closed there ("unsupported on this platform") instead of falling back to path checks
that a concurrent link swap can defeat. The verifier also looks up the real home directory
through the `pwd` database, which native Windows lacks. On the verifier, bundle and CLI import path, `pwd` is imported only where it is used, so
importing them does not fail on any platform.

## Repository map

```text
src/sn87_provenonce/   the package
  scoring.py           the one scorer
  profile.py           loader for the committed scoring profiles in profiles/
  classes.py           task families bound to validators, generator, baseline and profile
  baselines.py         the matched public-contract baseline
  miners/              the example candidate method (witness_ic.py)
  pilot/               signed HTTP client and server, replay store, sender policy
  miner_node/          the sn87-miner command: serve, probe, announce
  bundle.py            evidence bundle and the weight gate
  weights_dry_run.py   u16 weight quantizer; never broadcasts
scripts/               contest windows and results, admission, verifier, local miner server
protocol/              schemas, test vectors and the published truth in golden_truth/
attestation/           self-digested lists of testnet runs, and the participants file
shadow/                shadow cohort allowlist and the proposed criteria
examples/              challenge proposals, a demo contest window, a sensitivity example
docs/                  guides, quickstarts, protocol, decisions, diagrams, glossary
changes/               one note per visible change; they become the release notes
tests/                 the public test suite
```

## Honest limits

- Testnet only, alpha. No mainnet, production or adoption claim.
- All miners are operated by Provenonce, so the rows are conformance evidence for transport,
  integrity and arithmetic, not method competition.
- The task fixtures are illustrative.
- Scoring of the committed public fixtures is checkable here against published truth. The plan
  digest and scoring of hidden instances are not, so a public verifier run still ends UNVERIFIED
  (exit code 3, with the integrity, validator and chain checks PASS).
- The public baseline scores the same as the reference methods on the committed families
  (`NULL_NO_HEADROOM`), so a score of 1 shows agreement, not skill.

Read [LIMITATIONS.md](LIMITATIONS.md) before citing any result.

## What is private

The reference executors (the code that computes the expected truth) are private, and so are the
tools Provenonce uses to operate its validator. The truth they produce for the committed public
fixtures is published; the truth for any hidden instance is not. Anything that needs the private
parts is labelled "not verifiable outside Provenonce". The attestation records carry two digests
of Provenonce's output. The validator result is recomputed publicly from the published truth. The
approved plan is built by the private operator tooling, so only Provenonce can recompute it.
Benchmark supply and operations are maintained privately.

Commitments to the private executor files (SHA-256 of each file at this release; a hash of a
private file, not the file):

```
a74ac883e3c3deb912cf6107e83aed3072f3c89424fd59b6a8e54a087c31c0b1  institutional_v02/references.py
4ca7a7cc902c89bbe6f59b772cdbcad060dc04e732a3931bb07bba290214ad03  pilot/reference.py
c7b1cfc5af6b1e97da4a9cf9fac689c0adba774d6cfdf3439e678f7eee1332e4  simulation/type_c_reference.py
```

## Develop

```bash
uv sync --locked --all-extras
uv run ruff check .
uv run pytest
```

Some tests skip without the private executors; each skip says so. The scorer tests that can run
against the published truth do. CI runs the same steps
([conformance.yml](.github/workflows/conformance.yml)). See [CONTRIBUTING.md](CONTRIBUTING.md).

## Docs

Start at the [docs map](docs/README.md). It lists every page with its audience and purpose.

- [LIMITATIONS.md](LIMITATIONS.md) and [PROVENANCE.md](PROVENANCE.md)
- [Glossary](docs/GLOSSARY.md) and [diagrams](docs/diagrams/README.md)
- [Implementation status](docs/protocol/implementation-status.md) (implemented, enabled, tested, deployed)
- [Profile application](docs/protocol/profile-application.md), [wire rules](docs/protocol/wire-rules.md), [evidence bundle](docs/protocol/evidence-bundle.md), [v0alpha1 field traceability](docs/protocol/v0alpha1-field-traceability.md)
- Quickstarts (drafts): [miner](docs/quickstart/miner.md), [validator](docs/quickstart/validator.md)
- Guides that CI runs command by command: [reviewer test guide](docs/guides/reviewer-test-guide.md); [reproduce a window](docs/guides/reproduce-a-window.md); [guide format and runner](docs/protocol/guide-format.md)
- Research code, local only: [simulation](docs/simulation), [runtime](docs/runtime), [sensitivity example](examples/sensitivity/README.md)
- [Whitepaper policy](docs/whitepaper/README.md), [CHANGELOG](CHANGELOG.md)
- Decisions: [docs/architecture](docs/architecture) (ADR-0001 to ADR-0024)

## Community

- Site: <https://provenonce.ai/sn87/>. Whitepaper: <https://provenonce.ai/sn87/whitepaper/>.
- Questions and bugs: the [issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose).
  Questions also go to the "SN87, Provenonce" Telegram group linked from the site FAQ.

## License and contact

Developed by Provenonce, Inc. under the authority of Will O'Brien, Founder & CEO.
Copyright (c) 2026 Provenonce, Inc. Licensed under the MIT License (see [LICENSE](LICENSE)).
Provenonce and Bitstarter.ai are partnering on Proof of Assurance (Bittensor Subnet 87).
Report security issues privately to ops@provenonce.co (see [SECURITY.md](SECURITY.md)).
