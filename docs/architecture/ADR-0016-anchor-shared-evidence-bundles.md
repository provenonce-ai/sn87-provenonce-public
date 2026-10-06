# ADR-0016: Anchor reusable two-file evidence bundles

- Status: Accepted
- Date: 2026-09-04
- Decider: Will O'Brien, Provenonce

## Context

Four public-safe execution surfaces use the same two-file evidence shape: the transparent Lane
One simulation, local validator runtime, transparent Type-C reference, and transparent Type-C
candidate conformance. Each bundle contains `report.json` and `manifest.json`.

The shared implementation was create-only and rejected links during ordinary verification, but
its checks reopened pathnames independently and did not enforce byte ceilings. A concurrent
entry or directory substitution could therefore make one result depend on different filesystem
objects, and an unbounded input could consume excessive memory.

The supported claim is a stable point-in-time local snapshot. It is not a claim of custody,
authorship, origin, or immutability after verification returns.

## Decision

Keep one reusable two-file evidence primitive. Build canonical report and manifest bytes and
enforce configured positive byte ceilings before creating the destination. Create the final
directory atomically relative to a parent path opened component-by-component without following
symbolic links, then create each entry relative to the retained directory descriptor with
create-exclusive and no-follow controls. Fail closed on platforms that cannot supply the required
descriptor-relative, directory-only, no-follow, and nonblocking controls.

For creation and public verification, open both expected entries relative to one anchored
directory descriptor. Require regular files with exactly one link, retain both file descriptors,
and compare complete opening and closing byte snapshots and metadata. Recheck each named entry,
exact directory membership, directory metadata, and the published path's device and inode before
returning. Require exact canonical report and manifest bytes while preserving the existing
manifest and commitment formats.

Use a dedicated `EvidenceBundleError`, retained as a `ValueError` subtype, so low-level
filesystem and canonicalization failures do not escape the evidence boundary.

The default byte ceilings are local defensive limits: 16 MiB for the report and 16 KiB for the
manifest. They are not protocol economics, benchmark thresholds, or production calibration.

## Options considered

### Retain path-based verification

This is smaller but cannot establish that all checks observed the same directory and entries.

### Implement separate controls for each consumer

This permits surface-specific behavior but duplicates a security boundary and allows its
guarantees to drift.

### Harden the shared primitive

One descriptor-anchored implementation gives all four consumers the same point-in-time snapshot
contract without changing their report, manifest, or commitment formats. This option was
selected.

## Consequences

- Raced symbolic links cannot redirect writer output.
- Hard links, directory replacement, membership injection, oversized output, and concurrent
  entry mutation fail closed.
- Existing canonical writer-produced bundles remain verifiable without byte or commitment drift.
- A failed creation can leave an incomplete create-only destination; a retry must use a fresh
  path so failure evidence is not overwritten.
- Verification establishes only the returned point-in-time snapshot.
- Scoring policy, coefficients, calibration thresholds, ranking, miner weights, hidden truth,
  G1 acceptance, networking, wallets, chain actions, testnet use, and publication remain outside
  scope.
