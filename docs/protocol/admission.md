# Admission of outside uids as plan versions

**Status.** Tooling and rules for review. Nothing here changes the approved plan, any weight
row, any chain state or any registration. Alpha, testnet only ([LIMITATIONS.md](../../LIMITATIONS.md)).
Every document the tools produce is marked `PROPOSED_NEEDS_AUTHORITY_APPROVAL`.

A uid on testnet 582 can register without being weighted. This document says how a uid gets from
registered to weighted in steps that anyone can check: each step is a new version of the plan,
approved by the maintainers outside this repository, and the criteria for the last step are
published as a file a machine can evaluate.

## The approved plan does not change

The approved plan is a document with a digest. It names the uids that are weighted today. Admission
never edits it. A proposal reads the plan and writes a new document with a new digest; the parent
digest is recorded inside the new document, so the lineage is part of what the new digest covers.
The new document keeps every field of the parent and adds an `admission` section and a version
number.

The tool that does this is `scripts/admission_plan.py`. It holds no key, reads no ledger, sends
nothing and uses only the standard library, so a miner can run its checker on their own results.

## Stages

| Stage | What it means | In a weight row |
|---|---|---|
| `local` | The uid runs the miner guide against local fixtures. Nothing is queried or published. | No |
| `shadow` | The uid has a valid announced endpoint. It receives the same capsules as every other miner in each window, is scored with the public scorer, and its per-window result is published with `weight: 0`. | No, never |
| `weighted` | The uid may be in a weight row, after the criteria pass and an approval record cites the plan version. | Yes, only with the approval reference |

Rules the tool enforces when it builds a version:

* The uids in the approved plan cannot be re-staged, and uid 0 (the validator) cannot be staged.
* `shadow` needs an endpoint record that passes the checks below and names the same hotkey.
* `weighted` needs the uid to be `shadow` in an approved parent, under the same hotkey, and the
  raw window results. The tool evaluates the criteria again from those results; it accepts no
  report from the caller. The criteria digest must be the one pinned in the parent plan (a
  `shadow` proposal pins it), and the version records the criteria digest, the report digest and
  the digests of the result records it used.
* The same hotkey cannot be staged on two uids, or on a uid of the approved plan.
* A version built on another version needs the parent's approval reference to be non-empty.
* Moving a uid down a stage is a proposal like any other and needs no criteria.

## Approval

Every version carries `"approval": {"reference": ""}`. The tool leaves the reference empty. An
approval is a record made by the maintainers outside this repository that cites the version's
`plan_digest`. The reference is then written next to the document. It is outside the digested
`plan` object, so filling it in does not change the digest the approval cites.

`compose_row` in the same module is the one function that turns per-uid values into a row for a
plan document. It first verifies the whole document: the digest, the parent digest, the approval
reference format, and that every `weighted` entry carries its criteria and evidence digests and
the pinned criteria digest. A document that fails is refused. It then lists the uids that may
appear: the uids of the approved plan, plus `weighted` uids that carry a non-empty approval
reference. It refuses any other uid and any value that is not a finite, non-negative number. This tooling does not contact the live approval gates, and the live weight
path does not call it. Wiring a weighted uid into live weights is a separate change that needs its
own approval.

A fabricated `weighted` document is not stopped by the tooling alone. The tooling checks that a
document is internally consistent; whether a weighted uid is honoured is gated only by the external
approval record that cites the document's digest, and nothing in this tree reads that record.

## Shadow scoring

For a uid in `shadow`, the maintainers' shadow tooling does the following in each window. That
tooling is operator-only and is not part of this tree; this tree holds the plan versions, the
criteria and the checker that consume its published results. How an outside miner applies, and
the proposed criteria for leaving shadow, are on the public page
[shadow-cohort.md](../guides/shadow-cohort.md).

1. Reads the chain (read only) and confirms the uid still holds the announced hotkey.
2. Sends each capsule of the window to the announced endpoint through the signed client. The
   request is signed by the validator, and the response must verify under the announced hotkey and
   bind to the request.
3. Validates each reply with the task class's differential validator and scores the window with
   the public scorer under the committed profile.
4. Publishes one result per uid and window (`sn87-shadow-window-result/0.1`): counts of queried,
   valid, invalid and unavailable replies, the integrity failure codes, the estimate, the seed,
   `stage: shadow` and `weight: 0`, and a digest over the record.

A reply that fails the response checks (identity, binding, signature, replay, media type) is an
integrity failure. A timeout, a refused connection or a rejected request is unavailability. A
failure of the validator's own replay store voids the window and says nothing about the miner.

A shadow score cannot reach a row by construction. The result is a record, not a number. The
shadow code reads only the score summary of the scorer output, never the preference row, and
neither imports nor calls the u16 quantizer or any weights module; the maintainers' private tests
check its imports against an allowlist, check what an import loads, and run the flow with the
quantizer patched to raise. `compose_row` refuses a uid that is not eligible; the public tests for
that are in `tests/test_admission_plan.py`.

## Endpoint record

The minimal input for a uid is a JSON record:

```text
{ "schema_version": "sn87-endpoint-record/0.1", "netuid": 582, "uid": 3,
  "hotkey": "<SS58>", "endpoint": "https://<host>[:port]",
  "issued_at_ms": <integer>, "expires_at_ms": <integer> }
```

The signed miner announcement is accepted in its place (its `announcement` object is read, with
the `sn87-miner-announcement/0.1` schema). The checker validates the text of the record: HTTPS
origin, no path, query or credentials, not a local host, not a non-global address, correct netuid,
hotkey form and match, not expired, not issued in the future. It does not verify a signature
itself. A signature verifier is passed in by the caller; without one the signature is reported
`NOT_CHECKED`, and criteria that require a verified signature fail.

## Criteria

`python scripts/admission_plan.py criteria` writes a criteria document with these rules:

| Rule | Meaning |
|---|---|
| `consecutive_windows` | The current latest N window indexes (up to a caller-supplied current window) must all be present |
| `min_valid_responses_per_window` | Valid replies required in each of those windows |
| `max_integrity_failures_per_window` | Integrity failures allowed in each of those windows (default 0) |
| `require_endpoint_announcement_valid` | The endpoint record must pass the checks |
| `require_signature_verified` | The record's signature must have been verified |
| `results_must_be_shadow_with_weight_zero` | Always on: a result that is not `shadow` with weight 0 fails |

The checker (`python scripts/admission_plan.py check`) prints `PASS` or `FAIL` with one reason per
problem and exits 0 only on `PASS`. The checker needs the current window index (`--now-window`) and
recomputes everything from the raw result records. Result records are type-checked and their
counts must add up (valid, invalid, unavailable and integrity failures equal queried); a record
that fails is a reason, never an error. Reason codes: `CRITERIA_DIGEST_OR_RULES_INVALID`,
`NOW_WINDOW_INVALID`, `RESULT_WINDOW_IN_THE_FUTURE`, `RESULT_FIELD_INVALID_*`,
`RESULT_COUNTS_INCONSISTENT`,
`ENDPOINT_RECORD_MISSING`, `ENDPOINT_*` (one per failed endpoint check), `ENDPOINT_SIGNATURE_NOT_VERIFIED`,
`RESULT_SCHEMA_INVALID`, `RESULT_WINDOW_INVALID`, `RESULT_DIGEST_INVALID`, `RESULT_HOTKEY_MISMATCH`,
`RESULT_NOT_SHADOW_WEIGHT_ZERO`, `DUPLICATE_WINDOW`, `INSUFFICIENT_WINDOWS`, `MISSING_WINDOW`,
`INTEGRITY_FAILURE`, `TOO_FEW_VALID_RESPONSES`. An older failure outside the latest N windows does
not count; a gap inside them does. The report has its own digest and is evidence for the approval
record; a `weighted` proposal recomputes it instead of trusting it.

`check` verifies the endpoint record's signature with the repository's miner announcement verifier
by default (schema, sr25519 signature, netuid, hotkey, endpoint rule, freshness; rollback against
earlier records is not checked). Only a signed announcement can pass; a minimal unsigned record
reports `ENDPOINT_SIGNATURE_INVALID`. `--signature-verifier MODULE:FUNCTION` replaces it with a
callable that gets the record and returns True only if the signature verifies. Results must also
carry the evaluated `--netuid`. Criteria created with `--allow-unverified-signature` skip the signature check, as an explicit choice.

## Commands

```bash
uv run python scripts/admission_plan.py criteria --criteria-id ID --windows N \
    --min-valid-responses M --out criteria.json
uv run python scripts/admission_plan.py check --criteria criteria.json --results RESULTS_DIR \
    --uid U --hotkey SS58 --netuid 582 --endpoint-record record.json --now-ms NOW --now-window W
uv run python scripts/admission_plan.py propose --parent PLAN.json --uid U --stage shadow \
    --hotkey SS58 --endpoint-record record.json --now-ms NOW --criteria criteria.json --out DIR
# weighted: also --results RESULTS_DIR --now-window W, on an approved version that pins the criteria
```

Outputs are create-only: an existing file is an error, never overwritten.

## Open decisions for the maintainers

* The values of the criteria (`N`, `M`, the integrity allowance) and whether a verified signature
  is required. The tool takes them as explicit arguments and marks them as proposals.
* The window cadence and the schedule of plan versions.
* Which truth source the scoring of outside uids uses for non-public instances (decision D05 in
  the maintainers' records; see [second-validator-readiness.md](second-validator-readiness.md)).
