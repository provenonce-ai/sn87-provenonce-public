# ADR-0020: Contest windows (fresh committed instances, per-window results) and a window-sizing profile version

**Status:** Proposed. The tooling and the profile document are committed. The profile is not
active on any weight path, and no tool here sets, signs or submits a weight.

**Date:** 2026-10-08

**Deciders:** SN87 protocol maintainers. Activation, the window size and the closed-window truth
policy are open decisions (see "Open decisions").

## Context

An external technical review of the repository and the public testnet raised three connected
points.

1. **The public testnet series exercises the validator alone.** The attested runs share one
   validator digest, one plan digest, one seed (0) and one validator timestamp, so each run
   reproduces one scoring result over one fixed set of fixtures. That shows liveness, integrity
   and arithmetic. It cannot show whether scoring separates good work from bad, or what an epoch
   looks like when answers differ. The requested next stage is a testnet with a contest: fresh
   instances every window from a committed generator, seeds committed before a window and revealed
   after it, per-window scores published, and agreement with truth published beside each score.
2. **The public cases are already solved.** The public-contract baseline scores 1 on both classes
   (`NULL_NO_HEADROOM`), and the one place the methods differed in the launchpad demonstration
   (wrong scope) did not enter the scored totals. Under clock skew the baseline's agreement with
   truth falls while its mean score delta matches the references' (LIMITATIONS item 16): score
   alone does not separate the methods there, agreement does. Families with headroom, and
   agreement beside score, are needed.
3. **Windows carry exactly the profile minimum.** Every committed profile asks for 12 admitted
   scored cases and the fixture and source windows carry 12, so a single reference failure leaves
   11 and voids the window (LIMITATIONS item 15).

This record covers the tooling for 1 and 2 and the profile version for 3. It changes no committed
profile, no class binding, no reference executor and no wire contract.

## Decision

### 1. A window generator with a commit, open, reveal protocol (`scripts/contest_window.py`)

A window is a specification (profile id and commitment, family mix, open and close times, generator
id) plus a seed. The protocol is in [contest-windows.md](../protocol/contest-windows.md). In short:

- **Commit** (before the window opens). The operator holds a master seed. The window seed is
  `HMAC-SHA256(master, frame(domain, schedule_id, window_id))`, so a reused master seed and window
  id in another schedule give different instances. The public record carries
  `seed_commitment = sha256(frame(domain, window_id, seed))`, a salted `spec_commitment` over the
  specification (the salt derives from the secret seed, so the commitment hides the family mix), and a `schedule_commitment` over all rows. A whole schedule of windows is committed
  up front.
- **Open** (while the window runs). Instance `i` has its own key, derived by HKDF-Expand from the
  window seed with the window id and the position in the info string. That key drives the
  `identifier` hook of `institutional_v02/fixtures.py build_case`, which is reused unchanged (the
  generator is not forked). Miners receive capsules only: no family, no track, no truth.
- **Reveal** (after the window closes). The seed and the specification are published. Anyone
  regenerates every capsule and checks both commitments.

The family mix is configurable and committed with the specification. It reuses `stale_authority`,
`fresh_review` and `incomplete` from `build_case`, and adds two wrong-scope families built on top of
them: a fresh review or a stale authority record in which one action's approval is moved out of scope
(a different mission, recipient or artifact, chosen by the seed). These are the cases where the
references abstain and the matched baseline over-claims (a `FINDINGS` or a clear). The launchpad
demonstration reaches the same case through its source mapper (other cohort, other project, other
package version); the generator does the equivalent at the capsule level so that it needs no source
fixture. The wrong-scope rule stays what ADR-0019 recorded: abstention on record, with no new finding
code.

Truth for generated instances comes from the private reference executors and only on the private
side. The public tree has no executor, so the `truth` phase there fails with an explicit message.
An explicit `--phase` guard refuses a phase at the wrong time or under the wrong policy (see the
guard table in the protocol document). Hidden-window truth is never disclosed before the window
closes.

### 2. Per-window results (`scripts/contest_results.py`)

For a closed window the script scores every method, the public-contract baseline included, on the
same capsules with the one scorer under a committed profile chosen by id (default
`IC-FIRST-LIGHT-MIN-1`; `IC-FIRST-LIGHT-MIN-2` and `-3` by id). It writes a deterministic JSON
record and a markdown page. At close it publishes scores only. Once the seed is revealed and truth publication is authorized, it adds, beside each score, agreement with truth (state agreement and
exact agreement including finding codes), the confusion table by truth state, validity and
integrity failures, and the cost record. The baseline's responses are recomputed from the public
baseline code and compared. The schema is in [window-results.md](../protocol/window-results.md).
Scoring and cost use the existing machinery (`scoring.score_response`, `scoring.epoch_estimate`,
`bundle.cost_record`); no scoring rule is added.

### 3. Profile version `IC-FIRST-LIGHT-MIN-3`: window sizing above the minimum

`IC-FIRST-LIGHT-MIN-3` copies every parameter and the whole `scoring_rules` block of
`IC-FIRST-LIGHT-MIN-2` (so it inherits the state payoff matrix, the wrong-scope rule and the
precision-aware citation credit) and changes three values: the assignment (24 scored cases instead
of 12), the diagnostics (8 instead of 4) and `minimum_assignments` (22 instead of 12).

The smallest change that stops a single reference failure from voiding a window is no code change.
`epoch_estimate` already declares a window ineligible when the admitted scored cases number fewer
than `minimum_assignments`. A reference failure removes its case from the admitted supply, so a
window that assigns more cases than the minimum absorbs `assigned - minimum` of them. With 24
assigned and a minimum of 22, a window absorbs 2 reference failures and voids at the third. The
floor stays well above the old 12, so the statistical weight of a valid window does not fall. The
raw invalid-or-missing ceiling (0.10) is unchanged and counts miner failures, not reference
failures.

The profile is a new committed document with its own pinned commitment. `profile.py` registers it
and nothing else names it; no class binding, run plan or validator configuration does.

## Disclosure, precisely

| When | Public | Private |
|---|---|---|
| Before the window opens (commit) | seed, specification and schedule commitments; window times; profile id and commitment; generator id | master seed, window seed, family mix, instances, truth |
| While the window is open | capsules (sent to miners; they carry no family, track or truth) | window seed, cases file (family, track), truth |
| After the window closes, results | scores only: epoch estimate and eligibility per method, cost, the cases commitment and the salted truth commitment | agreement with truth, confusion tables, failure counts, truth state counts, per-case truth |
| After reveal | seed and specification: anyone regenerates every capsule, family and track and checks both commitments | truth-derived aggregates and per-case truth, unless the policy below is decided |
| Truth-derived aggregates and per-case truth of a closed window | only under an explicit policy flag, after the reveal verifies, for that window only (the salt is published with them) | everything else, and every open or future window |

Aggregates that derive from truth (agreement, confusion tables, family tables, failure counts, truth
state counts, reference failures, score dimensions) follow the same rule as per-case truth, because
they are the same information in summary. The scores that are published at close still constrain the
truth on a three-state task; [window-results.md](../protocol/window-results.md) says precisely what
a score alone reveals. The commitments file proves order only if it is anchored to an independent
timestamped channel, which the protocol document describes and the tooling does not perform.

Two facts bear on the policy decision. First, after reveal the family of every instance is public,
and under the current reference behaviour the truth state follows from the family (a stale authority
record has findings, a fresh review is clear, an incomplete record or a wrong-scope record is
abstain), as the public fixture truth already shows. What per-case publication adds is the required
evidence references of each finding and which instances had a reference failure. Second, instances are never reused: a window id is single use and a new window
derives new identifiers, so a closed window's truth does not describe any open or future instance.
The truth commitment published with the results lets a later publication be checked against what the
results were computed from.

## Alternatives considered

- **Derive each window's seed from a public randomness beacon at open time.** Removes the operator's
  freedom to choose the master seed. Not done: it adds an external dependency and a timing
  assumption. The commit-before-open order already stops the operator from choosing a seed after
  seeing any response. A beacon can be mixed into the window seed later as a new generator version.
- **Fork the case generator for seeded identifiers.** Rejected: `build_case` already takes an
  `identifier` callable, and a fork would drift from the public fixtures.
- **A named wrong-scope finding code.** Rejected for this version for the reason recorded in
  ADR-0019 (it is a contract version, not a scoring profile).
- **Lower the minimum instead of raising the window.** Rejected: it weakens the statistical floor
  and still needs a new profile version.
- **Redundant reference execution per case.** Possible later and independent of this record; it
  lowers the reference failure rate instead of tolerating it.
- **Publish per-case truth for every window by default.** Not decided here; see the open decisions.

## Numbers

The block below is generated, not typed, by `scripts/window_sizing_table.py` from the committed
profile documents and `epoch_estimate`. A test fails if it differs from the generated output.

<!-- BEGIN GENERATED: window-sizing -->
Assigned scored cases per window, the profile minimum, and how many reference failures a window absorbs (a failed reference removes its case from the admitted supply):

| Profile | Assigned scored | Minimum | Reference failures tolerated | Window void from |
|---|---|---|---|---|
| IC-FIRST-LIGHT-MIN-1 | 12 | 12 | 0 | 1 failure(s) |
| IC-FIRST-LIGHT-MIN-2 | 12 | 12 | 0 | 1 failure(s) |
| IC-FIRST-LIGHT-MIN-3 | 24 | 22 | 2 | 3 failure(s) |

Eligibility of a window of valid responses after k reference failures (`epoch_estimate`):

| k | IC-FIRST-LIGHT-MIN-1 | IC-FIRST-LIGHT-MIN-2 | IC-FIRST-LIGHT-MIN-3 |
|---|---|---|---|
| 0 | eligible | eligible | eligible |
| 1 | void (SAMPLE_FLOOR) | void (SAMPLE_FLOOR) | eligible |
| 2 | void (SAMPLE_FLOOR) | void (SAMPLE_FLOOR) | eligible |
| 3 | void (SAMPLE_FLOOR) | void (SAMPLE_FLOOR) | void (SAMPLE_FLOOR) |
| 4 | void (SAMPLE_FLOOR) | void (SAMPLE_FLOOR) | void (SAMPLE_FLOOR) |
<!-- END GENERATED: window-sizing -->

The demonstration window (`examples/contest-window-demo`) is regenerated end to end by
`scripts/contest_dry_run.py`; its page lists the numbers of one run (committed under
`examples/contest-window-demo/results`). Under `IC-FIRST-LIGHT-MIN-1` the same window shows the
candidate and the baseline tied on estimate while their agreement with truth differs; the
page produced under `IC-FIRST-LIGHT-MIN-3` separates them in estimate as well.

## Status: committed, not active

The tooling is shadow only: it reads and writes files, calls no chain and sets no weight. Testnet
weights are unchanged. `IC-FIRST-LIGHT-MIN-3` is committed and pinned and active on no path. Nothing
in this record is an approval. Activating a contest would need, at least: a decision on each open
item below; a plan version that names `IC-FIRST-LIGHT-MIN-3`; at least two outside miners admitted
to a window; commit-reveal on the target network; a second validator under the truth-custody
decision; and a fresh local qualification at the activating commit.

## Open decisions

- Whether truth-derived aggregates and per-case truth of a closed window may be published, and the
  exact fields (see "Disclosure, precisely"). The default in the tooling is to refuse.
- Whether even the scores should wait for the reveal. They are published at close here, and they
  constrain the truth on a three-state task.
- The window size and the tolerance (24 assigned, minimum 22, 2 reference failures tolerated).
- Whether and when to activate `IC-FIRST-LIGHT-MIN-3`, and on which path first.
- Whether abstain-truth families (wrong scope, incomplete record) join the scored track (the
  `messy` preset does; the `profile` preset keeps ADR-0019's current split).
- The window schedule: length, cadence and the number of windows committed in advance.

## Consequences

- A fresh window can be generated, committed, played, scored and audited with no change to the
  scorer, the reference executors or the wire contract.
- Once a closed window's seed is revealed and truth publication is authorized, agreement with truth
  is published beside every score, so a tie in score no longer hides a gap in agreement. Until then
  only scores are published.
- A window absorbs reference failures up to the tolerance; beyond it the window is void and says so.
- Truth custody is unchanged: the reference executors stay private, so outside parties verify the
  commitments and the capsules, and verify truth only to the extent that per-case truth is later
  published.
