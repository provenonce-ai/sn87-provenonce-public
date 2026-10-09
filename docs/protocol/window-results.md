# Per-window results `sn87-contest-window-results/0.1`

`scripts/contest_results.py` writes one record per closed contest window: `window_<id>.json` and a
markdown page `window_<id>.md` built only from that record. The protocol that produces the window is
in [contest-windows.md](contest-windows.md); the decision record is
[ADR-0020](../architecture/ADR-0020-contest-windows-and-window-sizing-profile.md).

This is shadow output. It sets no weight, touches no chain and does not change testnet weights. Every
number comes from the input files and the committed profile; the script has no clock, no randomness
and no typed figure, and its output is byte-identical for identical inputs. Floats leave as
17-significant-digit strings, as in [wire-rules.md](wire-rules.md).

## Inputs

| File | Holds |
|---|---|
| `window_<id>.capsules.json` | the window's capsules in position order, times, and `cases_commitment` |
| `window_<id>.truth.json` | per case: qid, family, track, capsule commitment, truth record or a reference failure; `seed_commitment`, `cases_commitment`, `salt` and the salted `truth_commitment`, which the script recomputes |
| `window_<id>.responses.json` | `sn87-contest-responses/0.1`: per method `{method_id, uid, role, responses}`; each response entry holds `response` (or null), optional `integrity` (the six booleans) and optional `cost` (`wall_time`, `cpu_time`, `model_tokens`, `oracle_time`) |
| `commitments.json`, `window_<id>.reveal.json` | optional; with both, the seed is verified and the regenerated instances are compared with the truth file |

`role` is `candidate` or `baseline`. The baseline row must be `public_contract_baseline`; it is
scored like every other method and its responses are recomputed from the public baseline code.
A missing response entry is a `missing` failure. A case whose truth is null (a reference failure)
leaves the admitted supply for every method.

## Two disclosure levels

`disclosure` is `SCORES_ONLY` or `TRUTH_DERIVED`.

- `SCORES_ONLY` (default) is what a closed window publishes before the seed is revealed and before
  truth publication is authorized: window identity and times, case count, the scoring profile, the
  cases commitment, the salted truth commitment, and per method only `estimate`, `eligible`,
  `reason` and `cost`.
- `TRUTH_DERIVED` adds everything that is computed from truth: `truth_state_counts`, the admitted and
  failure counts, `status`, and per method `agreement`, `confusion`, `by_family`, `failures`,
  `diagnostic` and the score `dimensions`, `lower`, `upper`. It needs a closed window, a verified
  reveal (`--commitments` and `--reveal`) and `--publish-closed-window-truth`, the same conditions
  as per-case truth. Whether to allow it is an open decision (ADR-0020).

### What a score alone reveals

The scores are published in both levels, and they constrain the truth. On a task with three states
and few cases, an estimate of 1 under a profile where only correct answers score 1 means every
admitted scored case matched the truth. A method that always answers one state has an estimate equal
to the share of cases whose truth is that state, under a profile that scores a wrong state at the
floor. Comparing two methods' estimates, and eligibility (`SAMPLE_FLOOR` means reference failures
exceeded the tolerance), also leaks a little. What stays hidden is which case has which truth and the
confusion structure. The reveal makes the family of every case public in any event, and the family
determines the truth state under current reference behavior.

## Guards

- The script refuses before the window's close time (`RESULTS_BEFORE_CLOSE`).
- `--publish-closed-window-truth` selects `TRUTH_DERIVED` and needs a verified reveal; without the
  reveal the script refuses (`TRUTH_PUBLICATION_BEFORE_REVEAL`). Per-case rows (`cases`, below) need
  the same flag (`TRUTH_PUBLICATION_NOT_AUTHORIZED` otherwise).
- `--profile` selects a committed profile by id (default `IC-FIRST-LIGHT-MIN-1`). An unregistered id
  or an altered document fails closed (`PROFILE_NOT_APPLIED`). Selecting a profile here scores a
  record; it activates nothing.

## Record

Top level: `schema_version`, `claim` (`SHADOW_RESULTS_NOT_WIRED_TO_WEIGHTS`), `note`, `disclosure`, `window`,
`profile`, `evidence`, `truth_state_counts`, `methods`, and `cases` only when per-case rows were
published.

`window`

| Field | Meaning |
|---|---|
| `window_id`, `opens_at`, `closes_at` | from the capsule file |
| `cases` | all instances in the window |
| `assigned_scored` | scored-track instances assigned |
| `admitted_scored`, `admitted_diagnostic` | instances with truth, per track |
| `reference_failures`, `reference_failure_qids` | instances without truth; they leave the supply |
| `minimum_assignments` | the scoring profile's minimum |
| `reference_failures_tolerated` | `assigned_scored - minimum_assignments`, never below 0 |
| `status` | `VALID`, or `VOID_SAMPLE_FLOOR` when `admitted_scored` is below the minimum |
| `cases_commitment`, `truth_commitment` | commitments recomputed from the files |

`profile`: `profile_id`, `profile_commitment`, `state_payoff` (whether the profile carries the
ADR-0019 scoring rules).

`evidence`: `same_cases_for_every_method` (always true: one capsule set, one truth set),
`baseline_recomputed_from_public_code` (the baseline's published responses equal what the public
baseline code returns for the same capsules), `integrity` (`ASSERTED_FIXTURE` unless the responses
file says its integrity booleans come from verified transport).

`methods[]`, one per method, candidates first and the baseline last:

| Field | Meaning |
|---|---|
| `method_id`, `uid`, `role` | identity as supplied (`uid` is null until assigned) |
| `score` | `estimate`, `eligible`, `reason`, `admitted`, `evaluable`, `raw_invalid_or_missing_rate`, `lower`, `upper`, `dimensions` (means over valid scored responses): the scorer's `epoch_estimate` over the scored track |
| `diagnostic` | `assigned`, `mean_score`, `epoch_input` (always false) |
| `agreement` | `state_all`, `state_scored`, `state_diagnostic`, `exact_all`; each `{agree, n, fraction}` |
| `confusion` | recomputed truth state (rows) by response state or `NO_VALID_RESPONSE` (columns), counts over all admitted cases |
| `by_family` | per family: `n`, `state_agreement`, `mean_score` |
| `failures` | `invalid_or_missing` and `by_reason` (`schema`, `missing`, or an integrity predicate) |
| `cost` | the six dimensions (`wall_time`, `cpu_time`, `bytes_in`, `bytes_out`, `model_tokens`, `oracle_time`): `value`, `unit`, `source`, `missing`, `n`. Byte counts are measured from the canonical files; other dimensions are reported with the responses or `NA` with the reason `NOT_REPORTED` |
| `versus_baseline` | for candidates: `estimate_delta`, `result` (`ABOVE_BASELINE`, `NULL_NO_HEADROOM`, `BELOW_BASELINE`, or `NA`), `agreement_delta` (state agreement over all cases, method minus baseline) |
| `recomputed_from_public_code` | baseline row only |

State agreement is the fraction of admitted cases in which a valid response's state equals the
recomputed truth state; an invalid or missing response counts as a disagreement. Exact agreement
also requires the same set of finding codes. Agreement and score are both reported because they can
disagree: a method that over-claims on cases where the references abstain loses agreement even where
a profile scores the case at the floor for everyone.

`cases[]` (only with the policy flag): `position`, `qid`, `family`, `track`, `truth_state`, and per
method `{state, score}`.

## Reading a page next to the data

The markdown page repeats the record in tables: window and status, scoring profile, one row per
method (estimate, eligibility, agreement over the scored track and over all cases, failures,
comparison with the baseline), then per method the confusion table, the family table, failure reasons
and the cost table. It adds no number that is not in the record.
