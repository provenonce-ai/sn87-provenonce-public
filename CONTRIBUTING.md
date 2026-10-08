# Contributing

SN87 is alpha protocol software on public testnet netuid 582; results so far are conformance
evidence only (see [LIMITATIONS.md](LIMITATIONS.md)). Contributions must preserve these rules:

1. Source precedes synthesis; label proposals and unresolved behavior explicitly.
2. Do not weaken schema, Evidence, response-state, privacy, or integrity invariants for convenience.
3. Do not add secrets, raw Tenant Evidence, hidden challenge instances, production topology, or proprietary runtime code.
4. Add or update conformance tests and traceability for every protocol change.
5. Keep the full history safe for public reading.
6. Do not claim mainnet, production, performance, adoption, or universal assurance without direct evidence and approval.

## Development setup

```bash
uv sync --locked --all-extras   # Python 3.12+, versions pinned by uv.lock
uv run ruff check .
uv run pytest -q                # tests that need the private reference executors skip
```

Scoring has one scorer, one canonicalizer and one profile loader (`scoring.py`, `canonical.py`,
`profile.py`); a new task family is a new `ClassBinding` in `classes.py`, never a new scorer, and
scorers carry no default parameters ([migration note](docs/releases/MIGRATION-scorer-rebuild.md)).
Cost coefficients stay 0 until Provenonce approves a profile that activates them. New files must
be classified in `PUBLIC_MANIFEST.json` (deny > private > review_required > allow);
`scripts/check_manifest.py` checks this and runs in CI.

Changes to protocol objects or canonical bytes require an accepted architecture decision and new
reference vectors. Scoring parameters live only in committed profiles; a change is a new profile
version, never hidden configuration ([profile application](docs/protocol/profile-application.md)).
No chain or wallet writes without approval from Provenonce.

## Filing an issue and getting an answer

Open an issue from the [issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose);
blank issues are off so that each report carries what is needed to act on it.

| Template | Use it for | Include |
|---|---|---|
| Setup failure | An install or documented step that fails | Platform, Python and uv versions, the document and step, the exact command, expected and actual result, the last 40 lines of output |
| Scoring question | A score you cannot explain or reproduce | Class, public fixture or window id, profile id, observed and expected score, how to reproduce |
| Security report | A suspected vulnerability | Nothing. Do not put details in an issue; send them privately as described in [SECURITY.md](SECURITY.md) |

Never include secrets, wallet material, raw Tenant Evidence or hidden challenge material in an
issue or pull request.

Triage is done by the maintainers listed in `.github/CODEOWNERS`. The cadence is a triage sweep on
Wednesdays and answers on Fridays, US Pacific time. This is a cadence, not a service-level
agreement: a busy week can slip, and a slip is stated on the issue rather than left silent. Each
sweep records its inputs (the issues and questions it covered) and its triage outcome (owner,
label and next step), and the outcome is posted back on the issue. Security reports follow the
handling in [SECURITY.md](SECURITY.md) instead.

## How builders enter

A builder adds a new task family as a new class binding (`ClassBinding` in `scoring.py`, registered
in `classes.py`), never as a new scorer. The one scorer, one canonicalizer and one profile loader stay
unchanged; the binding supplies the capsule and differential validators, the defect severities, the
generator and the baseline, and the family is scored by the existing code under a committed profile.
Start from [`docs/protocol/cmt-v0.1.md`](docs/protocol/cmt-v0.1.md), which is a candidate schema (not
adopted). A scoring change is a new profile version, and admission of any new class to live scoring
needs approval from Provenonce. Open a scoring question issue, or a pull request with the proposed
binding and its tests.

## Pull requests

1. Fork the repository and branch from `main`.
2. Make the change with its test; run `uv run ruff check .` and `uv run pytest` (both must pass).
3. Open a pull request that says what changed and why. There is no sign-off or CLA step; by
   contributing you agree your change is under the MIT License. Maintainers review for the rules
   above, and CI must be green.

## Good first issues

- Add a second worked example to `docs/quickstart/miner.md` that sends
  `build_case("fresh_review")` to the localhost server, and record the response you get.
- Add miner test vectors: a capsule whose evidence commitment is broken, and the exact 4xx the
  localhost server (`scripts/miner_serve.py`) returns for it, in `tests/test_miner_serve.py`.
- Add filtering to the `--json` output of `scripts/verify_attestation.py` (for example only the failing or
  unverified runs) with a test in `tests/test_verify_attestation_public.py`.
- Add a `--run RUN_ID` option to the verifier that checks one attested run, with a test.
- Fill gaps in `docs/protocol/v0alpha1-field-traceability.md` where a field names no test.
