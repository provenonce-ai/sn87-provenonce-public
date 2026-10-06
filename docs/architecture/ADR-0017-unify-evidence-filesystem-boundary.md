# ADR-0017: Unify the evidence filesystem boundary

- Status: Accepted
- Date: 2026-09-04
- Decider: Will O'Brien, Provenonce

## Context

SN87 has one reusable two-file evidence bundle and two source-preserving three-file bundles. The
three shapes make different semantic claims, but every writer and verifier depends on the same
filesystem invariants: an anchored directory identity, bounded regular files, exclusive creation,
stable opening and closing snapshots, exact membership, and caller-safe failures.

The two-file primitive already opened directory paths component-by-component without following
symbolic links and failed closed when required platform controls were unavailable. The two
source-preserving implementations independently enforced final-directory and entry controls, but
their parent-directory traversal and platform checks were older and weaker. Keeping separate
low-level implementations would allow the same integrity contract to drift again.

## Decision

Use one internal evidence-filesystem layer for all bundle shapes. The layer owns:

- componentwise, no-follow directory traversal and parent creation;
- create-exclusive final directories and entries relative to retained descriptors;
- required directory-only, no-follow, and nonblocking platform controls;
- bounded reads, regular-file and single-link checks, stable metadata projections, and
  best-effort descriptor closure; and
- normalization of low-level path, descriptor, and filesystem failures into the public error
  type supplied by each caller.

Each semantic bundle retains its own expected file set, byte ceilings, models, reconstruction,
manifest, commitments, verification result, and public error class. Local adapters remain at the
bundle modules so adversarial tests can intervene at the same lifecycle boundaries.

The source readers use the same required file controls, bounded read, and descriptor metadata
checks. A source hash continues to establish only the exact bytes read; it does not establish
authorship, origin, or custody.

Existing writer-produced bytes are a compatibility contract for this change. Regression vectors
pin every source, report, and manifest hash for the disclosed sensitivity vector and reference
Type-C candidate. The implementation changes filesystem handling only.

## Options considered

### Maintain three low-level implementations

This minimizes the immediate diff but preserves the mechanism that allowed integrity guarantees
to diverge.

### Replace the three-file formats with the reusable two-file bundle

This would reduce implementation count but discard the exact source snapshot that those bundles
are designed to preserve and would change public bytes and commitments.

### Share the filesystem boundary while retaining semantic bundle formats

This applies one security contract to every bundle without collapsing their claims or changing
their files, schemas, reports, manifests, commitments, or CLI surfaces. This option was selected.

## Consequences

- Intermediate parent symbolic links and parent-substitution races fail closed for every bundle.
- Required platform controls are mandatory rather than silently replaced with zero-valued flags.
- Descriptor metadata and invalid-path failures remain within each caller's public error boundary.
- The shared implementation is smaller than the three implementations it replaces and can be
  hardened once for all bundle shapes.
- Existing deterministic bundle bytes and commitments remain unchanged.
- A failed create-only operation can leave an incomplete destination; a retry must use a fresh
  path rather than overwrite evidence.
- The change does not define scoring, coefficients, calibration thresholds, ranking, miner
  weights, G1 acceptance, hidden truth, networking, wallets, chain actions, testnet behavior, or
  publication.
