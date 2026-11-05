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

## Protocol version 0.2

New schedules use `sn87-contest-generator/0.2` (schemas `/0.2`; decision record
[ADR-0023](../architecture/ADR-0023-opening-block-seed-truth-commitment-and-reveal-deadline.md)).
Version 0.1 files stay readable and verifiable: every phase and the verify check dispatch on the
schema version of the document they read, and the 0.1 derivation is unchanged.

| Change | What it is |
|---|---|
| Opening block in the seed | `preseed = HMAC(master, frame(PRESEED_DOMAIN, schedule_id, window_id))`; the commitment published at commit is `seed_commitment = sha256(frame(PRESEED_COMMIT_DOMAIN, window_id, preseed))`, so in a 0.2 file the `seed_commitment` field commits to the pre-seed. The window seed is `HMAC(preseed, frame(WINDOW_SEED_DOMAIN_2, schedule_id, window_id, block_number, block_hash))`. The spec commitment is salted from the pre-seed |
| The block is an input | `open` and `reveal` take an injected read-only provider. `find_beacon_block` bisects a reader (`block_time_ms`, `block_hash`, and `finalized_block` or `current_block`) up to the finalized head, else up to `FINALITY_DEPTH` (12) blocks behind the head, then reads the chosen block twice and refuses if the reads differ. Nothing in `contest_window.py` reads a chain. The committed rule is `FIRST_BLOCK_AT_OR_AFTER_OPENS_AT`, and the network is named by its genesis hash |
| The block record | `{number, hash, time_ms, parent_time_ms}`, plus `depth` (0 means read at the finalized head) and, only if typed in by hand, `manual: true`. `verify` and `verify-bundle` check offline that `parent_time_ms < opens_at <= time_ms`, so only the one block the rule names passes. A block typed in with `--block-number`, `--block-hash`, `--block-time-ms` and `--parent-block-time-ms` is refused unless `--allow-manual-block` is given; it is printed loudly and marked. The block is printed (`OPENING_BLOCK`), recorded in the cases file before anything else, and uploaded in the open record before any miner is queried. A crashed open reuses the recorded block; a different block is refused (`BEACON_CONFLICT`) |
| Truth fixed at open | `open` also runs the private reference (an injectable seam), writes the private truth file with a random salt, and puts `truth_commitment` (same function as before: salted, bound to the seed commitment and the cases commitment) in the capsules file next to `cases_commitment`. The salt is derived (`HMAC(preseed, window id)`), so a lost private truth file is made again by the `truth` phase (needs `--schedule` and the master seed file) and must hash to the value published at open, else `TRUTH_HASH_DIFFERS_FROM_OPEN`. An existing file is never replaced (`TRUTH_FIXED_AT_OPEN`). The service voids a window whose truth cannot be made again with `TRUTH_LOST_AFTER_OPEN` and still publishes its reveal |
| Carried in each request | The signed request envelope gains an optional `window_commitments` object `{generator, window_id, cases_commitment, truth_commitment}`. It is part of the signed body. A server accepts it or its absence and checks its shape only |
| Refusal on a differing hash | `publish-truth`, `verify` and `contest_results.py` compare the truth file's hash and cases commitment with the capsules file published at open and refuse with `TRUTH_HASH_DIFFERS_FROM_OPEN`, or `OPEN_RECORD_MISSING` when the capsules file is absent |
| Reveal deadline | Each schedule window carries `reveal_deadline` (from `closes_at` to seven days after it); it is part of the spec, the commitments row and the capsules file. The shadow service reports a window past it with no uploaded reveal as `REVEAL_OVERDUE` |
| Whole-schedule reveal | the operator's local `reveal-schedule` command writes a bundle (schema `sn87-reveal-bundle/0.1`): per window `OPENED` (reveal plus the open record, the opening block taken from the published open record), `NOT_OPENED` (no seed; nothing was drawn) or, for 0.1, `REVEALED`. The public `verify-bundle` phase checks it against the commitments and ties every reveal to the published open records (`--open-dir`, required for 0.2); it fails on closed windows the bundle misses unless `--allow-partial`, refuses an older protocol with `--min-protocol`, and with `--index` fails on a `REVEAL_OVERDUE` window the bundle does not cover (see the [shadow cohort guide](../guides/shadow-cohort.md)) |

The reveal file of a 0.2 window holds `preseed`, `beacon`, the derived `seed` and the spec. `verify`
checks the pre-seed against the committed value, recomputes the seed from the pre-seed and the
block, and checks the spec commitment, the spec against the committed row, and, when the capsules
and truth files are present, the open record against the reveal.

**What the block hash does and does not do.** Before the opening block exists, nobody can compute
the window seed, so neither miners nor the operator can know the instances ahead of the window
(the operator knows the pre-seed, not the block hash). It removes advance knowledge only. The
operator still builds the instances, runs the private reference and controls scoring, and a block
producer could in principle influence a block hash. Trust in the scoring still needs independent
validators that construct their own challenges. Outsiders must check the block record against the
chain themselves, including that it is the first block at or after `opens_at`; this tooling does
not.

## Anchoring the commitments

The commitments file proves order only if readers know when it was published. An operator should
anchor `commitments.json` (or its `schedule_commitment`) to an independent, timestamped channel
before the first window opens, for example a signed and dated public release, a timestamped
repository commit, or a public log, and keep the evidence. This tooling does not perform the
anchoring; it only produces the value to anchor.

## Limits

- The operator controls the master seed. Committing the whole schedule first stops choosing a seed
  after seeing responses; it does not prove the master seed was not chosen with the schedule in view.
  Version 0.2 mixes the opening block hash into each window seed, which removes the operator's
  advance knowledge of the instances (see "Protocol version 0.2" for its limits).
- Truth stays with the private reference executors. Outside parties verify commitments and
  capsules, and truth only as far as per-case truth is published.
- Integrity predicates in the dry run are asserted, not proven (no network exchange).
