# ADR-0019: Add a scoring profile version that pays correct abstention, settles wrong scope and prices citation

**Status:** Proposed. The profile document and its scorer support are committed. The profile is
not active on any weight path.

**Date:** 2026-10-08

**Deciders:** SN87 protocol maintainers. Activation, the wrong-scope alternative and the payoff
values are open decisions (see "Open decisions").

## Context

An external technical review of the repository and the public testnet raised three scoring rules
that work against the protocol's own design. Each was reproduced with the real scorer on public
fixtures before this record was written; the figures are in "Numbers" below.

1. **A correct abstention scores the floor.** `INSUFFICIENT_EVIDENCE_ABSTAIN` is one of the three
   response states the design rests on, yet under `IC-FIRST-LIGHT-MIN-1` a correct abstention on
   an abstain-truth record scores epsilon (1e-6). A hedged false finding scores above it,
   because the calibration term of a finding stays in the geometric composite
   (LIMITATIONS item 16). A miner that wants the higher score never abstains.
2. **The wrong-scope rule is unrecorded.** The class defines one finding code, `STALE_APPROVAL`.
   When an approval covers a different mission, recipient or artifact than the action, the
   reference executors cannot name a finding and abstain. That choice is real behaviour (the
   recomputed truth state is the abstain state), but no ADR or profile records it.
3. **Evidence credit is binary and ignores surplus.** Credit is 1 when every required reference
   is cited, whatever else is cited. Citing every event in the record earns full credit
   (LIMITATIONS item 3), and the matched public-contract baseline does exactly that.

Changing `IC-FIRST-LIGHT-MIN-1` in place is not allowed: its commitment is pinned and a sealed
run's meaning would change. A scoring change is a new profile version (ADR-0010,
`docs/protocol/profile-application.md`).

## Decision

Commit one new profile version, `IC-FIRST-LIGHT-MIN-2`, for the class
`IC-APPROVAL-APPLICABILITY`. It copies every parameter of `IC-FIRST-LIGHT-MIN-1` (weights,
epsilon, theta, gamma, severity weights, assignment and diagnostics families, minimum window)
and adds one block, `scoring_rules`, that declares three rules together:

### 1. State payoff matrix

The scorer reads a 3 x 3 matrix indexed by the recomputed truth state (row) and the response
state (column). The matrix follows the state-by-truth payoff matrix of the design (whitepaper
v0.7.2, TR-24). The whitepaper is not distributed with this repository and its text was not
available when this record was written, so the cell values below are a proposal and are not
claimed to be copied from it.

The cell caps the score. Only a correct `FINDINGS` response keeps per-finding quality: its cell
value is multiplied by the existing composite of detection, evidence and calibration. Every other
cell is the cell value, so a confidence claim cannot lift a wrong answer above a correct
abstention. Valid responses keep the epsilon floor. An invalid or missing response still scores 0.

Chosen values:

- correct finding and correct clear: 1;
- correct abstention (abstain truth, abstain response): 1/2;
- unwarranted abstention (a decidable truth, abstain response): 1/4;
- confident wrong answer (any other cell): 0, which the floor lifts to epsilon.

Why these values:

- The required order is confident wrong < correct abstention < correct finding or clear. The
  loader enforces a stricter order and refuses a profile that breaks it: confident wrong is at
  most an unwarranted abstention, which is below a correct abstention, which is below both
  correct cells. Caution is never scored below error.
- A correct abstention pays half of a correct answer, not the same. If it paid the same, always
  abstaining would be a safe strategy whenever abstain-truth cases are frequent.
- An unwarranted abstention pays a quarter. Let a miner believe a record is abstain-truth with
  probability q, and that a confident answer is right with probability r when the truth is
  decidable. A confident answer expects (1 - q) r. Abstaining expects q/2 + (1 - q)/4. The miner
  abstains when q/2 + (1 - q)/4 > (1 - q) r. With q = 0 that is r < 1/4, so abstention is a
  rational choice only when the miner is quite unsure, and never a free floor.
- With theta = 0.6 in the preference row, a miner that abstains on every record has a mean per
  record score of at most 1/2 and earns no preference weight. The values are exact in binary
  floating point, so the scorer's arithmetic reproduces them without rounding.

### 2. Wrong-scope rule: abstention on record

For a record whose approval covers a different scope than the action, the correct response is
`INSUFFICIENT_EVIDENCE_ABSTAIN`. The profile declares `wrong_scope: ABSTENTION_ON_RECORD`. The
scorer needs no extra code for it: the recomputed truth state of such a record is the abstain
state, the matrix pays a correct abstention 1/2, and a clear (the matched baseline's answer)
or any finding pays the floor. No finding code is
added, so the wire contract, the class defect list and the reference executors are unchanged.

The loader accepts only this value. A profile that declares a different wrong-scope rule is
refused with `PROFILE_NOT_APPLIED`.

### 3. Citation precision

Evidence credit of a matched finding becomes the product of precision and recall over the
references: `|cited & required| / |cited|` times `|cited & required| / |required|`, with repeated
references counted once and an empty or disjoint citation scoring 0. Citing exactly the required
set earns 1. Citing a superset earns less in proportion to the surplus, and omitting a required
reference earns less in proportion to what is missing. The rule is named `PRECISION_TIMES_RECALL`
in the profile.

Edge case: when a truth defect lists no required references, both rules give credit 1, as the
original binary rule always did. A truth record names at least the action and the completeness
scope, so the case does not arise for the bound class.

### Scorer support

`profile.py` parses `scoring_rules` into three optional `Profile` fields and validates them:
the matrix must be complete, every cell a decimal string in [0, 1], the order above must hold,
and the other two rules must name a supported value. `scoring.py` selects behaviour by those
fields, never by a profile name. A profile without `scoring_rules` leaves all three fields unset
and takes the original code path: `IC-FIRST-LIGHT-MIN-1` and `GRA-W03-3` score byte for byte as
before. The committed score results, golden vectors and pinned commitments are unchanged, and a
differential check of the pre-change scorer against the new one, over responses of every
public family of both bound classes (references, baseline, altered confidence, abstention,
clear, shortened citation, failed integrity and a missing response), found no difference. The new profile's score result adds one `payoff` key.

## Alternatives considered

- **A new finding code for wrong scope (for example `WRONG_SCOPE`).** Rejected for this version
  and listed as an open decision. A named finding gives a miner something to be paid for
  detecting, and the launchpad demonstrations want one. It also changes the wire contract: the
  class defect list and severity, the truth emitted by the reference executors, the hidden
  instance generator, the matched baselines and the miner kit would all change, and the public
  contract tests would move. That is a contract version, not a scoring profile. Abstention on
  record changes no wire byte and can be superseded later by a profile that names a code.
- **Binary evidence credit with a surplus cap.** Keeps the rule that missing any required
  reference earns 0, and allows a fixed number of surplus references. Rejected because the cap is
  an arbitrary constant, and because partial recall credit is a better training signal for a
  miner that is close.
- **F1 of precision and recall.** Gentler on surplus than the product. Rejected because the geometric
  weight of the evidence dimension is only 0.25, so the effect on the score is already small.
- **Paying an unwarranted abstention 0.** Closes the floor entirely. Rejected because a miner
  with no information would then be indifferent between abstaining and a coin-flip answer; 1/4
  puts the break-even where an honest abstainer would choose to abstain.
- **Editing `IC-FIRST-LIGHT-MIN-1`.** Not allowed. Its commitment is pinned.

## Numbers

The figures below are generated, not typed. A generator in the private test suite runs the real
scorer and the private reference executors over the public fixtures under both profiles, and
runs the existing multi-seed perturbation report once with each. A private test fails if this
block differs from the committed record. The profile document, the scorer rules and the unit
tests that exercise them ship in this repository; the generator and its records need the private
reference executors and do not.

Strategies: `reference` is a reference response with exact citations; `public_contract_baseline`
is the matched baseline; `cite_everything` is the reference with every event and the completeness
scope cited; `never_abstain` is the reference except that it states a hedged `STALE_APPROVAL`
finding at confidence 0.5 where the reference abstains; `always_abstain` abstains on every
record. The two wrong-scope families change one action's recipient in a public fixture.
In the tables, MIN-1 is `IC-FIRST-LIGHT-MIN-1` and MIN-2 is `IC-FIRST-LIGHT-MIN-2`.

<!-- BEGIN GENERATED: profile-comparison -->
State payoff matrix of the committed profile (rows are the recomputed truth, columns the response state):

| Truth \ response | FINDINGS | NO_MATERIAL_DEVIATION | INSUFFICIENT_EVIDENCE_ABSTAIN |
| --- | --- | --- | --- |
| FINDINGS | 1 | 0 | 0.25 |
| NO_MATERIAL_DEVIATION | 0 | 1 | 0.25 |
| INSUFFICIENT_EVIDENCE_ABSTAIN | 0 | 0 | 0.5 |

Correct abstention against hedged false findings, one public abstain-truth case (`incomplete`, index 0):

| Response | MIN-1 | MIN-2 |
| --- | --- | --- |
| correct abstention | 1e-06 | 0.5 |
| false finding, confidence 0.5 | 1.496e-05 | 1e-06 |
| false finding, confidence 0.9 | 1.137e-05 | 1e-06 |

Citation, one public finding case (`stale_authority`, index 0; 9 required references, 13 events plus the completeness scope in the record):

| Method | References cited | Evidence MIN-1 | Evidence MIN-2 | Score MIN-1 | Score MIN-2 |
| --- | --- | --- | --- | --- | --- |
| cite_everything | 13 | 1 | 0.6923 | 1 | 0.9122 |
| public_contract_baseline | 13 | 1 | 0.6923 | 1 | 0.9122 |
| reference | 9 | 1 | 1 | 1 | 1 |

Mean score by strategy and family, 20 public fixtures per family (MIN-1 / MIN-2):

| Family (recomputed truth) | reference | public_contract_baseline | cite_everything | never_abstain | always_abstain |
| --- | --- | --- | --- | --- | --- |
| fresh_review (NO_MATERIAL_DEVIATION) | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 | 1e-06 / 0.25 |
| incomplete (INSUFFICIENT_EVIDENCE_ABSTAIN) | 1e-06 / 0.5 | 1e-06 / 0.5 | 1e-06 / 0.5 | 1.496e-05 / 1e-06 | 1e-06 / 0.5 |
| stale_authority (FINDINGS) | 1 / 1 | 1 / 0.9122 | 1 / 0.9122 | 1 / 1 | 1e-06 / 0.25 |
| wrong_scope_clear (INSUFFICIENT_EVIDENCE_ABSTAIN) | 1e-06 / 0.5 | 1e-06 / 1e-06 | 1e-06 / 0.5 | 1.496e-05 / 1e-06 | 1e-06 / 0.5 |
| wrong_scope_stale (INSUFFICIENT_EVIDENCE_ABSTAIN) | 1e-06 / 0.5 | 1e-06 / 1e-06 | 1e-06 / 0.5 | 1.496e-05 / 1e-06 | 1e-06 / 0.5 |

Multi-seed perturbation report (20 seeds, 20 cases per family, pooled), mean score delta (perturbed minus unperturbed) and agreement with recomputed truth, MIN-1 / MIN-2:

| Perturbation | reference delta | baseline delta | reference agreement | baseline agreement |
| --- | --- | --- | --- | --- |
| clock_skew | -0.5465 / -0.2732 | -0.5465 / -0.4722 | 1 / 1 | 0.5584 / 0.5584 |
| clock_skew_small | -0.4342 / -0.2171 | -0.4342 / -0.4178 | 1 / 1 | 0.5658 / 0.5658 |
| drop_event | -0.5825 / -0.2913 | -0.5825 / -0.4053 | 1 / 1 | 0.725 / 0.725 |
| duplicate_event | -0.4292 / -0.2146 | -0.4292 / -0.3114 | 1 / 1 | 0.7775 / 0.7775 |
<!-- END GENERATED: profile-comparison -->

What the numbers show:

- Under `IC-FIRST-LIGHT-MIN-1` the hedged false finding beats the correct abstention, never
  abstaining beats the reference on every abstain-truth family, and citing everything ties
  exact citation. All three rules from the review reproduce.
- Under `IC-FIRST-LIGHT-MIN-2` the correct abstention pays 1/2 and the hedged false finding pays
  the floor. The reference scores at least as high as every other strategy on every family. Citing everything and the baseline lose part
  of the evidence term. Always abstaining pays well below answering.
- In the perturbation report, the references and the baseline had the same mean score delta in
  every cell under `IC-FIRST-LIGHT-MIN-1`, although the baseline's agreement with truth fell.
  Under `IC-FIRST-LIGHT-MIN-2` the delta separates them in every cell where agreement differs,
  in the direction of agreement. This is diagnostic output over synthetic fixtures. It is never a score input.

## Status: committed, not active

`IC-FIRST-LIGHT-MIN-2` is committed and pinned in the profile registry. It is not active on any
weight path. No class binding, run plan, validator configuration or weight approval names it. The
only profile bound to `IC-APPROVAL-APPLICABILITY` is `IC-FIRST-LIGHT-MIN-1`, and a test fails if
any source file other than the loader names the new profile. Nothing in this record is an
approval.

Activation would need, at least:

- a new plan version that names `IC-FIRST-LIGHT-MIN-2`, approved through Provenonce's own
  decision process (the approved plan in force is not changed by this record);
- a class binding to the new profile on a path that is not the current weight path;
- a decision whether abstain-truth families (wrong scope, incomplete record) stay diagnostics or
  join the assigned window. Under the profile as committed they stay diagnostics, so correct
  abstentions would not yet enter an epoch estimate; and
- a fresh local qualification and perturbation report at the activating commit.

## Open decisions

- Whether and when to activate `IC-FIRST-LIGHT-MIN-2`, and on which path first.
- Whether wrong scope stays abstention on record or becomes a named finding code under a new
  contract version.
- The payoff values (1, 1/2, 1/4, 0), and whether the whitepaper's matrix intends other values.
- Whether the citation rule is the product of precision and recall or another form.
- Whether abstain-truth families join the assigned window.

## Consequences

- A rational miner abstains only when it is unsure, and an abstention on a record the references
  also abstain on is paid.
- Citing every event costs part of the evidence term in proportion to the surplus, so the
  baseline no longer ties exact citation.
- The reference executors, the wire contract and every committed digest are unchanged.
- A residual weakness: the references still compute their own truth under common control, so a
  score above does not show that a method beats them. The payoff matrix does not decide whether
  abstain is the right truth for a record; it only pays the response that matches it.
