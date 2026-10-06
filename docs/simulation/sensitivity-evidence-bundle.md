# Offline sensitivity evidence bundle

The sensitivity-analysis CLI accepts one bounded JSON `SensitivityAnalysisSpec` from a regular
file. It analyzes that exact byte snapshot and can create a three-file evidence bundle:

- `sensitivity-spec.json`: the unchanged source bytes;
- `report.json`: the canonical analysis report; and
- `manifest.json`: raw file hashes and semantic commitments.

Create and verify a bundle:

```bash
uv run sn87-provenonce analyze-sensitivity ./sensitivity-spec.json \
  --output-dir ./evidence/sensitivity-001
uv run sn87-provenonce verify-sensitivity-bundle ./evidence/sensitivity-001
```

A checked-in [public conformance vector](../../examples/sensitivity/README.md) demonstrates the
complete profile, specification, CLI, evidence, and reconstruction path with disclosed synthetic
inputs and exact expected commitments. Every estimator and weight in that vector is illustrative
and non-normative.

Generated JSON Schemas define the complete
[analysis result](../../protocol/v0alpha1/schemas/sensitivity-analysis-result.schema.json),
[evidence report](../../protocol/v0alpha1/schemas/sensitivity-evidence-report.schema.json), and
[evidence manifest](../../protocol/v0alpha1/schemas/sensitivity-evidence-manifest.schema.json).
The same strict models construct and parse runtime outputs; nested results are not left as
unconstrained objects.

The destination must not already exist. Its parent path is opened component-by-component without
following symbolic links, the final directory is created atomically, and each entry is opened
descriptor-relative with create-exclusive and no-follow controls before bytes are written.
Required directory-only, no-follow, and nonblocking controls are mandatory; unsupported platforms
fail closed. Input is read once through a bounded, no-follow, regular-file-only descriptor.
Verification requires exactly the three named regular files,
checks canonical report and manifest bytes, verifies raw hashes, and reconstructs the complete
report from the preserved source bytes. Symbolic links, non-regular files, changed bytes,
unexpected entries, commitment drift, and reconstruction differences fail closed.
The writer verifies through the still-open directory descriptor, binds the returned result to
the exact source and report bytes already in memory, and confirms that the destination path still
names that directory inode before returning.
Reports exceeding 16,777,216 bytes are rejected by the analysis entry point before any output
directory is created.

Compatibility vectors pin the exact source, report, and manifest hashes. Filesystem hardening does
not change established bundle bytes or commitments.

Verification establishes a stable point-in-time snapshot. It does not claim that the directory
cannot be modified after verification returns.

The source byte hash and normalized specification commitment name different properties. The
first identifies the exact file snapshot, including whitespace and member order. The second
identifies the validated canonical specification. Neither proves authorship, provenance, miner
identity, or origin.

## Boundary

The report claim state is
`IMPLEMENTED_TESTED_TRANSPARENT_SENSITIVITY_EVIDENCE_ONLY`. It does not select a production
estimator or policy and does not define a winner, ranking, weights, G1 acceptance, hidden truth,
network, wallet, chain action, testnet behavior, or production evidence.
