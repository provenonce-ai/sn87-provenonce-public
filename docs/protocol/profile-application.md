# Profile application

One profile family: committed JSON profiles `GRA-W03-3` (class `TYPE-C-RELEASE`) and
`IC-FIRST-LIGHT-MIN-1` (class `IC-APPROVAL-APPLICABILITY`), committed as `src/sn87_provenonce/profiles/<id>.json` and loaded by `profile.py`.
A third profile, `IC-FIRST-LIGHT-MIN-2`, is committed beside them and is not bound to any class or
weight path (see "Optional scoring rules" below).

## Rule

- Operative parameters are derived from the validated committed profile: `theta`, `gamma`,
  `minimum_assignments`, `tail_fraction`, `maximum_raw_invalid_or_missing_rate`, dimension weights,
  `epsilon`, severity weights, `beta`.
- Scoring functions have no parameter defaults.
- Changing the committed profile changes the result.
- Evaluation fails closed on missing, unparsed or mismatched operative values, and when the run's
  profile commitment differs from the profile used: `PROFILE_NOT_APPLIED`.
- Nonzero cost coefficients are rejected: `COEFFICIENT_ACTIVATION_NOT_AUTHORIZED`.

The bundle records `profile_id`, `profile_commitment` (`object_commitment`: SHA-256 over the domain
`SN87:SCORING_PROFILE:<schema>`, a NUL byte and the length-prefixed canonical profile bytes) and `profile_applied`. `profile_applied: false` cannot appear in a bundle: the evaluation
that would produce it raises instead.

## Inert (reserved) profile fields

Two fields in each committed profile are inert: `rule_reliability` and
`deterministic`.

- Each is part of the profile commitment: it sits in the committed document, so changing it
  changes the commitment and is a new profile version (see below).
- No scorer code reads either field. `Profile` does not parse them into an operative parameter;
  its only access is `Profile.truth_fields()` in `profile.py`, which returns the two values
  verbatim (type-checked: a decimal string and a bool) for truth records. No other module under
  `src/` names them.
- Neither has any effect on any score, weight or verdict.
- Both are reserved. Wiring either one into scoring (for `rule_reliability`, the Eq. 2 rule
  score) needs a decision by Provenonce and a new profile version and commitment; it is not a
  code-only change.

The two private reference executors that build truth records carry no literals. Each splices in `load(<profile id>).truth_fields()` from its bound, pin-checked committed profile (`IC-FIRST-LIGHT-MIN-1` for `institutional_v02/references.py`, `GRA-W03-3` for `pilot/reference.py`), so a truth record cannot drift from its profile: a profile change moves the emitted values (and, because the profile is pinned, also needs a new profile version). A malformed profile value fails closed with `ProfileNotApplied`. This is an echo of the committed value, not a scoring read. `tests/test_inert_profile_fields.py` fails if any use of either name appears in `src/` outside `Profile.truth_fields()`, and checks that changing either field changes the commitment, so a future read has to be reviewed first. `tests/test_truth_profile_derivation.py` fails if an emitter's value differs from the committed profile or ignores the bound profile (it needs the private executors and skips without them). Eq. 2 stays inactive (see below).

## Optional scoring rules

A profile may carry a `scoring_rules` block (ADR-0019). `IC-FIRST-LIGHT-MIN-1` and `GRA-W03-3` do
not, and score exactly as before: `Profile.state_payoff`, `Profile.wrong_scope` and
`Profile.evidence_credit` are unset and the scorer takes the original path. A block declares all
three rules together, with no per-rule switch:

- `state_payoff`: a complete 3 x 3 matrix of decimal strings in [0, 1], indexed by recomputed
  truth state then response state. The loader refuses a matrix in which a confident wrong answer
  pays more than an unwarranted abstention, an unwarranted abstention pays at least a correct
  abstention, or a correct abstention pays at least a correct finding or a correct clear.
- `wrong_scope`: `ABSTENTION_ON_RECORD`, the only supported value. A named wrong-scope finding code
  would change the wire contract, so a profile cannot declare it.
- `evidence_credit`: `PRECISION_TIMES_RECALL`, the only supported value. Without the block, evidence
  credit stays binary.

The scorer selects behaviour from these fields, never from a profile name. A result scored under
such a profile adds a `payoff` key. A profile with a block is a new profile version with its own
commitment; it is not a change to a committed profile.

## Changing a profile

A parameter change is a new profile version and a new commitment, never a configuration edit.
A result produced under an old commitment is not relabelled. Earlier profile versions were
retired and are not part of this repository.

## Inactive scoring terms

Eq. 2, Eq. 8 and Eq. 10 are `"NA"`. Eq. 11 keeps eta = 1 because all four cost coefficients are 0;
its status is `INACTIVE`. See [wire-rules.md](wire-rules.md) and
[LIMITATIONS](../../LIMITATIONS.md).
