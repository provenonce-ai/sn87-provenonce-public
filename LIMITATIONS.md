# Limitations

Status: alpha protocol (`0.1.0a0`) on public testnet netuid 582. Existing testnet rows are
conformance evidence only.

1. **Conformance, not competition.** The First Light row (run `e6ffa76e6f8a14bc0625fc2caf92e2cc`,
   profile `IC-FIRST-LIGHT-MIN-1`, public testnet netuid 582, block 8,102,381) is conformance evidence for
   transport, integrity and arithmetic. Both methods (`state_machine` on uid 1, `relational` on uid 2)
   are Provenonce reference algorithms that also compute the truth, under common control. The later
   attested runs name the same two uids; the methods behind them rest on a privately recorded
   naming binding that cannot be checked from public files. The table in the
   [README](README.md#which-methods-hold-uids-1-and-2) gives the mapping for each period. Equal scores of 1 show agreement,
   not that either beats the other. Every bundle carries `claim: CONFORMANCE_ONLY`.
2. **Plain weight mode only.** Testnet runs with commit-reveal off. Commit-reveal is not implemented.
3. **Binary evidence credit.** Evidence quality is 1 only if every required reference is cited,
   else 0. No partial credit, and no penalty for citing more: any superset of the required refs
   receives full credit. The public-contract baselines use exactly that (they cite every bounded
   event plus the completeness scope, e.g. 13 refs where an IC `stale_authority` case requires 9),
   so their evidence score shows the rule's weakness, not evidence skill. A new profile version,
   `IC-FIRST-LIGHT-MIN-2`, makes the credit precision-aware (ADR-0019). It is committed and not
   active on any weight path; the committed profiles score as described here.
4. **Dead branch.** The "no grounded dimension, flag for review" branch is unreachable: detection
   is always applicable, so the branch cannot fire.
5. **beta is fixed at 1** (F1 score) in both profiles.
6. **Inactive equations.** Eq. 2 (rule score), Eq. 8 (utility) and Eq. 10 (robustness) are
   defined in the whitepaper but not scored; they serialize and display as `"NA"`, never `0`.
   Eq. 11 (efficiency) keeps its neutral factor eta = 1 numerically in raw records because all
   configured cost coefficients are 0; its status is `INACTIVE`. Nonzero coefficients are rejected
   (`COEFFICIENT_ACTIVATION_NOT_AUTHORIZED`). Composite arithmetic is unchanged.
7. **Integrity predicates for authenticated runs are set by a private harness** that is not in this
   repository. Public fixtures and tests cannot be relabelled as authenticated remote exchange.
   Replay does not verify the signed receipts that authenticate the post-seal `responses.json`
   and `report.json` (`RECEIPT_SIGNATURES_NOT_CHECKED_HERE`; see the replay trust boundary in
   docs/protocol/evidence-bundle.md).
8. **Null result against a matched baseline.** Each class binds a public-contract baseline
   (`baselines.py`), evaluated beside the reference methods and never weighted. A test proves
   it sees only the public contract (import graph, plus a runtime run with every evaluator-only
   module blocked). On both committed families it scores 1, like the references: the bundle
   reports `NULL_NO_HEADROOM` for each reference method. That null result is kept, not hidden.
   The two bound methods are role `reference`, because they are also the truth executors (the
   private reference executors, which are evaluator-only and not in this repository). See item 13
   for the one candidate.
9. **Cost measured locally on one machine only.** Cost fields are recorded beside scores
   and are `NA` with a missing reason when not measured: replayed sealed runs did not record time
   (`NOT_RECORDED_IN_SEALED_RUN`). Fixture runs were measured on one Mac; the numbers live in
   Provenonce's private measurement records and are not published here. They are local,
   deterministic-method, fixture-run numbers, not network or production capacity and not
   model-inference cost; no other hardware, load or transport cost is measured.
   At First Light the profile values were applied through function defaults; the scorer now
   applies the committed document and reproduces the same row on replay.
10. **Small N.** First Light scores 12 assignments per method; this is a diagnostic sample, not a
    population-quality estimate.
11. **Synthetic families.** Cases are synthetic approval-applicability and release-workflow
    traces. No claim of real-world assurance, adoption or mainnet readiness is made.
12. **Messy-evidence results are diagnostic only.** Provenonce's private perturbation reports
    measure the reference methods and the baseline under seeded perturbations of the public
    synthetic families. They need the private executors, so they are not reproducible from this
    repository. Nothing in them feeds scoring, the preference row or any incentive; the generators
    are near-identical per index, so n is draws of perturbation noise.

13. **One Provenonce-written candidate, one fictional source, one configuration.**
    `miners/witness_ic.py` (`approval_witness`, role `candidate`) is written and maintained by
    Provenonce from the public contract; it is a replaceable stand-in, still common control, not an
    independent miner. It has no hotkey or uid of its own: a privately recorded naming binding associates it with uid 1
    (the hotkey registered for the First Light method `state_machine`); the attested weight rows
    name only the uid, and the binding is not an identity proof and not verifiable here (see the [README](README.md#which-methods-hold-uids-1-and-2)). Its author had read the
    evaluator-only reference before writing it, so its independence from the oracle is
    unverified beyond the import-graph and blocked-import tests, and its per-action loop closely
    follows the public-contract baseline's (`baselines.py`, the IC action loop). It is a
    deliberately simple method and can be wrong: unlike the evaluator reference it does not check
    reviewer/approver actor bindings, the full three-action and handoff topology, or that the
    reviewed condition was ever governed, so on such contract-valid capsules it may give a
    finding where the reference abstains. Scoring would count such a divergence against it, but
    neither the First Light fixtures nor the FICTIONAL source contains such a capsule, so the
    measured estimate of 1 does not exercise these gaps: they are untested, not measured. The source
    (`sources/fixtures/`, labelled FICTIONAL) is invented, not a real organisation's data; the
    permission is a fixture, not a legal grant. Two executions of one source configuration
    (12 admitted scored capsules each, the profile minimum) are eligible, and every method,
    candidate and baseline included, scores 1: a null result with no headroom (Provenonce's
    private coverage report). That is two windows of one configuration, not
    population quality, not a second source, and not evidence of real-world coverage or cost.
    Model tokens, human exceptions and network cost are `NA` with reasons.
14. **Local qualification only, no exactly-once.** Provenonce's private qualification run
    exercised the queue in `service/queue.py` (lease, fencing, retry, expiry and simulated,
    in-process restart mechanics) in one process on one host over the FICTIONAL source and public
    fixtures, with seeded faults; the harness needs the private executors and is not in this
    repository. Attempts are at-least-once and acceptance is
    at most one per item; exactly-once is not claimed. Networked transport, multi-host, real
    chain, `AUTHENTICATED_REMOTE`, power-loss durability and production load are not qualified.
15. **Operational fragility at the profile minimum (open decision).** The committed First
    Light profile requires 12 admitted scored cases per window, and the fixture and source
    windows carry exactly 12. In the local qualification, a single reference failure removes one
    case from admitted supply and makes the window ineligible (`NO_VALID_PREFERENCE_ROW`).
    Whether to size windows above the minimum, add reference redundancy, or change the minimum
    (which would be a new profile version, never an in-place edit) is a decision for Provenonce;
    nothing here changes the profile.

16. **The score does not credit a correct abstention.** When recomputed truth is
    `INSUFFICIENT_EVIDENCE_ABSTAIN` with no defects, a correct abstention scores the floor
    (epsilon, about 1e-6). The tested methods (both references and the public-contract baseline)
    always state confidence 1, so their wrong answers there also score the floor: a
    `NO_MATERIAL_DEVIATION` scores the same, and a false finding at confidence 1 is higher by
    about 2e-21. A hedged false finding scores above a correct abstention, because its calibration
    term 1 - c^2 stays in the geometric composite (weights 0.60/0.25/0.15, epsilon 1e-6, checked
    with `score_response`): about 1.14e-5 at confidence 0.9 and 1.50e-5 at 0.5, roughly 11 to 15
    times the abstention's 1.0e-6. Provenonce's private multi-seed
    perturbation report shows the tie on IC: the baseline's agreement with
    truth falls to about 0.56 under clock skew, but its mean score delta is identical to the
    references' in every cell. Score alone does not separate the tested methods there; agreement
    does. This is an observation about the committed profiles; they are unchanged. A new profile
    version, `IC-FIRST-LIGHT-MIN-2`, pays a correct abstention and a wrong-scope abstention on
    record (ADR-0019). It is committed and not active on any weight path.

See [docs/protocol/implementation-status.md](docs/protocol/implementation-status.md) for what
is implemented, enabled, tested and deployed.
