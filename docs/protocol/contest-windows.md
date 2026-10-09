# Contest windows

A contest window is a bounded period in which miners answer fresh, generated capsules and the
results are published afterwards. This page specifies the generator protocol implemented by
`scripts/contest_window.py`. The decision record is
[ADR-0020](../architecture/ADR-0020-contest-windows-and-window-sizing-profile.md); the result record
is [window-results.md](window-results.md).

Status: shadow tooling. Nothing here sets a weight, signs, or sends to a chain. Testnet 582 weights
are unchanged. The scoring profile `IC-FIRST-LIGHT-MIN-3` that sizes the windows is committed and
active on no path.

## Entry criteria for a testnet with a contest

| Criterion | State |
|---|---|
| Fresh instances every window from a committed generator | implemented (`contest_window.py`, generator id `sn87-contest-generator/0.1`) |
| Seeds committed before the window, revealed after it | implemented (commit and reveal phases, `verify`) |
| Per-window scores published, with agreement with truth beside each score | implemented (`contest_results.py`) |
| Scoring that pays correct abstention and wrong scope (ADR-0019) | committed as a profile, not active |
| Window sized above the minimum (ADR-0020) | committed as a profile, not active |
| Families where the references abstain and a naive method over-claims | implemented (`wrong_scope_stale`, `wrong_scope_clear`, `incomplete`) |
| At least two outside miners | not provided by this change |
| Commit-reveal on the target network, a second validator | not provided by this change |

## Objects

- **Master seed.** 32 random bytes held by the operator, stored as 64 hex characters in a file with
  mode 0600. It is never published and never written by any phase except `init-master`.
- **Window seed.** `HMAC-SHA256(master, frame(WINDOW_SEED_DOMAIN, schedule_id, window_id))`. The
  schedule id is part of the derivation, so the same master seed and window id in a second schedule
  give different seeds and different instances. Revealing one window seed reveals nothing about the
  master or any other window's seed. Schedule ids must be unique per schedule. `commit` keeps a reuse ledger
  (`commitments-ledger.json`) beside the master seed file and refuses a repeated schedule and window id
  or a repeated seed commitment. The ledger is on by default: a first commit, with no ledger yet,
  needs `--no-prior-ledger REASON`, so skipping the check is a stated choice. `--prior-commitments
  FILE` (repeatable) adds earlier commitment files to the check.
- **Specification.** `{generator, schedule_id, window_id, opens_at, closes_at, profile_id,
  profile_commitment, mix_preset, mix}`. Its commitment is salted: `spec_commitment =
  sha256(frame(SPEC_DOMAIN, canonical(spec), salt))` with `salt = HMAC(window seed, ...)`. The salt
  is unknown before the reveal, so the commitment hides the family mix; a guesser cannot confirm a
  candidate mix against it. The mix is a list of `{family, track, count}`; families are `stale_authority`,
  `fresh_review`, `incomplete`, `wrong_scope_stale` and `wrong_scope_clear`; tracks are `scored` and
  `diagnostic`. The default preset `profile` takes the counts from the sizing profile's `assignment`
  and `diagnostics`. The preset `messy` puts the abstain-truth families in the scored track and is a
  shadow experiment.
- **frame(parts...)** is the concatenation of each part prefixed by its 4-byte big-endian length, so
  no two lists of parts give the same bytes.

## Phases

`--phase` selects exactly one. Every phase checks the clock (`--now` overrides it for tests and
replays). The guard protects against operator mistakes, not against an operator who falsifies the
clock.

| Phase | What it does | Refused when |
|---|---|---|
| `init-master` | create a master seed file (create-only, mode 0600) | the file exists |
| `commit` | write `commitments.json`: per window `seed_commitment = sha256(frame(COMMIT_DOMAIN, window_id, seed))`, the salted `spec_commitment`, times, and a `schedule_commitment` over all rows | any window has opened (`COMMIT_AFTER_OPEN`); a `demo-` id is used without `--demo`, or a non-demo id with it; a window or seed repeats the ledger or a `--prior-commitments` file (`WINDOW_OR_SEED_REUSED`); no ledger and no `--no-prior-ledger REASON` (`PRIOR_LEDGER_REQUIRED`); the schedule's profile is not for the generator's class (`PROFILE_CLASS_MISMATCH`) |
| `open` | write the capsule file for miners and a private cases file (family, track, variant) | before the window opens (`OPEN_BEFORE_WINDOW`) or after it closes (`OPEN_AFTER_CLOSE`); `commitments.json` is missing or differs from what the master seed and schedule produce (`WINDOW_NOT_COMMITTED`, `COMMITMENTS_DO_NOT_MATCH`) |
| `truth` | private: per-case truth from the private reference executors, with a random salt made now. `truth_commitment = sha256(frame(TRUTH_DOMAIN, window_id, seed_commitment, cases_commitment, salt, canonical(truth)))`: salted, so it hides the truth, and bound to the seed commitment published before the window and the capsule-set commitment published at open, so verification is not circular. A reference that raises on an instance is recorded as a reference failure for that instance | the private executors are absent (explicit message) |
| `reveal` | write `window_<id>.reveal.json`: the seed and the specification | the window has not closed (`REVEAL_BEFORE_CLOSE`); commitments differ |
| `publish-truth` | write the public `window_<id>.truth.json` (it now carries the salt) from the private truth file, after checking the reveal file's contents against the earlier commitments, the truth commitment against `commitments.json`, and the truth cases against the regenerated instances | before close (`TRUTH_PUBLICATION_BEFORE_CLOSE`); no reveal file (`TRUTH_PUBLICATION_BEFORE_REVEAL`); no `--publish-closed-window-truth` (`TRUTH_PUBLICATION_NOT_AUTHORIZED`); a reveal that fails its commitments (`SEED_COMMITMENT_MISMATCH` and others) |
| `verify` | public: recompute both commitments, the schedule commitment and every capsule from the reveal; compare with the published capsule file and truth file when present | any mismatch (`SEED_COMMITMENT_MISMATCH`, `SPEC_COMMITMENT_MISMATCH`, and others) |

`--window` must match `[a-z0-9][a-z0-9-]{2,47}` before it is used in any file name. `contest_results.py`
adds the guard `RESULTS_BEFORE_CLOSE`, and gates truth-derived aggregates like per-case truth.

## Instance derivation

1. The mix is expanded to a list of `(family, track)` and shuffled by sorting on
   `HKDF-Expand(seed, frame(ORDER_DOMAIN, window_id, index), 8)`, so position does not reveal family.
2. Instance `i` has key `HKDF-Expand(seed, frame(INSTANCE_DOMAIN, window_id, i), 32)`
   (RFC 5869, HMAC-SHA256). Its `identifier` stream is `HMAC(key, counter)[:16]` in hex.
3. `institutional_v02.fixtures.build_case` is called with that `identifier` and the window's
   `opens_at` as the capsule timestamp, so identifiers, nonces, commitments and times are fresh for
   every window and every instance.
4. A wrong-scope family builds a `fresh_review` or `stale_authority` record, then moves one action's
   approval out of scope: the action's mission, recipient or artifact is replaced by a fresh value
   (dimension and action chosen from the seed) and the evidence commitment is recomputed. The
   references abstain on these records; the matched baseline states a clear or a finding.

The generator id must change whenever any of these derivations changes. A test pins the output of a
demonstration window, so a silent change fails.

## What is disclosed, and when

| Stage | Disclosed |
|---|---|
| Commit | commitments, window times, profile id and commitment, generator id |
| Open | capsules, to miners (no family, track or truth) |
| Close | scores only: the epoch estimate and eligibility per method, cost, and the cases and (salted) truth commitments. Agreement with truth, confusion tables, family tables, failure counts, truth state counts, reference failures and score dimensions are withheld because they derive from truth |
| Reveal | seed and specification; anyone regenerates every capsule, family and track |
| Truth-derived aggregates and per-case truth | only for a closed window whose reveal verifies, and only under the explicit policy flag (open decision, ADR-0020). Both follow the same rule |

Hidden-window truth is never written to a public name before close. The private truth and cases
files are created with mode 0600 and carry `.private.` in their names.

## Anchoring the commitments

The commitments file proves order only if readers know when it was published. An operator should
anchor `commitments.json` (or its `schedule_commitment`) to an independent, timestamped channel
before the first window opens, for example a signed and dated public release, a timestamped
repository commit, or a public log, and keep the evidence. This tooling does not perform the
anchoring; it only produces the value to anchor.

## Limits

- The operator controls the master seed. Committing the whole schedule first stops choosing a seed
  after seeing responses; it does not prove the master seed was not chosen with the schedule in view.
  A public randomness source can be mixed in by a later generator version.
- Truth stays with the private reference executors. Outside parties verify commitments and
  capsules, and truth only as far as per-case truth is published.
- Integrity predicates in the dry run are asserted, not proven (no network exchange).
