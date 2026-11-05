# Limitations

Status: alpha protocol (`0.1.2`) on public testnet netuid 582. Existing testnet rows are
conformance evidence only.

1. **Conformance, not competition.** The First Light row (run `e6ffa76e6f8a14bc0625fc2caf92e2cc`,
   profile `IC-FIRST-LIGHT-MIN-1`, public testnet netuid 582, block 8,102,381) is conformance evidence for
   transport, integrity and arithmetic. Both methods (`state_machine` on uid 1, `relational` on uid 2)
   are Provenonce reference algorithms that also compute the truth, under common control. The later
   attested runs name the same two uids; the methods behind them rest on a privately recorded
   naming binding that cannot be checked from public files. The table in the
   [README](README.md#which-methods-hold-uids-1-and-2) gives the mapping for each period. Equal scores of 1 show agreement,
   not that either beats the other. Every bundle carries `claim: CONFORMANCE_ONLY`.
2. **Plain weight mode only.** Testnet runs with commit-reveal off. Commit-reveal submission exists as tested payload, schedule and state code against a fake chain, with no submitter that sends to a chain, so it has not run on any chain ([second-validator readiness](docs/protocol/second-validator-readiness.md)). The plain path refuses a commit-reveal target.
3. **Binary evidence credit.** Evidence quality is 1 only if every required reference is cited,
   else 0. No partial credit, and no penalty for citing more: under the committed profiles any
   superset of the required refs receives full credit. Newer profile versions score citation
   precision as well: `IC-FIRST-LIGHT-MIN-2` (ADR-0019) and `IC-FIRST-LIGHT-MIN-4` with
   `GRA-RELEASE-MIN-4` (ADR-0022). They are committed and not active on any weight path; the
   committed profiles score as described here.
4. **Dead branch.** The "no grounded dimension, flag for review" branch is unreachable: detection
   is always applicable, so the branch cannot fire.
5. **beta is fixed at 1** (the F-measure with equal weight on precision and recall) in both profiles.
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
   The tie belongs to the published fixtures and to every case with published truth, not to the
   methods: the candidate (item 13) and the baseline are different methods, and on contract-valid
   capsules built from the public fixture generator and edited in memory they return different
   states (for example, the candidate abstains on a broken approval chain and the baseline, which
   reads only the review condition, does not check it). The edits need no reference executor to
   reproduce; their truth is not published, so this shows the methods differ, not which is right.
   See `tests/test_candidate_baseline_divergence.py`.
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
    measured estimate of 1 does not exercise these gaps: they are untested, not measured.
    Separately, the candidate and the baseline are not equivalent: contract-valid capsules built
    by editing a public fixture and re-sealing it make them return different states, mostly
    because the candidate abstains on a broken approval chain; one case runs the other way (a
    same-instant tie of governing versions with one condition, which the candidate decides and
    the baseline abstains on). The truth for those edited capsules is not published, so which
    method is right on them is not measured (see `tests/test_candidate_baseline_divergence.py`). The source
    (`sources/fixtures/`, labelled FICTIONAL) is invented, not a real organisation's data; the
    permission is a fixture, not a legal grant. Two executions of one source configuration
    (12 admitted scored capsules each, the profile minimum) are eligible, and every method,
    candidate and baseline included, scores 1 on those fixtures: a null result with no headroom (Provenonce's
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
    nothing here changes the profile. A new profile version, `IC-FIRST-LIGHT-MIN-3`, assigns a
    larger window than its minimum so that a window absorbs a stated number of reference failures
    (ADR-0020 lists the size and the tolerance, generated from the profile). It is committed and
    not active on any weight path.

16. **The committed profiles do not credit a correct abstention, and ignore declared severity.**
    When recomputed truth is `INSUFFICIENT_EVIDENCE_ABSTAIN` with no defects, a correct
    abstention scores the floor (epsilon, about 1e-6) under the committed profiles, as does a
    wrong answer stated at confidence 1. The calibration term (Eq. 7) is computed over the claims
    the miner chooses to make, and the declared severity of a matched finding is not scored (the
    rationale is required and never scored; scoring it is a Type D question that is deferred).
    Under these profiles score alone does not separate the tested methods under perturbation of
    the evidence; agreement with truth does. This is a description of the committed profiles;
    they are unchanged. New profile versions pay a correct abstention and a wrong-scope
    abstention on record (`IC-FIRST-LIGHT-MIN-2`, ADR-0019), and `IC-FIRST-LIGHT-MIN-4` and
    `GRA-RELEASE-MIN-4` (ADR-0022) additionally score calibration over a fixed set of outcomes
    and score declared severity. Committed, not active on any weight path.

17. **Scoring is checkable for the committed public fixtures only.** The per-case truth of those
    fixtures is published in [`protocol/golden_truth/`](protocol/golden_truth), so the public
    scorer can be run against it, and `scripts/verify_attestation.py` recomputes the attested
    validator digest from it (PASS or FAIL, no reference executor needed). Still not checkable
    outside Provenonce: (a) the plan digest, which covers a plan document built by private
    operator tooling from unpublished files (the check is UNVERIFIED, so a public verifier run
    ends UNVERIFIED, exit 3); (b) that the published truth is the reference executors' output,
    which a private test shows and the digest match supports but does not prove; (c) the truth
    of any instance other than those public fixtures, which only the private reference executors
    compute. For the current families, whose truth is computed from the capsule, the private
    reference executors are load-bearing: published, they would answer any instance whose
    capsule is known. Correct scoring therefore depends on the operator keeping them private and
    running them, and this repository does not remove that dependence. "Open code, hidden instances" (protection from instances being unknown to miners
    until reveal, not from secret code) holds only for a family whose truth is fixed when the
    instance is built (ADR-0021, "Truth fixed at build time for new families"). That is where
    new families are meant to go. One candidate family of that kind is committed (inactive, bound
    to no class, weight 0); its baseline-headroom result is negative (ADR-0024), so no family
    that qualifies exists here yet. Even then the operator can derive
    seeds in advance unless the opening-block seed of ADR-0023 (committed tooling, not deployed) is used, so instances are unknown to miners until reveal
    but not to the operator. The binding gate in `bundle.py` (`candidate_gate`,
    `require_weight_eligible`) is intended to apply before any weighting: a family is
    weight-eligible only if a candidate beats every public method, `approval_witness` included,
    by at least a stated margin (0.001), and a tie is `NULL_NO_HEADROOM` and refuses. It is not
    wired into any live weight path. The files cover the attested seed only; the truth of later
    windows is not published. The design for new families is in
    [ADR-0021](docs/architecture/ADR-0021-published-truth-for-public-fixtures.md).

18. **Pool design bounds constant answers only.** The profiles `IC-FIRST-LIGHT-MIN-4` and
    `GRA-RELEASE-MIN-4` (ADR-0022) cap the share of defect, clear and abstain-truth cases in the
    scored pool, have the loader prove that no constant answer can reach theta minus a margin,
    price surplus citation, and make identities with the same decision vector (state and finding
    codes per case) share one weight, with dispatch, response-time and identical-answer flags
    that are never scored. The bound is on constant answers: a method that uses the pool mix,
    which is public in the profile, is not bounded by it. The pools as committed are small and
    repeat public fixtures, so a public method can reach the same score; that is a headroom
    question, handled by the gate in item 17, not a scoring rule. The redundancy rule cannot tell
    agreement from copying (two independent correct miners share one weight, an open design
    question for Provenonce) and has a second limit stated in ADR-0022. Committed, not active on any weight path; which scoring design a competition uses is
    a decision for Provenonce's own decision process.

19. **Text commitments in a customer export depend on a customer-held key.** A plain
    `sha256` commitment to a short or guessable source text can be confirmed by hashing
    candidate texts. For a source labelled `CUSTOMER_EXPORT` the mapping therefore commits text
    with HMAC-SHA256 under a key the customer holds and passes in; it refuses to run without one,
    never stores or logs it, and records the scheme in the mapping version
    (`launch-approvals-to-institution/0.2@2-hmac`). Plain commitments (the fictional fixtures,
    which hold no secret) keep the earlier version and still verify. What remains: a verifier
    needs the key to check a commitment, so third parties cannot; key custody, rotation and
    loss are the customer's, and the repository does not manage them; HMAC hides the text only
    as well as the key stays secret (the mapping refuses constant or low-variety keys but cannot
    measure entropy); the same text in two fields has the same commitment under one key; and
    `export_class` is required on every permission, so an unlabelled or misspelt class is refused,
    not treated as plain.

20. **The baseline-uplift admission rule cannot be met under today's windows.** The proposed
    criteria require a strictly higher estimate than the public baseline on each shadow window's
    scored instances. On the committed families under `IC-FIRST-LIGHT-MIN-1`, the baseline ties
    the reference methods on both the profile mix and the `messy` mix (item 8), so a tie fails
    every window. Under the committed, not active `IC-FIRST-LIGHT-MIN-2` the references beat the
    baseline. The rule is kept strict; the profile or mix that gives it headroom is undecided.

See [docs/protocol/implementation-status.md](docs/protocol/implementation-status.md) for what
is implemented, enabled, tested and deployed.
