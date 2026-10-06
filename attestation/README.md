# SN87 Testnet Attestations

This folder lets anyone with access to this repository check, for themselves, that SN87's
validator really set weights on Bittensor testnet 582, and that the numbers we report match what
the chain recorded. You do not have to trust our logs: the checker reads the chain.

There are two attestation files. Both are checked by the same script.

| File | Runs | Notes |
| --- | --- | --- |
| `SN87_TESTNET_ATTESTATION_01.json` | 8 | The hand run and the first seven operator cycles. Frozen: the run records never change. |
| `SN87_TESTNET_ATTESTATION_02.json` | 21 | Every completed OK run in the evidence at the time it was built: the hand run (`r5-20261005-a`) and every operator cycle after it. Run `r5-20261005-i` failed and is excluded. Contains all 8 runs of 01, with identical records. |

## What is attested

Each file lists completed live runs. For each run it records:

- the run id and the CONFIRM row number (`confirm_seq`) that authorised it, and the approval row
  (`approval_seq` 602) and the approved plan digest;
- the block window the run was allowed to use, and the block in which the weights were included;
- the weights set for uid 0 on netuid 582: uids 1 and 2, each at 65535;
- the digest of the shadow record made just before the run, and the validator "pinned digest"
  (a hash of the validator's full scoring result on the committed test fixtures).

Each file carries its own digest, so an edited copy is detected. It holds no signatures and no key
material of any kind. Provenonce's private tooling builds it from the evidence folders and is
deterministic: the same evidence always gives the same bytes.

## Check it with one command

```
uv sync --locked --extra transport                                # once
uv run --extra transport python scripts/verify_attestation.py     # attestation 02 (the default)
uv run --extra transport python scripts/verify_attestation.py --attestation attestation/SN87_TESTNET_ATTESTATION_01.json
```

A plain `uv run python scripts/verify_attestation.py` drops the bittensor dependency, so every
validator and chain check fails with "No module named 'bittensor'"; always pass `--extra transport`.

It needs network access to the public testnet node and nothing else: no wallet, no keys, no
account. It runs under a throwaway home directory, uses a read-only chain client, and cannot
send anything to the chain.

The output has two clearly separated sections, each with its own tally, so you can read
"reproduces offline" independently of "chain corroboration".

### 1. Offline reproduction (no chain read)

- **Integrity.** The file's own digest recomputes, and `netuid`, `mecid` and `validator_uid` are
  exactly 582, 0 and 0 (the only target the checker reads).
- **Plan.** The approved plan digest is recomputed by running Provenonce's private flip-plan
  tool and compared, for every run. It is UNVERIFIED where that tool is absent.
- **Validator.** The validator pinned digest is recomputed from the committed fixtures, in
  process, with no network beyond loopback, and compared, for every run. It needs the private
  reference executors and is UNVERIFIED where they are absent. A malformed validator seed or
  timestamp in a run fails that run's validator check.

### 2. Chain corroboration (each run at its own block)

Each run is read from the chain's own history at the block it names. `LastUpdate` for uid 0 at the
included block N equals N, and at block N-1 it is strictly less, so uid 0 set weights in exactly
block N. The uid 0 weight row read at block N equals the attested row, and N lies inside the run's
window.

If the node cannot serve state at that block, the run is **UNVERIFIED**, never PASS. The checker
then also reads the current state and prints it as supplementary information (and flags it if it
contradicts the attestation), but that read proves nothing about block N and never turns a run
into a PASS.

## What this proves and what it does not

- **Third-party checkable: the chain rows.** For each run, the checker reads Bittensor testnet 582
  at the attested block and confirms that uid 0 set weights in exactly that block and that the
  weight row there equals the attested row. Anyone with the public testnet node can do this; it
  needs nothing private (`scripts/chain_read.py`, a small read-only client).
- **Not verifiable outside Provenonce: scoring.** The plan digest and the validator pinned digest
  can only be recomputed with the private reference executors and the validator scoring code, which
  are not published. Without them the checker reports those two checks as UNVERIFIED with the
  reason "requires private reference executor", the overall verdict is UNVERIFIED (exit 3), and
  the summary says so. It never reports FAIL for a missing private file, and never PASS while
  anything is UNVERIFIED. In the full Provenonce tree they run and the overall result can be PASS.
- **Not published: evidence files.** The `evidence` field of each run names a run log and a shadow
  record with their sha256. Those files are not in this repository, so those hashes cannot be
  checked by an outsider.
- **Tamper evidence only: the file digest.** The attestation digest sits inside the file, so it
  detects accidental or careless edits; it is not a signature and not a trust anchor.

## Verdicts and exit codes

Verdicts are PASS, FAIL and UNVERIFIED, for each run and overall.

- A run is FAIL if any of its checks fails, UNVERIFIED if none fails but the chain check could not
  be completed, and PASS only if all its checks pass.
- Overall: FAIL if any run or the file integrity is FAIL; UNVERIFIED if nothing is FAIL but any run
  is UNVERIFIED; PASS only if everything is PASS.

| Exit code | Meaning |
| --- | --- |
| 0 | PASS |
| 1 | FAIL (also an unreadable attestation file) |
| 2 | usage error (argparse) |
| 3 | UNVERIFIED |

Change from the first version of this checker: it used to fall back to a "weaker check" (last
weights block at or after N, and the current row equal to the attested row) and report
"PASS (weaker check)". That is retired for every attestation file, 01 included. The same situation
now reports UNVERIFIED and exits 3. Neither file changes: the change is in the checker's verdict
vocabulary only.

## Which runs are included

A run is included only when its log holds exactly one `DONE/RESULT` event, that event is the last
in the log, and its status is OK. Any other run (in progress, failed, several results, or events
after the result) is excluded from the file; the one excluded failed run is `r5-20261005-i`.

## Honest limits

- All miners are Provenonce-operated. This shows our validator pipeline working, not an open
  market of independent miners.
- The tasks are fictional fixtures, not real customer work.
- The weights are equal (65535 each) because the candidate and baseline miners tie. This is
  not evidence that one miner is better than another, and nothing here implies uplift.
- Testnet 582 only. Testnet funds have no value, and nothing here says anything about mainnet.
- The CONFIRM rows were posted by the operator on the approver's directive (rows 622 and 678 of
  Provenonce's private approval ledger). They are not individual per-run human sign-offs. The
  verifier does not read the ledger, so it does not check those rows or their signatures.
- The shadow record digests are listed, but the verifier does not recompute them, because the
  records live in the evidence folders, not in this repository. It does recompute the validator
  pinned digest they contain.
- The checker proves that uid 0 set weights in exactly block N, and that the row at N equals the
  attested row, wherever the node serves history for N; where it does not, the run is UNVERIFIED.
  It also proves that the plan and validator digests reproduce. It does not prove who held the
  validator key.
- An attestation is a snapshot of the evidence when it was built. The operator keeps running, so
  later runs are not in a file that was built earlier.
