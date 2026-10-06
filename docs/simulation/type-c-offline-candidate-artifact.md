# Offline Type-C candidate artifacts

This boundary runs actual candidate response data against the complete disclosed Type-C corpus
without network access or test-harness expectations. It is deterministic public-safe
conformance, not scoring, miner authentication, hidden evaluation, or G1 evidence.

## Exact envelope

The JSON root contains only:

- `artifact_type`: `sn87-transparent-type-c-candidate-artifact`
- `artifact_version`: `sn87-transparent-type-c-candidate-artifact/0alpha1`
- `protocol_version`: `sn87/0alpha1`
- `conformance_version`: `type-c-candidate-conformance/0alpha1`
- `reference_oracle_version`: `type-c-transparent-reference-oracle/0alpha2`
- `reference_oracle_report_commitment`: the exact locally pinned reference-report commitment
- `candidate_id`: a nonempty local label of at most 128 characters
- `cases`: exactly one fixture ID and `AssuranceResponse` for each of the eight transparent
  fixtures

The generated JSON Schema is
`protocol/v0alpha1/schemas/type-c-candidate-artifact.schema.json`. Runtime validation additionally
enforces the exact fixture set, response challenge binding, local resource limits, and local
version constants.

## Parsing and limits

- regular files only; symbolic links, directories, and FIFOs fail closed;
- maximum source size is 262,144 bytes inclusive;
- UTF-8 only, with no byte-order mark and no invalid Unicode scalar values;
- duplicate raw keys and keys that collide after NFC normalization are rejected;
- ordinary JSON whitespace and case ordering are accepted;
- maximum JSON depth is 24, strings are at most 8,192 characters, each response may contain at
  most 32 findings, and each finding may contain at most 16 Evidence references; and
- missing, surplus, or duplicate fixture cases are rejected before evaluation.

These are ingestion-safety limits, not scoring or protocol-economic policy. JSON `1` and `1.0`
normalize to the same validated float in this draft object profile. The resulting commitment is
not the whitepaper's future normative Evidence commitment.

## Identity and reconstruction

The report distinguishes:

- `source_artifact_sha256`: plain SHA-256 of the exact source bytes;
- `normalized_artifact_commitment`: domain-separated commitment over the validated envelope in
  canonical `FIXTURES` order; and
- `candidate_commitment`: existing per-case commitment over candidate ID, fixture ID, and the
  validated response.

Evidence creation stores the exact source bytes alongside the canonical report and manifest.
The parent path is opened component-by-component without following symbolic links, the final
directory is created atomically, and every entry is created exclusively relative to the still-open
directory descriptor. Required directory-only, no-follow, and nonblocking controls are mandatory;
unsupported platforms fail closed. Verification opens all three files relative to one anchored
directory descriptor, verifies exact membership, single-link regular-file identity, stable bytes
and metadata, and byte hashes, then reparses and reruns the whole candidate evaluation from the
stored source snapshot. Both creation and public verification confirm that the published path
still names the verified directory inode before returning. Compatibility vectors pin exact source,
report, and manifest hashes so filesystem hardening cannot silently change established bytes or
commitments.

Verification establishes a stable point-in-time snapshot. It does not claim that the directory
cannot be modified after verification returns.

## Run it

```bash
uv run sn87-provenonce conform-type-c-artifact ./candidate.json
uv run sn87-provenonce conform-type-c-artifact ./candidate.json \
  --output-dir ./evidence/type-c-candidate-001
uv run sn87-provenonce verify-type-c-artifact-bundle \
  ./evidence/type-c-candidate-001
```

Invalid input creates no evidence destination. Valid bundle creation is create-only.

## Claim boundary

The report claim is
`IMPLEMENTED_TESTED_TRANSPARENT_TYPE_C_OFFLINE_ARTIFACT_CONFORMANCE_ONLY`. It does not prove the
candidate's identity or origin and does not evaluate natural-language semantics, confidence or
severity calibration, hidden truth, normative scoring, ranking, weights, G1 acceptance,
transport, wallets, networks, chains, testnet, or production readiness.
