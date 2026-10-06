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
| Eq.14-15 preference row | `sn87_provenonce.scoring:preference_row` | yes | `tests/test_golden.py::test_first_light_row_reproduces` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Eq.2 rule score | no | no | `NOT_TESTED` | no |
| Eq.8 utility | no | no | `NOT_TESTED` | no |
| Eq.10 robustness | no | no | `NOT_TESTED` | no |
| Eq.11 efficiency (neutral eta=1 only) | `sn87_provenonce.scoring:EFFICIENCY_STATUS` | no | `tests/test_scoring.py::test_inactive_dimensions_are_na` | no |
| Committed profile applied | `sn87_provenonce.profile:load` | yes | `tests/test_profile.py::test_profile_drives_result` | no |
| Canonicalizer gra/0.1 | `sn87_provenonce.canonical:canonical_bytes` | yes | `tests/test_gra_canonical.py::test_canonical_attacks_rejected` | `REPLAY_EQUIVALENT_TO_FIRST_LIGHT_BLOCK_8102381` |
| Signed transport and replay protection | `sn87_provenonce.pilot.transport:verify_bytes` | yes | `tests/pilot/test_transport.py` | `FIRST_LIGHT_TESTNET_582_BLOCK_8102381` |
| Chain target dry run | `scripts/pilot_chain_dry_run.py:dry_run` | yes | `tests/test_golden.py::test_first_light_row_reproduces` | `FIRST_LIGHT_TESTNET_582_BLOCK_8102381` |
| Plain weight submission (approval-gated) | `scripts/pilot_chain_weights_institutional_v02.py:make_manifest` | yes | `tests/pilot/test_institutional_v02_scripts.py` | `FIRST_LIGHT_TESTNET_582_BLOCK_8102381` |
| Commit-reveal submission | no | no | `NOT_TESTED` | no |
| Matched public-contract baseline (reported, never weighted) | `sn87_provenonce.baselines:BASELINES` | yes | `tests/test_separation.py::test_baseline_matches_truth_and_null_result_is_kept` | no |
| Truth/candidate separation (import graph) | `sn87_provenonce.baselines:METHOD_ID` | yes | `tests/test_separation.py::test_baseline_import_closure_excludes_evaluator_only` | no |
| Truth/candidate separation (runtime: baseline code neither imports nor needs truth; no process isolation) | `sn87_provenonce.bundle:run_baseline` | yes | `tests/test_separation.py::test_baseline_runs_with_evaluator_only_modules_blocked` | no |
| Cost record beside scores | `sn87_provenonce.bundle:cost_record` | yes | `tests/test_bundle.py::test_fixture_bundle_end_to_end` | no |
<!-- END STATUS_MATRIX -->

Rows whose implemented or tested column names `scripts/pilot_chain_*`, `tests/pilot/` or
`tests/test_golden.py` point at files that live in Provenonce's private source repository and are
not part of this one. The matrix is serialised into every evidence bundle, so it names them as
they are; those rows can be checked only inside Provenonce.

Not in the matrix, and not on any weight path: research code in `simulation/` and `runtime/`
(v0alpha1 objects and the NFC-normalizing v0alpha1 canonicalizer, kept for historical readers),
and offline evidence integrity in `evidence.py` and `evidence_filesystem.py`.
Field-level source of v0alpha1 objects: [v0alpha1-field-traceability.md](v0alpha1-field-traceability.md).
