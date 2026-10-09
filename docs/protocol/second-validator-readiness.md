# Second-validator readiness

**Status.** A checklist of what a second validator needs from this repository, with a script that
evaluates the items it can. Alpha, testnet only ([LIMITATIONS.md](../../LIMITATIONS.md)). Nothing
here registers, funds or sets weights.

Run the mechanical items:

```bash
uv run python scripts/second_validator_check.py          # table of every item
uv run python scripts/second_validator_check.py --json   # the same, machine readable
```

The script prints one status per item. `READY`: the check passed. For items whose evidence says
"files present", that means the files exist; the script does not run their tests. `NOT_READY`: the
check failed or the thing does not exist. `NEEDS_DECISION`: it waits for a decision of the
maintainers; this repository does not make that decision. `--root` runs the checks in a child process inside
that tree, with its `src` first on the module path, so imports come from that tree. This executes code from that tree: only point `--root` at a tree
you already trust. The statuses below are for the public tree. A few depend on the tree or the
machine (marked in the notes), so the script is the authority for the tree you hold.

| Item | Status | What it means |
|---|---|---|
| `INPUT_PUBLIC_FIXTURES` | READY | The public fixture generator and its contract are present |
| `INPUT_CMT_VERIFIES` | READY | The task manifest compiles and its commitment verifies |
| `SCORING_PUBLIC_SCORER_AND_PROFILE` | READY | The scorer loads and the bound profile commitment recomputes |
| `SCORING_TRUTH_PUBLIC_FIXTURES` | READY | Truth for the public fixtures is published and parses |
| `SCORING_TRUTH_HIDDEN_INSTANCES` | NEEDS_DECISION | Truth for hidden instances comes from executors that are not published; who holds it is the truth-custody decision (D05) |
| `CLIENT_SIGNED_EXCHANGE` | READY | The signed request and verified response client imports |
| `CLIENT_REPLAY_STORE_AVAILABLE` | machine | READY where a Valkey-compatible server binary is installed. The client needs one with `noeviction`; the script does not check that |
| `CLIENT_ENDPOINT_DISCOVERY_SPEC` | tree | READY only in a tree that contains the miner announcement specification; it is not in every tree yet |
| `CLIENT_ENDPOINT_DISCOVERY_READER` | NOT_READY | A validator-side reader that applies the discovery rule is not in the public tree |
| `WEIGHTS_QUANTIZER` | READY | The u16 quantizer imports and the SDK is the pinned version |
| `WEIGHTS_COMMIT_REVEAL_PATH_AND_TESTS` | READY | The commit-reveal payload, schedule and state code, a fake chain and tests are present |
| `WEIGHTS_REAL_SUBMITTER` | NOT_READY | No code in this repository sends a commit or reads the chain for commit-reveal; the submitter is an interface |
| `WEIGHTS_PLAIN_PATH_OPERATOR_TOOLING` | tree | READY only where the operator tooling is present; it is not in the public tree, so NOT_READY there |
| `WEIGHTS_COMMIT_REVEAL_ENABLED_ON_TESTNET` | NEEDS_DECISION | A chain parameter of the subnet owner; not read or set here |
| `ADMISSION_PLAN_VERSION_TOOL` | READY | Plan versions, stages and the criteria checker are present ([admission.md](admission.md)) |
| `ADMISSION_CRITERIA_VALUES` | NEEDS_DECISION | The values are proposals until an approval record cites their digest |
| `VERIFIER_ATTESTATION_INTEGRITY` | READY | The public verifier recomputes the attestation digests offline |
| `VERIFIER_PLAN_DIGEST_RECOMPUTE` | tree | READY only where the private plan tool and reference executors are present; NOT_READY in the public tree |
| `TRUTH_CUSTODY_D05` | NEEDS_DECISION | Open: who holds truth for hidden instances in the contest phase |

## What a second validator needs, by area

**Inputs.** The capsules for a window come from the generator the task manifest names. For public
fixtures the generator and the published truth are in the tree. A window of hidden instances is not
reproducible from the tree.

**Scoring.** The scorer, the committed profiles and the bundle are public. The truth that scoring
compares against for hidden instances is computed by reference executors that are not published
(they would be a perfect miner for hidden instances). A second validator can score public fixtures
and verify the first validator's published digests for them. It cannot recompute hidden-instance
truth until the custody decision is made.

**Signed client.** The client signs requests, verifies the responder's identity and binds the
response to the request. It needs a replay store as described in the validator quickstart. How a
validator finds an outside miner's endpoint is specified separately and is not in every tree yet;
a reader that applies the rule is not part of the public tree.

**Weights path.** The quantizer is public and shared by the plain and the commit-reveal paths; a
test shows both give the same row. Commit-reveal is implemented as payload preparation, schedule
and persisted state against a submitter interface, tested with a fake chain. The pinned SDK
submits weights for a commit-reveal subnet as a timelocked commit that the chain reveals; the
payload comes from the SDK's own function and a test compares the arguments with the SDK's weight
intent. No real submitter is provided, so commit-reveal has not run on any chain. The plain
weights path still refuses a commit-reveal target.

**Truth custody.** Not decided here. The options and their costs belong to the maintainers'
decision record; this repository only lists it as open.

## Status matrix

The status matrix row "Commit-reveal submission" still reads not implemented, not enabled, not
tested and not deployed. The matrix is part of the evidence bundle, and its digests are committed,
so changing the row changes digest-bound content. It is left as it is, and updating it is an open
item for the change that regenerates those records.
