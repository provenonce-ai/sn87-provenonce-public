# Reference miner boundary

`ReferenceMiner` is the transport-neutral response-emission boundary for an SN87 miner.
It accepts any miner-owned analysis engine that returns a strict `AssuranceResponse`. Model,
rules, retrieval, specialization, and execution strategy remain the miner's competitive work;
the core repository does not prescribe them.

Before a response can leave the boundary, `ReferenceMiner` rejects foreign return types and
revalidates the complete serialized response through the strict protocol model. This prevents
unchecked construction from bypassing the three whitepaper response-state shapes. It then
enforces the two request-relative invariants:

- response protocol version equals request protocol version; and
- response challenge identifier equals request challenge identifier.

Violations use stable codes and cannot be emitted as valid Differentials. Analyzer exceptions
propagate to the owning runtime. They are never silently converted into
`INSUFFICIENT_EVIDENCE_ABSTAIN`: the whitepaper defines abstention as a deliberate response to
insufficient Evidence, not a disguise for an operational failure.

This boundary has no HTTP server, model, wallet, network, benchmark truth, scorer, weight
planner, or chain capability. The local conformance suite exercises all three response states,
both substitution attacks, and the error-versus-abstention distinction.
