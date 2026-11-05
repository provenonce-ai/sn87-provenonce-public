# ADR-0022: A constant-answer bound, fixed-outcome calibration and declared-severity credit (profiles MIN-4 and GRA-RELEASE-MIN-4)

**Status:** Proposed. Two profile documents, their scorer support and their tests are committed.
Neither profile is active on any weight path, shadow service or default.

**Date:** 2026-11-05

**Deciders:** SN87 protocol maintainers. Which scoring design a competition uses is an
open decision (see "Open decisions"); this record does not make it.

## Context

The committed profiles leave several properties of the scoring design open. This record adds profiles
that fix them; it does not change a committed profile.

- **A pool should bound a fixed answer.** One fixed reply given to every case should not reach the
  threshold. What it earns depends on the share of each truth state in the scored pool, so the
  pool composition has to be declared and checked.
- **Identical answers should share one weight.** Several identities can return one answer and
  each earns a full weight. Nothing records simultaneous dispatch, matching response times, or
  identical answers on tasks that separate methods.
- **Abstention needs one stated place.** The share of abstain-truth cases in the scored pool is
  not capped, and what such a case is, and how it is paid, is not stated in one place.
- **Calibration should have a fixed denominator.** Equation 7 is a Brier score over the claims the
  miner chooses to make, so the denominator is the miner's choice. Type C has no payoff matrix.
- **Declared severity should be scored.** The severity a miner declares on a matched finding is
  ignored, and nothing says the rationale is not scored.
- **Surplus citation should cost something.** Citing more references than required should cost
  more than it does under the earlier citation rule.

Changing a committed profile in place is not allowed (ADR-0010, `docs/protocol/profile-application.md`).
These are new profile versions with new commitments. The earlier profiles, their commitments and
their score results are byte-identical; a test pins the file hashes.

## Decision

Commit two profile documents. Both declare a `scoring_rules` block with `rules_version` "4", which
the loader reads only when that key is present. A block without it is read exactly as before
(ADR-0019).

- `IC-FIRST-LIGHT-MIN-4`, class `IC-APPROVAL-APPLICABILITY`, derived from `IC-FIRST-LIGHT-MIN-3`.
- `GRA-RELEASE-MIN-4`, class `TYPE-C-RELEASE`, derived from `GRA-W03-3`. This is the new Type C profile: it
  gives Type C the payoff matrix, and with it the cap on a wrong state, and every other rule below.

The rules are inside these two documents only. No earlier profile is changed, and the scorer
selects behaviour from the parsed fields, never from a profile name.

### 1. The pool bounds every constant answer

The profile declares which truth state each assigned family has, and caps the share of each state:
defect cases at most 0.40, clear cases at most 0.40, abstain-truth cases at most 0.20.
`IC-FIRST-LIGHT-MIN-4` assigns 16 `stale_authority`, 16 `fresh_review` and 8 `incomplete`
(40 scored cases, minimum 36, so a window absorbs 4 reference failures). `GRA-RELEASE-MIN-4` assigns 16
`clean`, 6 `missing_gate`, 5 `order`, 5 `continuity` and 8 `incomplete` (40, minimum 36), with
`equivalent` staying a diagnostic.

A constant answer pays at most the matrix cell on every case. Its mean score is therefore at most
the share-weighted column of the matrix: for the column FINDINGS that is the defect share times 1,
whatever the code, severity, citation or confidence of the fixed finding. The loader computes that
bound for the three columns and refuses the profile (`PROFILE_NOT_APPLIED`) unless the largest is
at most theta minus a declared margin, and unless a method that is right on every case is at least
theta plus a declared strong margin. The loader also refuses a share above its cap, an assigned
family without a truth state, and a minimum above the assignment. The margins are 0.15 and 0.25.
Theta stays 0.60 and gamma 2.

An abstain-truth case is a record whose recomputed truth is `INSUFFICIENT_EVIDENCE_ABSTAIN`: a
declared incomplete record, or a record whose approval covers a different scope than the action
(wrong scope stays abstention on record, ADR-0019). It is paid by the matrix of ADR-0019, which is
copied unchanged: a correct abstention pays 1/2, an unwarranted abstention 1/4, a confident wrong
answer 0, a correct finding or clear 1. The 20 per cent cap is what keeps the half-price on a
correct abstention from costing a perfect method more than 10 per cent (its best mean is 0.90).

### 2. Calibration is a Brier score over a fixed set of outcomes

The outcome set is the class's committed defect catalogue (1 code for the IC class, 13 for Type C).
For each code the forecast p is the confidence the response states for it (0 if it makes no claim)
and the outcome y is 1 if the sealed truth holds the code. The score is `1 - sum (p - y)^2 / K`,
floored at 0. The denominator is K, the catalogue size, and the miner cannot change it.

- A false claim adds `p^2 >= 0` to the sum, so it can only lower the score; at confidence 0 it
  changes nothing. A claim on a code outside the catalogue is a false claim of the same kind.
- A code claimed more than once is read least favourably to the claimant: the lowest confidence on
  a true code, the highest on a false one, so a duplicate can never help.
- The rule is strictly proper per code: the expected score under belief q is uniquely maximised by
  reporting p = q.

Calibration enters the score linearly. For a correct `FINDINGS` response with at least one matched
code, `Q = (1 - w) * G + w * B`, where G is the geometric composite of detection, evidence and
severity (weights renormalised), B the calibration score, and w = 0.15. Linearity is what makes the
full score proper, not only B: the other terms do not depend on the stated confidences. A finding
set with no matched code has nothing to calibrate and keeps G. For every other cell `Q` is B alone
(an abstention states no forecast and is paid its cell). The score is `max(cell * Q, epsilon)`,
so B is computed in every cell of the matrix.

The cell caps the wrong state. A wrong state scores at most its cell (0, or 1/4 for an unwarranted
abstention), whatever its findings and confidences. A correct state with the right codes scores at
least 0.85 of its cell, whatever the confidence (down to 0), so the cap sits below it.

Three invariants are tests (`tests/test_profile_min4_rules.py`): (i) a false claim never raises a
score at any confidence on a grid of 0 to 1; (ii) reporting true beliefs is optimal on a grid of
beliefs, both for the rule and end to end through the scorer; (iii) a wrong state is capped below a
correct one.

### 3. Declared severity is scored on matched findings

For each matched finding, the declared severity is compared with the sealed one on the order LOW,
MEDIUM, HIGH: credit 1 for equal, 1/2 for one step, 0 for two. The dimension is the weighted mean
over matched findings, weighted as detection and evidence are. It is a fourth dimension, weight
0.10, in the composite. The weights are detection 0.40, evidence 0.35, severity 0.10, calibration
0.15. In the IC class there is one code with one sealed severity, so the dimension is a constant
there; it separates methods in Type C, where severities differ.

Rationale is required and not scored. The contract requires a non-empty rationale on every
response and a non-empty rationale on every finding; the scorer never reads either (a test
changes both and the score does not move). Scoring rationale needs a judge of free text, which is
Type D and is deferred. The profile records it as `REQUIRED_NOT_SCORED_TYPE_D_DEFERRED`.

### 4. Over-citing is priced

Evidence credit is `precision^2 * recall` over the cited and required references, and the evidence
weight rises from 0.25 to 0.35. Four surplus references on a 9-reference witness cost about 22 per cent
of the score, and each surplus reference costs at least 4 points more than the one before. The exponent is a profile parameter, bounded to 1 through 4.

### 5. Identical answers share one weight

`redundancy.redundancy_groups` groups identities by their decision vector: per case, the declared
state and the set of finding codes. Citations, declared severity, confidence, rationale, method
name and order are left out. Keying on the citations as well would let a surplus citation on one
case move an identity out of its group at almost no cost, so the key is the decision vector.

`scoring.preference_row` computes the groups itself from the answers it is given; the caller passes
answers, not groups. A caller-supplied grouping that disagrees with the computed one is refused.
Each member's pre-normalisation weight is divided by the group size, so a group earns what one
member would. A profile without the rule ignores both.

Two limits are stated plainly. First, the rule cannot tell agreement from copying: two independent
miners that are both right on every case have the same decision vector and share one weight. On an
easy pool this penalises honest agreement, and it is an open design question for Provenonce
whether that is acceptable. Second, the rule does not stop identity copies. An identity that copies
a correct miner joins its group and dilutes that miner's own share, while the group still earns
one weight in all; only the cost of registering identities limits that. Tests named `test_documented_limit_*` assert both behaviours.

Three non-scoring flags are recorded beside the results (`flags.observation_flags`, and in
`contest_results.py` under a profile with the rule): simultaneous dispatch, similar response time,
and identical answers on tasks that separate methods (a task is separating when the answers of the
identities on it are not all alike). A pair is flagged at 8 or more comparable cases and a share
of 0.9 or more, with 1 second as the dispatch window and 0.5 second as the response-time limit.
The flags are never a score or weight input; a test checks the scorer does not import the module.

## Parameters

The generated measurements behind these choices need the private reference executors and are
kept with the private research records. The parameters are part of the profile documents.

| Parameter | Value | Why |
| --- | --- | --- |
| theta, gamma | 0.60, 2 | Unchanged. The margin comes from the pool, not from moving theta. |
| defect share cap | 0.40 | Bounds a fixed finding at the cap, before any citation cost. |
| clear share cap | 0.40 | Bounds an always-clear answer at the cap. |
| abstain share cap | 0.20 | Bounds an always-abstain answer, and limits what the half-price on a correct abstention costs a perfect method to 0.10. |
| constant margin | 0.15 | Required of the loader: every constant answer at most theta minus 0.15. |
| strong margin | 0.25 | Required of the loader: a method right on every case at least theta plus 0.25. |
| window | 40 assigned, 36 minimum | Absorbs 4 reference failures, as ADR-0020 did at 24 and 22. |
| precision exponent | 2 | Surplus references are priced steeply enough to matter, within the 1 to 4 bound. |

## Not active

`IC-FIRST-LIGHT-MIN-4` and `GRA-RELEASE-MIN-4` are committed and pinned in the profile registry. No class
binding, run plan, validator configuration, shadow service or default names them, and a test fails
if any source file other than the loader names either. Nothing in this record is an approval.

## Open decisions

- **Profile selection is for Provenonce's own decision process, not for this record.** Other scoring designs are possible; this record
  does not choose between them. The severity credit, the abstention payoff and the pool caps above
  apply inside these two profiles only.
- Whether the correct-abstention payoff stays 1/2. At 1 a perfect method reaches 1.0, and the
  always-abstain constant would rise to 0.40 at a 0.20 cap.
- Whether to bind `GRA-RELEASE-MIN-4` or `IC-FIRST-LIGHT-MIN-4` to a class on any path, and a fresh
  qualification and perturbation report at that commit.
- Whether grouping by decision vector is acceptable where honest miners legitimately agree (it is
  computed by the scorer from the answers; the validator must pass the answers), and who records
  dispatch and response times.
- Whether rationale is scored, which is Type D.

## Consequences and limits

- The bound is on constant answers. A method that has information about the pool mix can score
  higher, and the mix is public in the profile, so it is known to every miner. The caps on the
  clear and abstain shares limit how far that goes.
- The reference executors still compute their own truth under common control (LIMITATIONS item 1);
  a score above theta does not show that a method beats them.
- The fixed set is the committed catalogue, so a code added to a class changes K and needs a new
  profile version. In Type C (13 codes) a miss costs 1/13 of the calibration term, a weaker signal
  than in IC (1 code); the cap and the other dimensions carry the weight there.
- Redundancy groups identical decision vectors only. A copy that changes a decision is not grouped
  but pays for it in score, and the flags are heuristics that need dispatch and response times,
  which the shadow tooling records where available (`NOT_RECORDED` otherwise).
- The pools as committed are small and repeat public fixtures, so a public method can reach the
  same score as a candidate. That is a headroom question, not a scoring rule: the profiles bound
  constant answers and nothing more. The bundle's candidate and family gate (`bundle.py`) refuses such a
  family but is wired into no weight path; tests named `test_documented_limit_*` assert the
  limit. Integration must check that the weight gate refuses a family a public method already solves, and fresh instances (not these
  fixtures) are the remedy.
- The family truth states are a fact about the committed class and live in the loader
  (`CLASS_FAMILY_STATES`); a profile that declares a different map is refused. The calibration
  weight must be positive.
- A window of 40 scored cases is still a small sample.
