# Implementation status

Generated from `sn87_provenonce.bundle.STATUS_MATRIX`, the same matrix every evidence bundle
carries (`status_matrix`); `tests/test_bundle.py` fails if this table drifts from it or if any
cited symbol or test does not exist. Columns: **implemented** (module:symbol), **enabled by
profile** (a committed profile turns it on), **tested** (pytest node), **deployed** (observed on a
live target). The only live target is public testnet netuid 582, and its rows are conformance
evidence only ([LIMITATIONS](../../LIMITATIONS.md)). CI status is not deployment status.

<!-- BEGIN STATUS_MATRIX -->
| Item | Implemented | Enabled by profile | Tested | Deployed |
|---|---|---|---|---|
| Eq.1 integrity gate | `sn87_provenonce.scoring:Integrity` | yes | `tests/test_scoring.py::test_every_integrity_failure_is_zero` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Eq.3-6 detection and binary evidence credit | `sn87_provenonce.scoring:score_response` | yes | `tests/test_scoring.py::test_duplicate_is_false_positive` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Eq.7 calibration | `sn87_provenonce.scoring:calibration` | yes | `tests/test_scoring.py::test_abstention_and_na_calibration` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Eq.12 composite (Eq.9 per-perturbation base: no separate code) | `sn87_provenonce.scoring:geometric` | yes | `tests/test_scoring.py::test_composite_is_na_when_empty` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Eq.13 epoch estimate | `sn87_provenonce.scoring:epoch_estimate` | yes | `tests/test_scoring.py::test_epoch_floor_ceiling_and_quantile` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Eq.14-15 preference row | `sn87_provenonce.scoring:preference_row` | yes | `tests/test_golden.py::test_first_light_row_reproduces` (private suite) | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Eq.2 rule score | no | no | `NOT_TESTED` | no |
| Eq.8 utility | no | no | `NOT_TESTED` | no |
| Eq.10 robustness | no | no | `NOT_TESTED` | no |
| Eq.11 efficiency (neutral eta=1 only) | `sn87_provenonce.scoring:EFFICIENCY_STATUS` | no | `tests/test_scoring.py::test_inactive_dimensions_are_na` | no |
| Committed profile applied | `sn87_provenonce.profile:load` | yes | `tests/test_profile.py::test_profile_drives_result` | no |
| Canonicalizer gra/0.1 | `sn87_provenonce.canonical:canonical_bytes` | yes | `tests/test_gra_canonical.py::test_canonical_attacks_rejected` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Signed transport and replay protection | `sn87_provenonce.pilot.transport:verify_bytes` | yes | `tests/transport/test_signed_endpoint.py` | `FIRST_LIGHT_TESTNET_582_BLOCK_8102381` |
| Chain target dry run | `scripts/pilot_chain_dry_run.py:dry_run` (private suite) | yes | `tests/test_golden.py::test_first_light_row_reproduces` (private suite) | `FIRST_LIGHT_TESTNET_582_BLOCK_8102381` |
| Plain weight submission (approval-gated) | `scripts/pilot_chain_weights_institutional_v02.py:make_manifest` (private suite) | yes | `tests/pilot/test_institutional_v02_scripts.py` (private suite) | `FIRST_LIGHT_TESTNET_582_BLOCK_8102381` |
| Commit-reveal submission | no | no | `NOT_TESTED` | no |
| Matched public-contract baseline (reported, never weighted) | `sn87_provenonce.baselines:BASELINES` | yes | `tests/test_separation.py::test_baseline_matches_truth_and_null_result_is_kept` | no |
| Truth/candidate separation (import graph) | `sn87_provenonce.baselines:METHOD_ID` | yes | `tests/test_separation.py::test_baseline_import_closure_excludes_evaluator_only` | no |
| Truth/candidate separation (runtime: baseline code neither imports nor needs truth; no process isolation) | `sn87_provenonce.bundle:run_baseline` | yes | `tests/test_separation.py::test_baseline_runs_with_evaluator_only_modules_blocked` | no |
| Cost record beside scores | `sn87_provenonce.bundle:cost_record` | yes | `tests/test_bundle.py::test_fixture_bundle_end_to_end` | no |
<!-- END STATUS_MATRIX -->

A reference marked `(private suite)` names a file of Provenonce's private source repository that is
not part of this one: `scripts/pilot_chain_*` (private suite), `tests/pilot/` (private suite) and
`tests/test_golden.py` (private suite). Those rows can be checked only inside Provenonce. The matrix is serialised into every evidence bundle,
whose digests are committed, so the bundle names those files as they are and only this rendering
carries the marker. The signed transport row is described in
[ADR-0005](../architecture/ADR-0005-signed-http-and-replay-boundary.md) (status Implemented).

## Items outside the evidence-bundle matrix

The matrix above is serialised into every evidence bundle, so it is not edited by hand. These
items are tooling around the contest, admission and source paths. The table is maintained by
hand; `tests/test_implementation_status_extra.py` checks that every cited symbol and test exists.
"Deployed" is `no` unless a live observation is cited: none of these is deployed on a target
that can be verified from this repository.

| Item | Implemented | State | Tested | Deployed |
|---|---|---|---|---|
| Miner sender allowlist (a permit snapshot and a per-sender rate limit; trusted senders by address) | `sn87_provenonce.pilot.sender_policy:SenderPolicy` | On by default in sn87-miner serve; --allow-any-sender turns it off (loopback only) | `tests/transport/test_sender_policy.py::test_a_hotkey_with_validator_permit_is_accepted` | no |
| Contest protocol 0.2 (opening-block seed, truth fixed at open, reveal deadline, `window_commitments` in each request) | `scripts/contest_window.py:request_commitments` | Inactive: no schedule of this version is deployed | `tests/transport/test_trusted_sender_window_commitments.py::test_the_trusted_shadow_signer_is_answered_with_the_open_record` | no |
| MIN-4 profiles (`IC-FIRST-LIGHT-MIN-4`, `GRA-RELEASE-MIN-4`) | `sn87_provenonce.profile:load` | Inactive: committed, active on no weight path | `tests/test_profile_min4_rules.py::test_new_profiles_are_pinned_and_every_older_profile_is_byte_identical` | no |
| Weight gate (a candidate must beat every public method) | `sn87_provenonce.bundle:require_weight_eligible` | Inactive: wired into no live weight path | `tests/test_weight_gate.py::test_a_candidate_above_every_public_method_is_eligible` | no |
| HMAC text commitments (customer-held key) | `sn87_provenonce.sources.mapping:map_source` | Committed; the plain default is unchanged | `test_text_commitment_hmac.py::test_customer_export_defaults_to_hmac_and_differs_from_plain` (private suite) | no |
| Admission uplift rule (strictly above the public baseline on the window's instances) | `scripts/admission_plan.py:evaluate_criteria` | Proposed: cannot be met under today's windows | `tests/test_admission_plan.py::test_beating_the_baseline_in_every_window_passes` | no |

Not in the matrix, and not on any weight path: research code in `simulation/` and `runtime/`
(v0alpha1 objects and the NFC-normalizing v0alpha1 canonicalizer, kept for historical readers),
and offline evidence integrity in `evidence.py` and `evidence_filesystem.py`.
Field-level source of v0alpha1 objects: [v0alpha1-field-traceability.md](v0alpha1-field-traceability.md).
