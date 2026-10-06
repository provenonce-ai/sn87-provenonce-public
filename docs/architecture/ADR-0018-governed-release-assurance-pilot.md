# ADR-0018: Governed Release Assurance pilot bytes and scoring

Status: accepted for implementation. Testnet deployment remained subject to Will O'Brien's review of the exact bootstrap transaction.

## Decision

Implement `gra/0.1` as a bounded pilot alongside the existing `v0alpha1` and toy simulation. The published Proof of Assurance whitepaper v0.7.2 controls. Reuse the two existing Type C reference algorithms; disclose their common control. Missing events support defects only inside the declared complete trace.

The exact canonical JSON and length-prefix rules, severity matching, optional dimensions, finite numeric behavior, assigned failure accounting, and no-valid-row rule are specified in the preregistration of profile `GRA-W03-3` (kept privately). The profile commitment is `sha256:e732ea977497a6ccd5e9541c8fd98bc949086ade5cbeccb058a38312329eda21`. Existing conformance vectors and new protocol tests bind interoperability. No historical scoring formula or `lane_one.py` transformation is promoted to live weighting policy.

The first revision was a diagnostic starting implementation. Independent review produced a second, requiring confidence on every asserted finding and closing assignment/invalid-response errors. A further valid-large-response storage failure produced `GRA-W03-3`, separating the unchanged 262,144-byte wire limit from bounded local batch storage. Earlier documents remain intact. Each revision preceded release holdout evaluation; no failed release result was rescued by retuning.

The private benchmark tooling creates new salted commitments and source/profile seals outside Git. It preserves every assigned failure and refuses source drift or relabeling a local rehearsal as remote evidence. Authenticity uses the pinned SDK and the shared replay boundary in ADR-0005; an unavailable store fails closed. Target conversion never invents preferences to satisfy chain constraints.

## Evidence and limits

The integrated suite of this repository and the private benchmark tooling executed with 391 passing tests. Independent review ran seven additional adversarial regressions and 120 malformed-type probes. A standard-library Decimal implementation reproduced all 96 responses in each of two fresh local rehearsals within absolute error 4.1e-22. A run with five missing scored responses per method retained 96 assignments, yielded `NO_VALID_PREFERENCE_ROW`, and resumed with zero redispatches.

Those results establish software behavior. GRA-W03-3 was a recorded evaluation whose row was never submitted; the later First Light row (profile IC-FIRST-LIGHT-MIN-1, public testnet netuid 582) is the applied conformance evidence.
