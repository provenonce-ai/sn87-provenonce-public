# Changelog

This file records durable product milestones. Development chronology and internal operating
notes are maintained outside the repository.

## Unreleased

Changes waiting for the next release are written as short notes in `changes/` (see
`changes/README.md`) and assembled into a new section here by `scripts/release_notes.py`
when a version is cut.

## [0.1.1] - 2026-11-05

Contest protocol 0.2 and shadow cohort tooling

### Added

- Admission can now build a window result for any scored profile from a window results document instead of by hand, and an admission report lists, as a flag that changes no verdict, the other uids and public methods that gave the same decisions on every scored case (SHARES_DECISION_GROUP_WITH); whether that should count is left as a decision in the admission document.
- A new command, `sn87-provenonce challenge check PROPOSAL.json`, reads a challenge proposal (intended consumer, evidence rights, truth source and oracle class, scoring, baselines, budget, headroom) and prints ADMISSIBLE, NEEDS_DECISION or INADMISSIBLE with reason codes; see docs/guides/propose-a-challenge.md. It activates nothing.
- An offline end-to-end test now walks one contest window from the committed schedule to the summary a miner reads, through the real signed transport and sender policy, with fake miners that are honest, copied, late, malformed, wrong-capsule, unpermitted or unannounced, and records which of 13 stages it exercises and where components do not yet connect; the inactive MIN-4 profile is scored beside the active one and labelled as such. (a private test; not in this repository)
- Contest windows have a new protocol version 0.2 for new schedules: the opening block hash is mixed into each window seed, the truth hash is fixed at open and sent in every request to a miner, and `publish-truth`, `verify` and the results tool refuse a truth that differs from it. Version 0.1 windows still verify. See ADR-0023 and docs/protocol/contest-windows.md.
- The docs map, README, reviewer and validator pages and diagram 04 now link the reproduce-a-window guide in place of the "coming in this release" notes; the weight-flow diagram and glossary state that a weighted plan version needs an eligible gate verdict and that admission reports carry the decision-group flag. The window reproduction fixture's derived record was regenerated so its admission report carries the new flag field.
- A new candidate task family built for headroom is registered as inactive: delegated-authority traces whose truth is fixed when each instance is built, with a committed profile. It is bound to no class, weight path or default, and the weight gate refuses it. See ADR-0024. Its headroom result is negative (ADR-0024); only the profile document is published here.
- Two new scoring profiles, IC-FIRST-LIGHT-MIN-4 and a new Type C profile (ADR-0022), keep every constant answer below the threshold by construction, score calibration over a fixed set of outcomes, score declared severity, charge for over-citing and make identical answers share one weight. They are committed and not active on any weight path.
- A new redundancy module groups identities that give identical answers and records simultaneous-dispatch, response-time and identical-answer flags in window results under the new profiles; the flags are never scored.
- A second party can now recompute a closed contest window from its published files with `scripts/reproduce_window.py`: commitments, seed, cases, truth commitment, outcome codes, scores, preference and weight rows, weight gate and admission verdict each print PASS, FAIL or UNVERIFIED, and a closing statement says what was and was not reproduced. See docs/guides/reproduce-a-window.md; a synthetic window to try it on is in examples/window-repro-fixture/.
- `shadow_cohort.py check-config --online` now also looks up an opening block on the configured node, which needs a node that keeps old state, and fails with `OPENING_BLOCK_LOOKUP_FAILED` when it cannot. (Operator service code; not in this repository and not yet deployed.)
- A new page, docs/guides/shadow-cohort.md, sets out the admission criteria for the shadow cohort (outside uids that are scored and published with weight 0), with an issue form to apply and a proposed criteria file at shadow/criteria-proposed.json. The miner guide, the contest-windows quickstart and the admission document now point to it.
- The shadow service now records, for every query it sends, when it was dispatched and when a reply arrived as milliseconds from the start of the window's queries (a monotonic reading, never a wall-clock time), publishes them in the window's responses file, and the window results read them, so the simultaneous-dispatch and response-time flags can fire under the new profiles. (Operator service code; not in this repository and not yet deployed.)
- The shadow service can score inactive profiles named in an optional `report_profiles` setting beside the two it always scores and publish them with `profile_status: INACTIVE`, stage shadow and weight 0, including redundancy groups and flags; the default is unchanged, and a schedule is refused when its windows are sized below a report profile's minimum (MIN-4 needs at least 36 scored cases). (Operator service code; not in this repository and not yet deployed.)
- The shadow service now gives every 0.2 window a reveal deadline and marks a window `REVEAL_OVERDUE` in the index and the log when it passes with no reveal uploaded. `shadow_cohort.py reveal-schedule` derives and checks every window seed of a committed schedule into one bundle, and the public `verify-bundle` phase of `contest_window.py` checks it from the published commitments alone. (Operator service code; not in this repository and not yet deployed.)
- A new page, docs/guides/start-here.md, takes a newcomer from a fresh clone to a readable local result in about 20 minutes: prerequisites, setup, the demo and the staging run, how to read PASS, FAIL, UNVERIFIED and a baseline tie, and a table that keeps local example, shadow participation, independent validation and weighted apart. A new script, scripts/clean_slate_smoke.py, runs that page from a clean clone of the committed tree.
- Each shadow window row now lists, under responses.case_outcomes, one outcome code for every query sent to a miner (VALID, REPLY_SCHEMA_INVALID, RESPONSE_LATE, TIMEOUT, a NOT_QUERIED code or a transport code), with responses.case_outcomes_status RECORDED; none is scored. A window resumed from a ledger written before this change or with unusable case_outcomes publishes {} with the status NOT_RECORDED_LEGACY_LEDGER. A repeated query id is a validator fault: nothing is queried and no miner is blamed. (Operator service code; not in this repository and not yet deployed.)
- `sn87-miner serve` takes a repeatable `--trusted-sender SS58` (at most 8, `--probe-hotkey` is one of them): a trusted hotkey may send without validator permit but is still signature-checked and rate limited, and is listed at start-up. A shadow cohort miner adds the shadow service address this way; see the miner guide, "Who may send".
- The comparison against public methods is now a binding gate in `bundle.py`: a family is weight-eligible only if a candidate beats every public method, `approval_witness` included, a tie is `NULL_NO_HEADROOM` and refuses, and a family whose public methods all sit at the ceiling is marked `RETIRE_RECOMMENDED`. The gate is a check weighting tools must call and is wired into no live weight path; the optional `weight_gate` bundle section exposes it.

### Changed

- The proposed shadow-to-weighted criteria now also require the uid's estimate to be strictly above the public baseline's on the same scored instances in every checked window. The criteria stay proposed and have a new digest; see `shadow/criteria-proposed.json` and the admission document.
- Contest protocol 0.2 pins the opening block by time (checked offline), refuses a hand-typed block unless `--allow-manual-block`, reads only final blocks, derives the truth salt so a lost truth file is made again, caps reveal deadlines at seven days, and ties every reveal in a bundle to the published open record. See ADR-0023.
- Every source permission now declares an export class (an external export or a fictional fixture), which is part of the permission digest; a missing, unknown or conflicting class is refused, and keys for keyed commitments must have enough variety. Window results also record that the baseline scored every instance, and the criteria name the profiles they accept.
- The weight gate can now take a family's public methods and its preregistered minimum effect from a closed list registered once per family, refuses a caller that leaves any registered method out, and treats a lead under the minimum effect as `NULL_NO_HEADROOM`. Existing families and `candidate_gate` calls behave as before. See ADR-0024.
- A weighted plan version can only be proposed when the window's baseline-headroom gate verdict, recomputed from the window's estimates, says the candidate is above every public method; a weighted entry without an eligible verdict does not verify. The gate is wired into no weight write.
- Identical-answer grouping under the new profiles now keys on the declared state and set of finding codes per case, and the scorer computes the groups from the answers and refuses a caller grouping that disagrees; the loader also takes family truth states from the committed class and requires a positive calibration weight.
- A rejected request is now recorded as `REMOTE_REJECTED_<status>`, and a 422 as `MINER_REJECTED_ENVELOPE`, so a miner that does not know a request field is distinguishable from one that refuses the sender. See the miner guide error table.
- The shadow service now spaces its sends to each miner (default 4 per second, optional config key `max_queries_per_second`) so a window's cases stay under a miner's default per-sender rate limit, and the window record states the pacing under `query_pacing`. (Operator service code; not in this repository and not yet deployed.)
- The shadow service can sign its challenges with one stable transport key, read from a key file named by the new optional config key `signer_keyfile` (mode 0600; not a wallet, never registered); `shadow_cohort.py signer-address` prints its address. Without it the service refuses to run with `SIGNER_NOT_CONFIGURED`, except in rehearsal mode, where it signs with a random key and warns that miners on the sender allowlist will refuse it. (Operator service code; not in this repository and not yet deployed.)
- The attestation verifier now also compares each attested weight row with the weights pinned by the recomputed validator receipt, and reports a different uid list or u16 value as FAIL. If no pinned weights could be recomputed, the weights check is UNVERIFIED, never PASS.
- The signed miner request envelope accepts an optional `window_commitments` object (the contest window open record). A miner built before this change rejects it, so update `sn87-miner` before the first 0.2 window opens.

### Fixed

- The evaluation bundle (`bundle.evaluate`) now passes each candidate's scored answers to the preference row, so a run under `IC-FIRST-LIGHT-MIN-4` or `GRA-RELEASE-MIN-4` no longer stops with `REDUNDANCY_ANSWERS_REQUIRED`; identities that answer alike share one weight, as ADR-0022 says.
- The window reproduction kit now fails a result scored under a profile other than the committed one, takes stages and uids from the submissions rather than the derived record, adds a line for whether the open record is the one seen at open, and states that an operator who controls every file can produce a set that passes. Free text of replies is no longer published in the fixture.

### Security

- The build backend is pinned to an exact version (hatchling 1.33.0) instead of a range, so a package build uses the same backend every time.
- The package build now runs from a hash-pinned build environment (`requirements/build.txt`: hatchling and all its dependencies at exact versions with their file hashes), used as a build constraint with `--require-hashes` in CI, the exported workflow and the documented commands. A changed or substituted build dependency fails the build.
- The developer and CI install now builds the project from the hash-verified build environment: `requirements/build.txt` (now also pinning `editables`) is installed with `--require-hashes`, then `uv sync --locked --no-build-isolation-package sn87-provenonce` builds the editable project with it, and CI runs `uv run --no-sync`. A tampered build hash fails the install, and a missing build environment fails the sync. The plain `uv sync` in the newcomer docs keeps uv's unhashed isolated build; AGENTS.md records that remaining gap.
- `sn87-miner serve` now accepts requests only from hotkeys that hold validator permit on the subnet (read from the chain in the background, once per epoch), plus the probe hotkey and up to 8 `--trusted-sender` hotkeys you name, behind per-sender and global rate limits; refused senders get a defined error and never reach your method. It is on by default; `--allow-any-sender` turns it off for local development (loopback only), and `sn87-miner probe` takes `--probe-hotkey-keyfile`. See the miner guide, "Who may send".
- The shadow service now loads its signing key at start-up and refuses a missing key file (outside a rehearsal), a path inside a wallet folder, a file owned by another user, and a key that is a registered hotkey on the subnet. When a key is configured, the shadow page shows its address so miners can trust it with `--trusted-sender`. (Operator service code; not in this repository and not yet deployed.)
- Text commitments in a source labelled as an external export now use HMAC-SHA256 under a key the data owner holds and passes in, so a guessable text cannot be confirmed by hashing candidates; the mapping refuses such an export without a key, and earlier plain commitments still verify under their own mapping version. See `sources/mapping.py` and LIMITATIONS item 19.

### Docs

- The README now follows a fixed outline (what it is, who it is for, how it works, current status, getting started, honest limits), and there are new pages for miners, validators, challenge authors and reviewers, a glossary, a docs map and eight diagrams of how the system works, each tied to the code it describes. Start at docs/README.md.
- LIMITATIONS items 3, 16 and 18 now describe the new profiles and what their pool bound covers, and the contract documentation says the rationale is required but not scored.
- LIMITATIONS item 17 now says plainly that for the current capsule-computed families the private reference executors are load-bearing and the operator dependence remains, and that "open code, hidden instances" holds only for families whose truth is fixed at build time (ADR-0021).
- The shadow guide now says what the opening block hash does and does not do (it removes advance knowledge only), and what a 0.2 window lets you check about its truth.
- The implementation-status page lists the sender allowlist, contest protocol 0.2, the MIN-4 profiles, the weight gate, keyed text commitments and the admission uplift rule with their state, and the weight-flow diagram and README describe the row-versus-pinned weight check as committed, with no claim that it runs on the live path.

## [0.1.0] - 2026-10-08

### Added

- New tooling, tests and documents describe how an outside miner could move from local to shadow to weighted through approved plan versions, how weights could be submitted on a commit-reveal subnet (tested against a fake chain only), and what a second validator needs; see `docs/protocol/admission.md` and `docs/protocol/second-validator-readiness.md`. Nothing here changes the live plan or sends anything to a chain.
- `scripts/verify_attestation.py` checks the testnet attestation files against the chain with a small read-only client (`scripts/chain_read.py`) and reports each check as PASS, FAIL or UNVERIFIED. Checks that need unpublished reference code report UNVERIFIED instead of being skipped.
- Contest windows can now be rehearsed offline: a seed is committed before a window, fresh cases are generated from it, per-window results are published after close, and the seed is revealed so anyone can check the commitment. A new profile, IC-FIRST-LIGHT-MIN-3, sizes windows so one reference failure no longer voids them; it is not active and sets no weights. See docs/quickstart/contest-windows.md.
- `scripts/check_doc_paths.py` fails when a document or script links to, or names, a repository file that does not exist, so a moved file cannot leave a dangling pointer.
- The expected result for each public fixture case is published in `src/sn87_provenonce/institutional_v02/public_fixture_truth.json`, bound to the case's evidence commitment, so the demo output can be compared with a record.
- Issues now start from a chooser with three forms: setup failure, scoring question and security report. `scripts/check_issue_templates.py` checks the forms in CI, and blank issues are off so each report says what is needed to act on it.
- One public miner guide, `docs/guides/miner-guide.md`, takes a newcomer from install to a signed, probed and announced endpoint with the expected output after every command, and states plainly which last step (a score on the test network) is not available yet and what it depends on. Its commands run in CI, and its error-code table is checked against the source.
- The miner kit is published: the miner methods, the localhost miner server (`scripts/miner_serve.py`) and a quickstart for running one. The scorer, canonical encoding and evidence bundle it relies on ship with it.
- A new scoring profile, `IC-FIRST-LIGHT-MIN-2`, is committed but not active on any weight path. It pays a correct abstention, records a wrong-scope answer as an abstention, and scores citations by precision; the earlier profiles score exactly as before.
- The expected scores for the public fixtures are now published, so anyone can recompute the validator digest with the verifier on their own machine and no longer needs anything from Provenonce to check it. The design note is ADR-0021 in docs/architecture.
- The `sn87-provenonce demo` command now runs the `institution/0.2` path on three public synthetic fixtures (`stale_authority`, `fresh_review`, `incomplete`) and prints one scored row per case. It works offline in one process; the earlier `v0alpha1` demo stays available with `--legacy-v0alpha1`.
- The read-only chain client can read the current registration cost of a subnet, so the miner guide prints it from the chain at run time instead of quoting a figure.
- The table of which method each testnet 582 uid stands for is now generated by `scripts/render_uid_table.py` from `attestation/TESTNET_582_PARTICIPANTS.json` and cross-checked against the attestation files. `--check` fails when a README table drifts from the data.

### Changed

- The guide runner can start a private replay store for a step marked `requires-valkey`, stops any server a step leaves running when the step ends, and keeps loopback addresses reachable in offline steps, so a guide can start a local server and talk to it.
- Supported platforms are now stated: Linux and macOS are tested in CI on Python 3.12 and 3.13, and Windows is supported through WSL2. Native Windows is not supported, and evidence bundles fail closed there instead of falling back to weaker path checks.

### Fixed

- The guide runner now serves the tree under test to a guide's `git clone` through git's own transport instead of the local-clone shortcut, which removes an intermittent clone failure seen on macOS runners.

### Docs

- A new test module shows where the candidate and the baseline differ on edited capsules built from the public fixture generator, and LIMITATIONS.md and the reviewer guide now say the tie holds on the published fixtures only.
- CONTRIBUTING.md now explains how to file an issue, what each form asks for, how maintainers triage, and how a builder adds a new task family as a class binding.
- The architecture decision on signed HTTP and the replay boundary, the status matrix and the evidence bundle description were brought into agreement, and documents that cite files from the unpublished test suite now say so.
- The agent guide, the validator quickstart and the reviewer test guide now say exactly what is public: the one scorer, the committed profiles, the published truth for the public fixtures and the verifier. Only the reference executors, hidden-instance truth and operator tooling are private.
- Release notes are now assembled from short notes kept in `changes/`, with a CI check on their wording and a check that pull requests touching code or documents carry one. CONTRIBUTING.md has the rules, and docs/releases/RELEASING.md describes the release steps.

### Compatibility

- Weights version key: the code sets none of its own. The weight-submission scripts read the subnet's `WeightsVersionKey` from the chain at submit time and send that value; the last recorded readback for testnet 582 is 0. A miner pins to this tag for the code and reads the key from the chain.
- Profiles carried: the validator scores with the Type C release profile (commitment `sha256:e732ea977497a6ccd5e9541c8fd98bc949086ade5cbeccb058a38312329eda21`) and `IC-FIRST-LIGHT-MIN-1` (commitment `sha256:7049f165bc9b4fae32133f2d37aa9a48f5bf13f3b4fa47ea94643e5633d3c766`). `IC-FIRST-LIGHT-MIN-2` and `IC-FIRST-LIGHT-MIN-3` are committed, bound to no class or weight path, and set no weights. All are pinned in `src/sn87_provenonce/profile.py`.
- Scorer: the one scorer in `src/sn87_provenonce/scoring.py` (whitepaper v0.7.2 equations), with canonicalizer `gra/0.1`. It carries no separate version number; this tag identifies it.
- Attestation: `attestation/SN87_TESTNET_ATTESTATION_02.json` (21 runs, netuid 582, digest `sha256:57af3c99d683fd3c868bfe6cbcc3353451fab70f70c2a374c0eec11a9c552b7a`) backs the run counts; `attestation/SN87_TESTNET_ATTESTATION_01.json` (8 runs) is the earlier record.
- Commit and CI: the tag goes on the merge commit of this release; its Linux and macOS results on Python 3.12 and 3.13 are on that commit.
- Package version: `0.1.0` (was `0.1.0a0`). The protocol remains alpha and testnet only.

## Before the first release

Earlier entries, kept as written before release notes were assembled from `changes/`.

- Scoring profile `IC-FIRST-LIGHT-MIN-2` (ADR-0019), committed and not active on any weight path:
  a 3 x 3 state-by-truth payoff matrix that pays a correct abstention, the wrong-scope rule
  recorded as abstention on record, and a precision-aware citation rule, declared in an optional
  `scoring_rules` block. Profiles without the block (the two earlier profiles) score
  byte for byte as before.
- Miner launch: `sn87-miner serve` runs a miner method behind the signed endpoint
  (`pilot.server.create_app`, `btauth/1`, Valkey replay store) with a hotkey from a key file or an
  environment variable; `--check` validates the configuration; `sn87-miner probe` self-tests a
  running endpoint. `scripts/miner_serve.py` is now the unsigned loopback development mode of the
  same launcher and shares the method interface and canonical bytes. `sn87-miner announce`
  signs an endpoint announcement record (`docs/protocol/miner-announcement.md`). The signed
  transport tests are public (`tests/transport`) and run against a Valkey container in CI.
- Public export: the miner kit (`miners/`, `scripts/miner_serve.py`), the protocol, schemas and
  canonical modules, the scorer and evidence bundle, the local simulations and the attestation
  verifier are published. `scripts/verify_attestation.py` and the read-only chain client
  `scripts/chain_read.py` check every attested weight-set against the chain. The reference
  executors and the operator tooling stay private.
- Published per-case truth for the committed public fixtures (`protocol/golden_truth/`, read by
  `scripts/golden_truth.py`), bound to each capsule by its evidence commitment. The staging
  validator (`scripts/staging_subnet.py`) is public and takes its truth from those files; the
  attestation verifier recomputes the validator pinned digest from them, so that check is PASS or
  FAIL outside Provenonce. The plan check stays UNVERIFIED (private operator tooling). Scorer
  tests that used the executors now also run against the published truth.
- `PUBLIC_MANIFEST.json` classifies every tracked file of the source repository exactly once
  (allow, private, review_required, deny); `scripts/check_manifest.py` enforces it.
- Evidence bundle schema 0.3 (additive): `manifest.profile_document` and `profile_commitment_domain` carry the
  committed profile so readers verify the Eq. 13-15 gate values against `profile_commitment` instead of
  copying them.
- Evidence bundle schema 0.2 (additive): FIXTURE bundles carry per-case records (`cases`) so the
  equations can be recomputed from public data; REPLAY/LIVE never do.
- Status matrix: the composite row is relabelled "Eq.12 composite (Eq.9 per-perturbation base:
  no separate code)", correcting an overclaim in the status matrix.

### Release notes draft (scorer rebuild; not a release)

- Scorer rebuild: one profile family, one canonicalizer, one scorer, one evidence bundle. Breaking for code
  written against the earlier layout: removed `pilot/scoring.py`, `pilot/serialization.py`,
  `pilot/fixtures.py`, `institutional_v02/scoring.py`, `institutional_v02/serialization.py`;
  scorers have no defaults; `score_response(binding, ...)`, `epoch_estimate(..., profile)`,
  `preference_row(..., profile)`, `wire`. See `docs/releases/MIGRATION-scorer-rebuild.md`.

### Changed

- Added `LIMITATIONS.md`, `PROVENANCE.md`, `PUBLIC_MANIFEST.json`, `AGENTS.md`, draft miner and
  validator quickstarts, and protocol docs for profile application, wire rules and the evidence bundle.
- Rebuilt the implementation-status matrix as implemented / enabled / tested / deployed.
- Replaced "not testnet-ready" and "pre-release" wording with the actual status: alpha protocol,
  public testnet netuid 582, conformance evidence only.

## milestone/source-preserving-evidence-integrity-v0alpha1

### Changed

- Unified every evidence-bundle shape on one fail-closed filesystem boundary.
- Added componentwise no-follow parent traversal, mandatory platform controls, normalized
  descriptor and path failures, and bounded source-file reads.
- Pinned exact compatibility hashes for all files in the disclosed sensitivity and reference
  Type-C candidate bundles.
- Added adversarial coverage for parent-link races, intermediate parent links, unavailable
  platform controls, invalid paths, and descriptor metadata failures.

## milestone/shared-evidence-integrity-v0alpha1

### Changed

- Anchored every reusable two-file evidence writer and verifier to retained directory and file
  descriptors.
- Added bounded reads, exact canonical-snapshot checks, exclusive no-follow creation, single-link
  enforcement, and final path-identity verification.
- Added adversarial coverage for entry races, membership injection, concurrent mutation,
  directory substitution, hard links, and output ceilings.

## milestone/type-c-artifact-evidence-integrity-v0alpha1

### Changed

- Anchored offline Type-C evidence creation and verification to one directory descriptor.
- Added exclusive no-follow entry creation, single-link checks, stable closing snapshots, and
  directory-identity verification.
- Added caller-safe evidence failures and adversarial coverage for raced links, path substitution,
  membership injection, and concurrent mutation.

## milestone/strict-sensitivity-evidence-schemas-v0alpha1

### Added

- Strict typed contracts for sensitivity analysis results, evidence reports, and manifests.
- Generated JSON Schemas for the complete output structures.
- Bounded public parsers and internal binding validation for specifications, estimators,
  scenarios, relations, source hashes, and commitments.

## milestone/public-sensitivity-conformance-vector-v0alpha1

### Added

- A disclosed, non-normative task profile and sensitivity-analysis specification.
- Exact rational golden results and commitments for the public CLI path.
- End-to-end conformance coverage from policy-identity preimages through evidence reconstruction.

## milestone/transparent-sensitivity-evidence-v0alpha1

### Added

- Bounded offline sensitivity-spec ingestion and deterministic analysis CLI.
- Create-only evidence bundles that preserve exact source bytes and reconstruct results.
- Verification for exact membership, canonical report and manifest bytes, raw hashes, and
  semantic commitments.

## milestone/transparent-sensitivity-analysis-v0alpha1

### Added

- Exact, committed sensitivity analysis over disclosed component vectors.
- Pairwise componentwise dominance relations without winner selection or ranking.
- Strict analysis specification and generated schema.

## milestone/transparent-estimator-comparison-v0alpha1

### Added

- Exact comparison of weighted arithmetic and weighted harmonic component estimators.
- Versioned estimator specifications, generated schema, and fail-closed artifact parsing.
- Immutable milestone-tag policy.

## milestone/lane-one-task-profile-v0alpha1

### Added

- Versioned Lane One task profiles with canonical commitments.
- Explicit component enablement and identity-only upstream policy bindings.
- Required closed boundaries for scoring, ranking, weights, and chain actions.
- Generated task-profile JSON Schema and profile-bound component measurements.
