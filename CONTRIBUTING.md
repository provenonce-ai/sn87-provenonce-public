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
uv run pytest -q                # tests that need the private reference executors skip; scorer
                                # tests run against the published truth in protocol/golden_truth
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
   Add a change note (see [Writing a change note](#writing-a-change-note)).
3. Open a pull request that says what changed and why. There is no sign-off or CLA step; by
   contributing you agree your change is under the MIT License. Maintainers review for the rules
   above, and CI must be green.

## Writing a change note

Every pull request that changes `src/`, `scripts/` or a public document adds one short note, so
that release notes are written by the people who know the change. Create
`changes/<name>.<type>.md`, where `<type>` is `added`, `changed`, `fixed`, `security` or `docs`
and `<name>` is a short lower-case label (letters, digits, `-` and `_`) or the pull request
number. Names are checked with the same word list as the text. The file holds one or two
plain sentences for someone who has not followed the project: what is different for them, and
where to look. No bullet marker, no heading, at most 600 characters.

Good:

- `changes/platform-policy.changed.md`: "Linux and macOS are now tested in CI on Python 3.12 and
  3.13, and Windows is supported through WSL2. Native Windows is not supported."
- `changes/doc-path-check.added.md`: "`scripts/check_doc_paths.py` fails when a document or
  script names a repository file that does not exist, so a moved file cannot leave a dangling
  pointer."

Bad:

- "Fix bug in server." It does not say which bug, what a reader will see, or where to look.
- "Refactor the canonical layer to harmonise the serialisation boundary per ADR discussion." It is
  written for the author, uses terms a reader has not met, and says nothing about the effect.

Write what changed for a reader, not what you did. Never put secrets, local paths, e-mail
addresses, names of people or organisations outside the project, or statements about funds or
launch dates in a note. `scripts/check_release_notes.py` runs in CI, ignores letter case and fails
on those. When a change has nothing a reader can see (a test-only change, a rename inside a
private module), ask a maintainer to add the label `no-changelog` instead of writing a note; the
`changelog` check on the pull request is advisory and passes with that label.

## Good first issues

- Add a second worked example to `docs/quickstart/miner.md` that sends
  `build_case("fresh_review")` to the localhost server, and record the response you get.
- Add miner test vectors: a capsule whose evidence commitment is broken, and the exact 4xx the
  localhost server (`scripts/miner_serve.py`) returns for it, in `tests/test_miner_serve.py`.
- Add filtering to the `--json` output of `scripts/verify_attestation.py` (for example only the failing or
  unverified runs) with a test in `tests/test_verify_attestation_public.py`.
- Add a `--run RUN_ID` option to the verifier that checks one attested run, with a test.
- Fill gaps in `docs/protocol/v0alpha1-field-traceability.md` where a field names no test.
