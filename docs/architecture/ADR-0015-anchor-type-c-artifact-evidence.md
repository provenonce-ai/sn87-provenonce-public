# ADR-0015: Anchor offline Type-C artifact evidence

- Status: Accepted
- Date: 2026-09-04
- Decider: Will O'Brien, Provenonce

## Context

The offline Type-C candidate boundary preserves an exact candidate artifact, canonical report,
and manifest. The original evidence writer used create-only path operations, and the verifier
rejected symbolic links and unexpected entries. Those controls did not keep one directory
identity anchored throughout creation and verification. A concurrent path or entry substitution
could therefore make individual checks observe different filesystem objects.

The evidence claim is limited to one stable point-in-time local snapshot. The implementation
must support that claim without implying custody, authorship, candidate identity, or immutability
after verification returns.

## Decision

Create the final bundle directory atomically relative to an open parent descriptor. Create every
entry relative to the still-open bundle descriptor with create-exclusive and no-follow flags.
Synchronize written files and the directory before verification.

Open all verification entries relative to the anchored directory descriptor. Require regular
files with one link, enforce byte ceilings before reading, retain every entry descriptor through
reconstruction, and compare initial bytes and metadata with a second complete read. Recheck the
named entries, exact membership, and directory metadata before returning. Both the writer and
public verifier confirm that the published path still names the verified directory device and
inode.

Expose a dedicated `CandidateArtifactEvidenceError`, which remains a `ValueError` subtype, for
caller-safe evidence failures.

## Options considered

### Retain path-based creation and verification

This preserves the smaller implementation but cannot establish that all checks apply to one
directory and file set under concurrent substitution.

### Write to a temporary directory and rename

This improves publication atomicity but does not by itself prevent entry races or prove that the
post-rename path still identifies the verified directory.

### Anchor creation and verification to descriptors

This adds explicit filesystem code and adversarial tests while binding reads, writes, and closing
checks to the same kernel objects. This option was selected.

## Consequences

- Raced symbolic-link entries cannot redirect writer output.
- Directory replacement, membership injection, hard links, and entry mutation fail closed.
- Verification describes a stable point-in-time snapshot, not future filesystem immutability.
- Candidate identity, origin, natural-language quality, calibration, scoring, ranking, weights,
  G1 acceptance, networking, wallets, chain actions, and testnet behavior remain outside scope.
