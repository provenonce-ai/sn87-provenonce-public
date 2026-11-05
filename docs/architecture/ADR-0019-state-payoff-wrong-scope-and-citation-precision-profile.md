# ADR-0019: Add a scoring profile version that pays correct abstention, settles wrong scope and prices citation

**Status:** Proposed. The profile document and its scorer support are committed. The profile is
not active on any weight path.

**Date:** 2026-10-08

**Deciders:** SN87 protocol maintainers. Activation, the wrong-scope alternative and the payoff
values are open decisions (see "Open decisions").

## Context

Three scoring rules of the committed profile work against the protocol's own design. Each was
checked with the real scorer on public fixtures before this record was written.

1. **A correct abstention scores the floor.** `INSUFFICIENT_EVIDENCE_ABSTAIN` is one of the three
   response states the design rests on, yet under `IC-FIRST-LIGHT-MIN-1` a correct abstention on
   an abstain-truth record scores epsilon (1e-6). A hedged false finding scores above it,
   because the calibration term of a finding stays in the geometric composite
   (LIMITATIONS item 16).
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

## Measurements

The measurements behind this record (a comparison of the two profiles over the public fixtures
and a multi-seed perturbation report) are generated by tooling that needs the private reference
executors. They are kept with the private research records and are not part of this repository.
The profile document, the scorer rules and the unit tests that exercise them ship here.

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
