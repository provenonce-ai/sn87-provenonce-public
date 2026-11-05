# Propose a challenge

<!-- guide: no-steps -->

**Status.** Testnet 582 only, alpha ([LIMITATIONS.md](../../LIMITATIONS.md)). This page and the
check it describes change no weight, no scoring profile, no class binding and no miner
admission. A proposal is always `PROPOSED`; passing the check does not activate anything.

## What a proposal is for

A proposal describes a new challenge in terms the system can evaluate: who will use the result,
who may see which evidence, where the truth comes from, what a submission looks like, how it is
scored, what it must beat, and what it may cost. The oracle classes decide admissibility. A task
is not admissible because someone proposes it, nor because it sounds cheap to score.

## Oracle classes as this repository uses them

The whitepaper is not distributed here ([docs/whitepaper/README.md](../whitepaper/README.md)),
so these are the readings the code and ADRs support. The classes are `OracleClass` A to D in
`src/sn87_provenonce/protocol/v0alpha1/models.py`.

| Class | Truth comes from | Self-verifying |
|---|---|---|
| A | Fixed when the instance is built, such as a planted defect list ([ADR-0021](../architecture/ADR-0021-published-truth-for-public-fixtures.md)) | Yes (decision pending) |
| B | A public source; the repository does not define it further | Yes (decision pending) |
| C | Comparison with a reference execution, at least two independent ones ([ADR-0007](../architecture/ADR-0007-independent-type-c-reference-executions.md)) | No |
| D | A recorded adjudication; it must carry measured reliability | Never |

Expert-adjudicated truth (D) is a judgement with a measured agreement rate. A proposal must not
describe it as a self-verifying result, and the check rejects one that does. The boolean
`claims_self_verifying` is the real gate. The text scan that also looks for self-verification
wording in every free-text field (after Unicode normalisation) is best effort: it can be evaded
by wording it does not know, and it can fire on a sentence that denies the claim.

A Type D proposal is never `ADMISSIBLE` from this check. The reliability block (`method`,
`sample_size`, an `agreement` statistic named `COHEN_KAPPA`, `FLEISS_KAPPA`,
`KRIPPENDORFF_ALPHA` or `PERCENT_AGREEMENT`, and its value) must be present, and then a person
reviews the measured reliability (`TYPE_D_RELIABILITY_REVIEW`). The check applies no threshold.

## What `ADMISSIBLE` means

`ADMISSIBLE` means that no rule in this check fired. It never means that headroom is shown, that
the truth is right, or that the challenge will be taken up. The evidence-rights check is
structural: it reads flags and looks for the word "raw" in the rights text, and it cannot tell
what the evidence actually contains. For families the repository itself records as
`NULL_NO_HEADROOM` (`LIMITATIONS.md` item 8: `IC-APPROVAL-APPLICABILITY`, `TYPE-C-RELEASE`) the
verdict is always `NEEDS_DECISION`, whatever the proposal says about its own history.

## Fields

`proposal_id`, `proposal_version`, `challenge_family`, `intended_consumer`, `evidence_rights`
(`visibility`, `raw_evidence_leaves_source`, `export_default`, `export_justification`),
`truth_source` (`oracle_class`, `description`, `claims_self_verifying`, and for D a
`reliability` block with `method`, `sample_size` and an `agreement` statistic), `submission_format`,
`scoring`, `baselines`, `resource_budget`, `headroom` and `known_limitations`.

`scoring.reference` is either the id of a pinned profile (with its commitment, as in
`src/sn87_provenonce/profile.py`) or `PROPOSED_UNPINNED`. An unpinned rule is never activated.

## Run the check

```text
uv run sn87-provenonce challenge check examples/challenge-proposals/TEMPLATE.json
uv run sn87-provenonce challenge check examples/challenge-proposals/ic-approval-applicability.example.json
```

Add `--json` for machine output. Exit codes: 0 `ADMISSIBLE`, 3 `NEEDS_DECISION`,
1 `INADMISSIBLE` (including a file that does not match the schema), 4 file unreadable (missing, or not UTF-8).

## Verdicts and reason codes

| Code | Verdict | Meaning |
|---|---|---|
| `SCHEMA_INVALID` | INADMISSIBLE | Not valid JSON, nested too deeply, or does not match the schema. Types are strict (a number given as a string is rejected), numbers must be finite, ids carry no surrounding whitespace, `schema_version` is required and `baseline_id` values are unique. |
| `TYPE_D_RELIABILITY_MISSING` | INADMISSIBLE | Type D with no reliability block. |
| `TYPE_D_RELIABILITY_REVIEW` | NEEDS_DECISION | Type D with a reliability block; a person must review it. |
| `SELF_VERIFYING_CLAIM_ON_TYPE_D` | INADMISSIBLE | Type D described as self-verifying. |
| `SELF_VERIFYING_CLAIM_ON_NON_SELF_VERIFYING_CLASS` | INADMISSIBLE | Type C described as self-verifying. |
| `BASELINE_MISSING` | INADMISSIBLE | No baseline. A required input is absent, and without one headroom and a null result cannot be reported (LIMITATIONS.md item 8). |
| `SCORING_PROFILE_UNKNOWN`, `SCORING_COMMITMENT_MISMATCH` | INADMISSIBLE | Not a pinned profile, or the commitment is wrong. |
| `EVIDENCE_RIGHTS_INCONSISTENT` | INADMISSIBLE | `raw_evidence_leaves_source` disagrees with `export_default`. |
| `RAW_EXPORT_BY_DEFAULT` | INADMISSIBLE | Raw source records leave the source by default with no justification. |
| `RAW_EXPORT_JUSTIFIED` | NEEDS_DECISION | The same, with a justification someone must judge. |
| `SCORING_UNPINNED` | NEEDS_DECISION | Scoring is `PROPOSED_UNPINNED`. |
| `SCORING_PROFILE_FAMILY_MISMATCH` | NEEDS_DECISION | The pinned profile belongs to another family. |
| `BASELINE_NOT_PUBLIC_CONTRACT`, `BASELINE_NOT_IMPLEMENTED` | NEEDS_DECISION | No matched public-contract baseline, or none has been run. |
| `PRIOR_NULL_NO_HEADROOM` | NEEDS_DECISION | The proposal itself declares earlier null results. |
| `PRIOR_NULL_NO_HEADROOM_RECORDED` | NEEDS_DECISION | The repository records a null result for the family. |
| `EVIDENCE_TEXT_MENTIONS_RAW` | NEEDS_DECISION | The rights text mentions raw evidence although the flags say it stays at the source. |
| `TYPE_C_NEEDS_INDEPENDENT_EXECUTIONS`, `TYPE_C_EXECUTOR_NOT_DECLARED_PRIVATE` | NEEDS_DECISION | Type C without two independent executions, or an executor not declared private. |

The worst verdict among the reasons is the verdict.

## Worked example

`examples/challenge-proposals/ic-approval-applicability.example.json` describes the existing
family `IC-APPROVAL-APPLICABILITY` honestly: Type C truth from two reference executions that
Provenonce controls, scored under the pinned `IC-FIRST-LIGHT-MIN-2`, against the implemented
baseline. It lists the earlier `NULL_NO_HEADROOM` result as a prior null and the check returns
`NEEDS_DECISION` (`PRIOR_NULL_NO_HEADROOM_RECORDED`), because a null result is a matter for a person, not for a rule. It is a
description of an existing family, not a new admission.
