# ADR-0001: Separate protocol, hidden truth, and production operations

**Status:** Accepted
**Date:** 2026-09-03
**Decider:** Will O'Brien, Provenonce Founder & CEO

## Context

SN87 needs an open protocol and contest surface, renewable hidden challenge truth, and private production operations. These assets have different audiences, exposure risks, and release lifecycles. Combining them would either compromise future publication, leak benchmark truth, or expose production controls.

## Decision

Use three repositories with one stable `sn87-provenonce` identity stem:

1. `sn87-provenonce` owns public-intended protocol contracts, reference code, public-safe benchmarks, conformance tests, and documentation.
2. `sn87-provenonce-benchmark-foundry` owns permanently private challenge generation, rotation, adjudication, and leakage controls. Protected corpora and answer keys remain outside Git.
3. `sn87-provenonce-operations` owns permanently private infrastructure, deployment, observability, recovery, and chain-configuration evidence. Secrets remain outside Git.

The protocol repository uses a public-clean history from its first commit. The other two repositories never become public.

## Options considered

- One repository: rejected because its histories cannot satisfy all three trust boundaries.
- Protocol plus operations: rejected because hidden truth and operator access are not the same role.
- Many component repositories: deferred because independent schema, SDK, miner, validator, and documentation release trains would create compatibility drift before the protocol is stable.

## Consequences

- Shared schemas and reference semantics version together.
- Hidden instances and production controls cannot leak through a future protocol publication.
- Cross-repository interfaces must be explicit and versioned.
- New repositories require a durable responsibility boundary, not a temporary phase or audience label.
