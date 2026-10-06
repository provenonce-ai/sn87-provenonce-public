# Evidence bundle `sn87-evidence-bundle/0.3`

One dry run produces one bundle (`bundle.py`). Docs and views cite it; nothing else is a data
source except labelled FIXTURE samples. Canonical `gra/0.1` JSON; numbers per
[wire-rules.md](wire-rules.md).

## Mode label

`mode` declares what the bundle is, before anything else is read:

| Mode | Meaning |
|---|---|
| `FIXTURE` | Public synthetic fixture produced locally. |
| `REPLAY` | Re-evaluation of a sealed past run (`source.kind: SEALED_RUN_REPLAY`). |
| `LIVE` | Produced against a live target with verified provenance. Never relabel a fallback as LIVE. |

`claim` is `CONFORMANCE_ONLY`: no method-competition claim.

## Sections

- `manifest`: `run_id`, `class_id`, `profile_id`, `profile_commitment`, `profile_applied`,
  `profile_commitment_domain`, `profile_document` (0.3, see below),
  `canonicalizer_id`, `window`, `source` (`kind`, `digest`), `common_control: true`. A source-configuration
  execution adds, under `source` only and without a schema bump: `config_id`, `permission_id`,
  `permission_digest`, `meaning_version`, `mapping_version`, `source_schema_id`,
  `execution_index`, `export_id`, `disclosure_digest`. Bundles without a source
  configuration carry none of them.
- `methods`: each with `role`. `reference`: a Provenonce reference algorithm that also
  computes truth (`state_machine`, `relational`). `candidate`: proven to see only the public
  contract (`miners/`). Used only on the source-execution path, where `approval_witness` is bound
  beside the references; the fixture bundles and the First Light row do not include it, and its
  `uid` is null until assigned. `baseline`: the matched public-contract baseline, `uid` null, never in
  the row.
- `baseline`: `{"state": "CONFIGURED", "method_id": "public_contract_baseline", "definition",
  "public_contract_only": true}`. Scores, cost and diagnostics cover it like any method.
- `comparison`: per non-baseline method, `estimate_delta` (method minus baseline, wire string or
  `NA`) and `result` (`NULL_NO_HEADROOM`, `ABOVE_BASELINE`, `BELOW_BASELINE`, `NA`). Headroom is
  reported, never a gate (0085 D3); a null result is displayed, never hidden.
- `scores[method]`: `admitted`, `evaluable`, `estimate`, `eligible`, `reason`
  (`SAMPLE_FLOOR`, `RAW_FAILURE_CEILING`, `EMPTY_ASSIGNMENT` or null),
  `lower`, `upper`, `raw_invalid_or_missing_rate`, `dimensions` (each `{value, n}`: detection,
  evidence, calibration, utility `NA`, robustness `NA`).
- `inactive`: Eq. 2, 8, 10 `"NA"`. Eq. 11 is in `efficiency` instead: status `INACTIVE_ZERO_COEFFICIENTS`, eta `"1"`.
- `diagnostics[method]`: assigned, correct abstentions, contest weight.
- `row`: `state` (`VALID_PREFERENCE_ROW` or `NO_VALID_PREFERENCE_ROW`), `weights`, `z`, over
  the non-baseline methods only.
- `chain_dry_run`: null or the output of the chain-target dry run (`weights_dry_run.dry_run`:
  `TARGET_CONFORMED_DRY_RUN`, `u16_weights`, `input_sha256`, `broadcast: false`). Never a broadcast.
- `cost[method]`: wall time, CPU time, bytes in/out, model tokens, oracle time, each
  `{value, unit, source, missing}`. Recorded beside scores, never inside them.
- `status_matrix`: four columns (implemented, enabled, tested, deployed); `tested` is a pytest node
  id or `NOT_TESTED`. Rendered in [implementation-status.md](implementation-status.md).
- `cases` (optional; `FIXTURE` only, see below): one record per assigned case, in assignment order.

## Per-case records (`cases`, FIXTURE only)

A `FIXTURE` bundle carries `cases`, so a reader can recompute Eq. 3-7, 12 and 13 from per-case
values instead of trusting the per-method aggregates. Each record is `{qid, track, family,
methods}`: `track` is `scored` or `diagnostic`; `family` is the generator family named in the
committed profile's public `assignment`/`diagnostics` (`NA` if the caller supplied none).
`methods[method]` holds `valid`, `failures`, `state` (the response state, `NA` if invalid),
`dimensions` (all five; `NA` when inactive, not applicable or invalid), `precision`, `recall`
(`NA` when undefined), `fp_cost` and `score`. All numbers are wire strings. There is no truth,
no capsule, no evidence reference and no cost here: cost stays in `cost[method]`.

Recompute: `scores[m].dimensions[k]` is the mean of `float(dimensions[k])` over scored-track
records that are `valid` and not `NA` (`n` is their count); `scores[m].estimate` is Eq. 13 over
every scored-track `score`, invalid ones counted as 0. `tests/test_bundle.py` checks both
equalities exactly, as wire strings.

Why FIXTURE only, and only with established provenance: `cases` is opt-in (`evaluate(...,
per_case=True)`) and raises for REPLAY/LIVE. FIXTURE mode alone is not a disclosure gate. The
public synthetic generator (`fixture_run`) opts in; a source execution opts in only when both the
source schema and its permission declare it FICTIONAL (`sources.mapping.is_fictional`), so a real
source mapped through the same path never publishes per-case outcomes. The private bundle writer
also refuses to write a non-FIXTURE bundle that has `cases`. Publishing per-case data from a
sealed run (First Light included) is a decision for Provenonce, not a code default.

## Carried profile (0.3)

`manifest.profile_document` is the committed scoring-profile document and
`manifest.profile_commitment_domain` its commitment domain. The binding is
`sha256(domain || 0x00 || uint32_be(len) || canonical_json(document))` (the `object_commitment`
rule, `canonical.py`) and must equal `manifest.profile_commitment`. A reader takes the Eq. 13-15
values it needs (`minimum_assignments`, `maximum_raw_invalid_or_missing_rate`, `tail_fraction`,
`theta`, `gamma`) from the document only after that equality holds. If the fields are absent
(0.1, 0.2) or the hash differs, the reader must report the values as unavailable and show no number
derived from them (fail closed); it must not fall back to a copied constant. The document is
identical to `src/sn87_provenonce/profiles/<profile_id>.json`; no profile or scoring value changes.

Schema version: `sn87-evidence-bundle/0.3`. 0.3 adds only `manifest.profile_commitment_domain` and
`manifest.profile_document`; a bundle's version is exactly one of 0.1, 0.2, 0.3 and readers reject any
other. Everything below on 0.2 still holds. The First Light row and its recorded section are
unchanged by the move to 0.3.

History: `sn87-evidence-bundle/0.2` added only the optional, FIXTURE-only `cases`
section; every 0.1 field is unchanged, so 0.1 readers that ignore unknown keys still work. A
reader that checks the version must check it exactly. A reader that needs per-case data tests for
`cases` and falls back to "not recomputable from this bundle" when it is absent.

## Replay trust boundary

Replay verifies the seal: the private cases against the manifest's capsule and salted answer
commitments, then the rescore against the sealed report row. `responses.json` and `report.json`
are written after the seal, so no seal commitment covers them. Replay binds both into the source
digest and requires the rescore to equal the sealed report row; it does not prove who produced
the responses. That authenticity rests on the signed transport receipts, checked by Provenonce's private
run-verification tooling and not by replay. The bundle therefore carries
`RECEIPT_SIGNATURES_NOT_CHECKED_HERE` in `manifest.source.verification`. Replay does not verify
receipts.

## Golden row (First Light)

Run `e6ffa76e6f8a14bc0625fc2caf92e2cc`, profile `IC-FIRST-LIGHT-MIN-1`, commitment
`sha256:7049f165bc9b4fae32133f2d37aa9a48f5bf13f3b4fa47ea94643e5633d3c766`. Estimates 1 and 1
(12 admitted each), weights 0.5/0.5, `z` `0.16000000000000003` each. Dry run: uids [1,2], u16
[65535,65535], input sha256 `7f376609ca79fecea61d787f34ac0fcea0c273212fce730ae65c843099eeb650`.
Applied on public testnet netuid 582 at block 8,102,381. Conformance evidence only.
