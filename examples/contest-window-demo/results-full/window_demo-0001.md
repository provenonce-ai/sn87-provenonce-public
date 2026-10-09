# Contest window demo-0001: results

Shadow results. Testnet weights are unchanged; nothing here sets a weight.

- Window: 2026-10-20T00:00:00Z to 2026-10-21T00:00:00Z
- Status: VALID (admitted scored cases 24 of 24 assigned, minimum 22, reference failures 0, tolerated 2)
- Scoring profile: IC-FIRST-LIGHT-MIN-3 (`sha256:039b8639a839f8617003c2f5e686dcf313dd7fc80f9de2c1b8d7d9762a6e7665`)
- Cases commitment: `sha256:14a349f9d4e06d39e48a01f7fda5201e3eaa789bab17ec2f52ae63d52645e71c`
- Truth commitment: `sha256:59ef699f9b25e4c86fdf6d92a8009a153c18351d761fa1ef4f506929c80a6105`
- Seed: revealed and verified against the committed seed commitment `sha256:832db2851e085a20453df081cf957814c35adfc2bd6972565a388e18e16180f9`
- Equal evidence: every method answered the same 32 capsules; baseline recomputed from public code: True; integrity: ASSERTED_FIXTURE

Truth states in the window (admitted cases): FINDINGS 10, NO_MATERIAL_DEVIATION 6, INSUFFICIENT_EVIDENCE_ABSTAIN 16

## Scores and agreement with truth

| Method | uid | Role | Epoch estimate | Eligible | Agreement (scored) | Agreement (all) | Invalid or missing | Estimate vs baseline |
|---|---|---|---|---|---|---|---|---|
| approval_witness | - | candidate | 0.8333 | yes | 24/24 (1.000) | 32/32 (1.000) | 0 | ABOVE_BASELINE |
| public_contract_baseline | - | baseline | 0.6717 | yes | 18/24 (0.750) | 22/32 (0.688) | 0 | NA |

## approval_witness

Role candidate. Exact agreement (state and finding codes): 32/32. Diagnostic cases: 8 (never an epoch input).

Confusion table, rows are the recomputed truth state, columns the response:

| Truth \ response | FINDINGS | NO_MATERIAL_DEVIATION | INSUFFICIENT_EVIDENCE_ABSTAIN | NO_VALID_RESPONSE |
|---|---|---|---|---|
| FINDINGS | 10 | 0 | 0 | 0 |
| NO_MATERIAL_DEVIATION | 0 | 6 | 0 | 0 |
| INSUFFICIENT_EVIDENCE_ABSTAIN | 0 | 0 | 16 | 0 |

| Family | Cases | State agreement | Mean score |
|---|---|---|---|
| fresh_review | 6 | 6/6 | 1.0000 |
| incomplete | 6 | 6/6 | 0.5000 |
| stale_authority | 10 | 10/10 | 1.0000 |
| wrong_scope_clear | 5 | 5/5 | 0.5000 |
| wrong_scope_stale | 5 | 5/5 | 0.5000 |

Validity and integrity failures: none.

| Cost | Value | Unit | Source or reason |
|---|---|---|---|
| wall_time | NA | ms | NOT_REPORTED |
| cpu_time | NA | ms | NOT_REPORTED |
| bytes_in | 198576.0 | bytes | canonical_capsule_bytes |
| bytes_out | 15380.0 | bytes | canonical_response_bytes |
| model_tokens | NA | tokens | NOT_REPORTED |
| oracle_time | NA | ms | NOT_REPORTED |

## public_contract_baseline

Role baseline. Exact agreement (state and finding codes): 22/32. Diagnostic cases: 8 (never an epoch input).

Confusion table, rows are the recomputed truth state, columns the response:

| Truth \ response | FINDINGS | NO_MATERIAL_DEVIATION | INSUFFICIENT_EVIDENCE_ABSTAIN | NO_VALID_RESPONSE |
|---|---|---|---|---|
| FINDINGS | 10 | 0 | 0 | 0 |
| NO_MATERIAL_DEVIATION | 0 | 6 | 0 | 0 |
| INSUFFICIENT_EVIDENCE_ABSTAIN | 5 | 5 | 6 | 0 |

| Family | Cases | State agreement | Mean score |
|---|---|---|---|
| fresh_review | 6 | 6/6 | 1.0000 |
| incomplete | 6 | 6/6 | 0.5000 |
| stale_authority | 10 | 10/10 | 0.9122 |
| wrong_scope_clear | 5 | 0/5 | 0.0000 |
| wrong_scope_stale | 5 | 0/5 | 0.0000 |

Validity and integrity failures: none.

| Cost | Value | Unit | Source or reason |
|---|---|---|---|
| wall_time | NA | ms | NOT_REPORTED |
| cpu_time | NA | ms | NOT_REPORTED |
| bytes_in | 198576.0 | bytes | canonical_capsule_bytes |
| bytes_out | 18595.0 | bytes | canonical_response_bytes |
| model_tokens | NA | tokens | NOT_REPORTED |
| oracle_time | NA | ms | NOT_REPORTED |
