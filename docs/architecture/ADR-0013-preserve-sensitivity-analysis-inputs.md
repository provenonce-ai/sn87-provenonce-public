# ADR-0013: Preserve exact sensitivity-analysis inputs

- Status: Accepted
- Date: 2026-09-04

## Context

The transparent sensitivity layer is deterministic, but an in-memory result alone does not
prove which external file bytes were analyzed. Normalized semantic identity also cannot preserve
differences in ordinary JSON whitespace or member order. A useful offline demonstration needs
both identities without overstating either as provenance.

## Decision

Provide a bounded CLI entry point and a dedicated create-only evidence bundle containing the
exact source specification, canonical report, and canonical manifest. Bind the source by raw
SHA-256, the validated specification and analysis by their domain-separated commitments, and
the report by its own domain-separated commitment.

Verification reconstructs the complete report from the preserved source bytes and requires an
exact regular-file set. Input and bundle reads do not follow symbolic links. The final directory
is created atomically; entries use descriptor-relative, create-exclusive, no-follow writes.
Output byte sizes are enforced before directory creation, and the bundle destination must not
already exist.

Creation verification runs through the still-open destination directory descriptor. Before
returning, the writer binds the result to the in-memory source and report identities and confirms
that the published path names the same device and inode as the verified descriptor.
Verification establishes a stable point-in-time snapshot; it does not claim that the directory
cannot be modified after verification returns.

## Consequences

- A sensitivity result can be reproduced from its exact disclosed input snapshot.
- Raw-byte identity remains distinct from normalized semantic identity.
- Evidence creation cannot overwrite an existing destination.
- The bundle proves neither source authorship nor origin.
- Estimator selection, production scoring, ranking, weights, G1, hidden truth, network, wallet,
  chain, testnet, and production evidence remain outside this capability.
