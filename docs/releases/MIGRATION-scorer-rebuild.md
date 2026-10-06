# Migration: scorer rebuild (one scorer, one canonicalizer, one profile loader, one bundle)

The scorer rebuild replaced the duplicated pilot and institutional scoring and
serialization modules with single modules. This note is for anyone with code or notes written
against the earlier layout. It is a description of what the repository contains now; it does not
change any protocol object or canonical byte.

## Removed modules and replacements

| Removed | Replacement |
|---|---|
| `sn87_provenonce/pilot/scoring.py` | `sn87_provenonce/scoring.py` (one scorer for every class) |
| `sn87_provenonce/institutional_v02/scoring.py` | `sn87_provenonce/scoring.py` |
| `sn87_provenonce/pilot/serialization.py` | `sn87_provenonce/canonical.py` (`canonical_bytes`, `parse_canonical`, `object_commitment`, `evidence_commitment`, `check_timestamp`, `lp`; canonicalizer id `CANONICALIZER_ID`) |
| `sn87_provenonce/institutional_v02/serialization.py` | `sn87_provenonce/canonical.py` (commitments keep both recorded schema domains, `gra/0.1` and `institution/0.2`) |
| `sn87_provenonce/pilot/fixtures.py` (`capsule_from_fixture`, `fixture_run`, `recorded_fixture_run`) | `pilot/contracts.capsule_from_fixture`; `bundle.fixture_run(binding)`; the registered classes in `classes.py` |

## Truth moves to evaluator-only modules

The evaluator-only modules named here are private and are not part of this repository.

| Was | Now |
|---|---|
| `pilot/contracts.agreed_truth`, `make_differential`, `required_refs` | `pilot/reference.py` (evaluator-only) |
| `institutional_v02/contracts.agreed_truth`, `make_differential` | `institutional_v02/references.py` (evaluator-only) |
| `simulation/type_c.py`: `execute_state_machine`, `execute_relational`, `compare_reference_executions`, `ReferenceOutcome`, `run_type_c_simulation` | `simulation/type_c_reference.py` (evaluator-only); `from sn87_provenonce.simulation import <name>` still works (exports now resolve lazily, PEP 562) |
| (none) | `baselines.py`: the matched public-contract baseline per class; `ClassBinding.baseline` and `ClassBinding.role` (`"reference"`) are new fields |

The `contracts` modules are now the public contract only (capsule and differential validation).
Bundles gain method roles, a configured `baseline` and a per-method `comparison`.

Module-level `PROFILE` and `DIMENSION_WEIGHTS` constants in the removed scorers are gone. Operative
parameters now come only from the committed profile documents in
`src/sn87_provenonce/profiles/*.json`, loaded with `profile.load(profile_id)`.

## API changes

- **No defaults.** Scorers carry no default parameters. Every operative value is parsed from the
  committed profile document; a missing, unparsed, unsupported or mismatched value fails closed
  with `PROFILE_NOT_APPLIED`. Nonzero cost coefficients are refused
  (`COEFFICIENT_ACTIVATION_NOT_AUTHORIZED`).
- **`score_response(binding, capsule, truth, response, integrity)`.** The first argument is a
  `ClassBinding` (from `classes.BINDINGS`), which carries the profile, the grammar validators,
  the reference, the reference methods (`candidates`) and the matched `baseline`. A new family is a new binding, never a new scorer.
- **`epoch_estimate(scores, valid, profile)`.** Takes the `Profile`; every assigned response stays
  in the sample and an invalid or missing one counts as zero.
- **`preference_row(estimates, profile)`.** Takes the `Profile` (theta and gamma come from it).
- **`wire(value)`.** The one report-boundary emitter: floats become `.17g` decimal strings
  (binary64 round-trip), nothing else changes. Equations 2, 8 and 10 serialize as `"NA"`, never `0`;
  Equation 11 keeps its neutral eta = 1 with an inactive status.
- **Evidence bundle.** `bundle.fixture_run(binding)` and the private sealed-run replay writer emit
  the one evidence bundle (mode, identifiers, denominators, `NA`, cost beside scores, status matrix).

## Verification pointers

- Golden: the First Light row reproduces byte for byte on replay of the sealed run, which needs
  private custody.
- `docs/protocol/profile-application.md`, `docs/protocol/wire-rules.md`,
  `docs/protocol/evidence-bundle.md`, and [`LIMITATIONS.md`](../../LIMITATIONS.md).
