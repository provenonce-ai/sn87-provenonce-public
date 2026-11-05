# ADR-0024: DAT-HEADROOM, an inactive candidate family built for headroom (class DELEGATED-AUTHORITY-TRACE)

**Status:** NEGATIVE: headroom not established (see "Addendum 2026-11-05"; the text above the
addendum is kept as written). Proposed as a record only. A generator, a contract, public methods, a profile document and a
preregistered test are committed. The family is INACTIVE: it is bound to no class in the registry
of bound classes, to no weight path, shadow default or criteria file, and the weight gate refuses
it.

**Date:** 2026-11-05

**Deciders:** SN87 protocol maintainers. Whether to bind this family, or to build another, is open
(see "Open decisions"); this record does not decide it.

## Context

[ADR-0022](ADR-0022-constant-bound-fixed-outcome-profile.md) ends with the headroom problem: every
committed family is solvable by public methods or cheap heuristics (simple structural heuristics), so nothing can be weighted on them, and "fresh instances are the remedy".
[ADR-0021](ADR-0021-published-truth-for-public-fixtures.md) says how a new family should fix truth
(at the moment the instance is built) so that code can be open while instances stay hidden. This
record builds one such family and runs the registered headroom test on it.

## Decision

Commit one candidate family and mark it inactive. It has five parts.

**1. The family.** Delegated-authority traces (`dat/0.1`). A trace is a log, in arrival order, of
grants (each citing a parent grant and the source that logs it), revocations, uses of a granted
capability, and events that carry no authority (queries, heartbeats, syncs, notes). Event time,
not arrival order, is authoritative. The contract fixes the rules:

- a revocation is effective only if it is later than the grant and its revoker is the grantor of
  that grant or of an ancestor; an effective revocation voids later uses through the chain;
- a chain's effective level is the lowest level on it, and a use above it escalates;
- a chain whose parent grant is absent is broken if the parent's source was observed up to that
  point, and undetermined if the source declares a gap that could hold it;
- a declared gap makes a use undetermined only if it could hide an effective revocation of a grant
  the use depends on (a gap in the source of a grantor on the chain, during the grant's life up to
  the use).

The truth states are `FINDINGS` (a violation is visible), `NO_MATERIAL_DEVIATION`, and
`INSUFFICIENT_EVIDENCE_ABSTAIN` (no visible violation and at least one use undetermined). The defect
catalogue has three codes: `REVOKED_GRANT_USE` (HIGH), `BROKEN_CHAIN_USE` (HIGH),
`SCOPE_ESCALATION` (MEDIUM). Witnesses (the required references) are defined by the contract.

**2. Truth is fixed at build (ADR-0021, Type A).** A deterministic generator builds a clean
simulated world, adds benign look-alikes, and then either plants violations (recorded as planted),
plants a blind spot (a gap that hides what a use depends on), or plants nothing. The planted record
is the truth. No private executor exists. The open semantics is run once per attempt as a check that
the planted record is what a reader of the visible capsule can establish; an attempt that fails is
discarded and counted. The generator, its random source (splitmix64 over a sha256 seed, identical on
every platform) and the contract are open; instances are hidden until their seed is revealed.

**3. Designed for headroom.** Traces vary in length (about 48 to 336 events), actors, resources,
delegation depth, event kinds and ordering. Every instance, whatever its family, carries three to
eleven decoys (a valid use whose later revocation is logged first, a revocation after the last use,
a revocation by someone without authority, a second grant after the first is revoked, an escalated
grant used within its ceiling, a query through a revoked grant) and one to three declared gaps. Each
plant has a benign analogue of equal footprint that fills its slot in the other families, so counts
of grants, uses and revocations do not tell. Evidence is priced by the profile's precision-squared
credit, so on a large trace citing everything is expensive.

**4. A profile and a binding that is not registered.** `DAT-HEADROOM-MIN-4` applies the MIN-4 rules
(ADR-0022) unchanged: the pool is 16 `planted_violation`, 16 `clean_decoys`, 8 `blind_spot`, so
every constant answer is bounded at 0.40 by the loader and a perfect method scores 0.90. The profile
is pinned in the profile registry; its class is not in the registry of bound classes.

**5. A registered test.** The preregistration (private research record) was committed before any
held-out instance existed, with the held-out seed by hash only. Methods: the matched baseline; an
analogue of the published `approval_witness` (`chain_witness`); a simple strong public method; structural
heuristics adapted to the family; 14 constant strategies. Candidate: `reference_semantics`, all rules and
exact witnesses. Primary metric: the Eq. 13 estimate under the profile, pooled over 10 windows of
40; pass iff the bundle's candidate gate says `ABOVE_ALL_PUBLIC_METHODS`, the smallest lead is at
least 0.05, and the lower end of a paired bootstrap interval of that lead is above the gate margin.

## Numbers

From the results record (private research record; the held-out seed is revealed in it and spent).

- The reference scores 0.9000, the pool's ceiling, in every window. The closest public method,
  `chain_witness`, scores 0.8081: lead 0.0919, 95 percent interval 0.0714 to 0.1145. The gate
  verdict is `ABOVE_ALL_PUBLIC_METHODS` pooled and in all ten windows; the preregistered rule is met.
- Next: the matched baseline 0.5814 (it cites every event), `strong_public` 0.4853, the constant
  clear answer and the count heuristic 0.4000, the constant abstention and the completeness-flag
  heuristic 0.3000, the lookup 0.2555, presence and order 0.0854, every fixed finding 0.11 or less.
- Ablations of the reference, one rule changed (loss): event time 0.47, revoker authority 0.40,
  exact citation 0.32, coarse gaps 0.30, no level ceiling 0.11, gaps ignored 0.10, a missing
  parent read without its gaps 0.03. `chain_witness` is the reference without the broken-chain
  rule and the gap between them, 0.09, is that rule.
- No structural tell was found by the features tried; the details are kept in the private research record.

## Not active

Nothing names the profile or the class except its loader entry, the family's own module and its
runner. A test fails if any other tracked source, script, shadow or reproduction file does. The
class is not in the registry of bound classes, so `bundle.public_methods` and
`bundle.require_weight_eligible` refuse it (`WEIGHT_GATE_CLASS_NOT_BOUND`); a test asserts it. No
shadow service, class binding, run plan, validator configuration or criteria file names it. The
family's code is classed private in the public manifest: its truth is not an answer key, but
exporting a research family is a separate decision. Nothing in this record is an approval.

## Open decisions

- **Whether to bind this family, and under what rules.** The held-out headroom result is NEGATIVE
  (see the dated addendum): the candidate does not clear every public method, so the family is not
  weight-eligible under the gate. The first limit also applies to any later attempt: binding it
  would give weight to the ability to implement a public contract.
- **Whether the reference should be published.** Publishing it makes it a public method and closes
  the gate for everything at or below it; withholding it makes the test depend on the operator,
  which ADR-0021 was written to avoid.
- Whether a second, harder family is built whose rules the contract does not fully determine.
- A seed derivation the operator cannot compute in advance (the seed here was drawn by the
  family's builder, who knows it).

## Limits

- **A family whose exact rules are public saturates at its reference.** The reference scores the
  ceiling of the pool. Once published, it is a public method, and a hypothetical miner at its score
  is `NULL_NO_HEADROOM`: no miner can lead a method at the ceiling. This is a property of any
  deterministic Type A family with a public contract, not of this one. The headroom found is
  between methods that implement the contract and methods that do not (0.32 to 0.88 below the
  reference for all but one method), and between a careful reader who misses one rule and a complete
  one (0.09, which one rule of the contract removes). A family with room above every public method
  needs something the contract does not determine.
- The leads over surface methods depend on the decoys: they are the look-alikes of each rule and
  every instance carries them. With fewer, the leads would shrink; this was not measured.
- One family, one seed, 400 instances: the interval on a lead is about 0.04. Two of ten windows
  have a `chain_witness` lead under 0.05.
- The builder of the family wrote its contract, its reference and every public method, and
  revised three method definitions and seven generator choices on development data before the
  freeze (all recorded in the preregistration). The held-out seed did not exist until the end.
- A tell is measured by the features tried. The check shows none of those tell; it does not show
  that no cleverer feature does.
- Partial observability here is declared gaps. A miner cannot probe the world for the hidden event;
  abstaining is correct whether or not a hidden event existed, which is the point and also makes
  the abstention rate depend on the plant.
- The profile inherits ADR-0022's open points (window of 40 scored cases, redundancy by decision
  vector, the half-price correct abstention).

## Addendum 2026-11-05: correction after re-examination

The registered test was passed, and the pass does not hold. A cheap public method, `chain_witness`
with its one abstention replaced by a guess (report a broken chain instead of abstaining, either
always or when the missing parent's source declares no gap), scores 0.8688 and 0.8880 on the
spent held-out seed and 0.861 and 0.891 on a fresh seed of 1000 instances, against the reference's
0.9000: leads of 0.012 to 0.039, under the preregistered minimum effect of 0.05. The registered
pass depended on the closed baseline list not containing these methods or the reference's one-rule
ablations, one of which the results record already printed. Against the closed list of 30 methods
the gate returns `NULL_NO_HEADROOM`. The headroom is real against methods that do not implement the
contract (0.32 or more) and absent against a careful reader with one guess.

Also stated plainly: the reference's ceiling is circular, because the generator discards any
attempt the open semantics does not read as planted; and the reference is reproducible from the
contract text a miner is given. A family whose semantics a short contract determines cannot have
headroom above its public methods.

Changes made, none of which re-runs or tunes against the spent seed:
- **Gate.** A family registers a closed list of methods and a preregistered minimum effect;
  `registered_gate` takes them from the registry, refuses a caller that omits any registered
  method, and treats a lead under the minimum effect as `NULL_NO_HEADROOM`. DAT-HEADROOM registers
  its 21 methods, the 7 one-rule ablations of the reference and the 2 guesses, effect 0.05.
- **Generator `dat-gen/2`, for future seeds only.** Windows are listed in a seeded shuffle; the
  unauthorised-revocation decoy is logged out of order as often as the plant. This is aimed at a
  logging-order tell found under `dat-gen/1`. No structural tell was found by the features tried;
  the details are kept in the private research record. The spent result remains as recorded under
  `dat-gen/1`.
- **Seed.** Still chosen by the builder; a documented limit. Future held-out seeds should come from
  a committed future block hash or be drawn by a second party.

### What a second family would need (future work, not done here)

- **Semantics not derivable from one contract rule.** Truth that depends on interacting conditions
  no short contract states completely, so that a reader of the contract cannot write the best
  method in an afternoon, and so that adding one guess to a good method does not reach the
  ceiling. The test must include such neighbours (every one-rule ablation and every one-guess
  extension of the best known method) in the closed baseline list before it is run.
- **Adjudicated or richer evidence.** Truth fixed by a recorded adjudication (ADR-0021) or by
  evidence the generator did not produce from the same rules the reference reads, so that
  the generator's filter is not the reference and the ceiling is not circular.
- **An independent seed.** Drawn from a committed future block hash or by a second party, never by
  the builder, and with the held-out set listed in a shuffled order.
- **A baseline list registered, closed and complete before the run**, with the minimum effect
  stated in the same registration.
