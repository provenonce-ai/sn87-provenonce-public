# ADR-0006: Keep miner analysis strategy behind a strict emission boundary

**Status:** Accepted

**Date:** 2026-09-03

**Deciders:** Will O'Brien, Provenonce Founder & CEO; SN87 protocol maintainer

## Context

The whitepaper defines the miner's commodity as a decomposable Assurance Differential and
requires every response to declare exactly one of `FINDINGS`, `NO_MATERIAL_DEVIATION`, or
`INSUFFICIENT_EVIDENCE_ABSTAIN`. It permits miner specialization: competing miners may use
different models, rules, retrieval systems, or bounded execution methods, but all responses
face one output contract and the same hidden challenge.

The core repository therefore needs a reference miner boundary without pretending to provide
the winning analysis strategy. It must also distinguish a deliberate Evidence-based
abstention from an unavailable or broken analyzer. Converting arbitrary failures into
abstentions would corrupt abstention-quality measurements and hide operational defects.

Current subnet references reinforce the separation of concerns rather than a shared strategy:
Glyph publishes a minimal reference artifact and keeps evaluation and validator orchestration
separate, while Chutes splits miner APIs, workload management, data services, and deployment
components. Their economics and infrastructure are not SN87 protocol authorities.

Sources reviewed:

- SN87 protocol specification, Digital Commodity, Miner Specialization, Protocol
  Roles, and Formal Object Model
- [Glyph subnet reference-codec and validator separation](https://github.com/glyph-research/glyph-subnet)
- [Chutes miner component separation](https://github.com/rayonlabs/chutes-miner)

Document packaging and presentation changes do not change this protocol decision.

## Decision

Define an asynchronous `AssuranceAnalyzer` protocol owned by the miner implementation. Add a
small `ReferenceMiner` response-emission boundary that:

1. rejects foreign return types and revalidates the serialized candidate through the strict
   `AssuranceResponse` model;
2. requires response and request protocol versions to match;
3. requires response and request challenge identifiers to match;
4. emits stable contract-violation codes; and
5. allows analyzer exceptions to remain operational failures.

Do not catch an unspecified analyzer exception and convert it into
`INSUFFICIENT_EVIDENCE_ABSTAIN`. An analyzer may return that state explicitly only when it can
produce the required rationale and any bounded Evidence request under the protocol model.

Do not prescribe a model provider, prompt, rules engine, retrieval stack, or inference method
in the reference boundary. Those are miner strategies, not consensus protocol.

## Options considered

### Strict emission boundary with pluggable analyzer: selected

Preserves miner competition while providing one testable response contract and clear failure
semantics.

### Ship one canonical analysis implementation

Rejected. It would collapse miner differentiation, invite benchmark overfitting, and imply
semantic capability that has not been measured.

### Treat analyzer failure as abstention

Rejected. It would make operational instability appear epistemically responsible and would
contaminate future abstention-quality and availability metrics.

### Leave request binding solely to validators

Rejected as the only control. Validators must still reject substitutions, but a reference
miner should also refuse to emit a response it knows is bound to another protocol or
challenge.

## Consequences

- Miner implementations can innovate behind a narrow stable interface.
- Reference code cannot be mistaken for a canonical inference strategy.
- Explicit abstention remains measurable and distinct from runtime failure.
- Validator-side integrity checks remain independently required; this is defense in depth,
  not a replacement.
- Transport, rate limits, model execution, scoring, benchmark truth, and chain behavior remain
  outside this decision.
