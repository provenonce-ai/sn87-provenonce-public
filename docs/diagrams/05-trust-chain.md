# Diagram 5: Trust and verification chain

> What each check depends on, what you can run yourself, and what stays UNVERIFIED outside
> Provenonce.

Quick links: [diagram index](README.md) | [attestation README](../../attestation/README.md) | [reviewer test guide](../guides/reviewer-test-guide.md) | [previous](04-contest-window-timeline.md) | [next: weight flow](06-weight-flow.md)

Every check ends in one of three words. **PASS**: it ran and the claim holds. **FAIL**: it ran and
the claim does not hold. **UNVERIFIED**: it could not run here, and nothing is claimed.

```mermaid
flowchart LR
    subgraph INPUTS["Inputs you can get"]
        F1["Attestation file<br/>attestation/*.json"]
        F2["Golden truth<br/>protocol/golden_truth/<br/>public fixtures, seed 0"]
        F3["Public scorer and<br/>committed profile"]
        F4["Public testnet node<br/>read only"]
        F5["Published commitments,<br/>open records, reveals"]
    end

    subgraph RUN["Checks anyone can run"]
        K1["integrity<br/>file digest recomputes,<br/>netuid 582, mecid 0, validator uid 0"]
        K2["validator<br/>pinned digest recomputes<br/>from published truth"]
        K3["weights<br/>attested row equals<br/>the pinned weights"]
        K4["chain<br/>uid 0 set weights in<br/>exactly the attested block"]
        K5["window verify<br/>seed, spec and schedule<br/>commitments recompute,<br/>every capsule regenerates"]
        K6["truth hash<br/>published truth hashes to the<br/>value sent when the window opened"]
    end

    subgraph NOPE["Stays UNVERIFIED outside Provenonce"]
        U1["plan<br/>digest of a plan document built by<br/>private operator tooling"]
        U2["truth is correct<br/>needs the private<br/>reference executors"]
        U3["uid to method naming<br/>private naming binding,<br/>not an identity proof"]
        U4["opening block is on the<br/>canonical chain<br/>compare it with your own node"]
        U5["instances built honestly<br/>operator builds them<br/>and holds the answer key"]
    end

    F1 --> K1
    F1 --> K3
    F1 --> K2
    F2 --> K2
    F3 --> K2
    F1 --> K4
    F4 --> K4
    F5 --> K5
    F5 --> K6
    K1 --> OVER
    K2 --> OVER
    K3 --> OVER
    K4 --> OVER
    U1 --> OVER
    OVER["Overall verdict<br/>one UNVERIFIED keeps it UNVERIFIED<br/>exit code 3"]

    classDef ok fill:#eaf6ec,stroke:#2e7d32,color:#1a1a1a
    classDef no fill:#fff8e1,stroke:#b58900,color:#1a1a1a
    classDef inp fill:#e8f1fb,stroke:#1f5fa8,color:#1a1a1a
    class K1,K2,K3,K4,K5,K6 ok
    class U1,U2,U3,U4,U5,OVER no
    class F1,F2,F3,F4,F5 inp
```

## Reading the chain

| Check | Depends on | Result today | Command |
|---|---|---|---|
| integrity | the attestation file only | PASS | `scripts/verify_attestation.py` |
| validator | golden truth, public scorer, committed profile, the staging validator | PASS for the attested seed | `scripts/verify_attestation.py`, `scripts/staging_subnet.py` |
| weights | the attestation file | PASS | `scripts/verify_attestation.py` |
| chain | the public testnet node (needs network) | PASS | `scripts/verify_attestation.py` |
| plan | private operator tooling and unpublished files | UNVERIFIED | not runnable here |
| window verify | commitments and reveal files | PASS or FAIL per window | `scripts/contest_window.py --phase verify` |
| truth hash | the truth file and the open record | PASS or FAIL per window | `scripts/contest_window.py --phase verify` |

The README shows a real run of the verifier, generated from the code, in
[Verify the chain proof yourself](../../README.md#verify-the-chain-proof-yourself).

## What a PASS does not prove

- A validator-check PASS shows the scorer reproduces the attested digest from the published truth.
  It does not show the truth is right, and it says nothing about hidden instances
  ([ADR-0021](../architecture/ADR-0021-published-truth-for-public-fixtures.md)).
- A truth-hash PASS shows the truth was not changed after the window opened. It does not show the
  truth is correct, because the reference executors stay private.
- A commitments file proves order only if you know when it was published. The tool produces the
  value to anchor; it does not anchor it.
- The block record is checked offline for the time rule (`parent_time < opens_at <= time`). The
  tool does not read a chain to show the block is canonical.
- A window result record carries a digest, not a signature. The digest detects accidental edits;
  it cannot tell the validator's record from one written by someone else with a correct digest
  ([admission.md](../protocol/admission.md), "Trust boundary of the window result").

## Where the code is

`scripts/verify_attestation.py`, `scripts/chain_read.py` (read-only chain client),
`scripts/golden_truth.py`, `scripts/staging_subnet.py`, `scripts/contest_window.py`,
`scripts/render_verifier_output.py`. What each check proves is spelled out in
[attestation/README.md](../../attestation/README.md).
