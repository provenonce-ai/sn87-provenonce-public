# Start here: from a fresh clone to a result you can read

About 20 minutes, on your own computer, with no wallet and no account. The clone and `uv sync`
need the network; nothing after that does. You clone the repository, install the pinned packages, run the SN87
scoring path on public synthetic fixtures, read the result, and learn what that result does and
does not show. At the end you will know which of four levels you have reached (this page reaches
the first only) and how to enter the next.

This page is a guide in the format of [guide-format.md](../protocol/guide-format.md).
`scripts/run_guide.py` runs every command below in a temporary clone and compares the output with
the blocks shown, on every change, on Linux and macOS. `scripts/clean_slate_smoke.py` runs this
page again from a clean `git clone` of the committed tree (in CI, as a job on Linux only), so a change that breaks the first hour
of a newcomer fails the build until this file is updated. Nothing here is copied by hand from a
run: the version you test, the digests and the counts are printed by the commands.

**Reading the blocks.** A block marked `bash step` is a command. The block after it, marked
`text expect`, is the output the command must print. In it, a line starting `re:` is a regular
expression that must match the whole line, and `...` stands for any number of lines.

**What SN87 is, in two sentences.** SN87 is a Bittensor subnet where miners test the difference
between observed autonomous work and a declared assurance contract. A miner returns one
`Differential` (its single structured answer for one evidence capsule: `FINDINGS`,
`NO_MATERIAL_DEVIATION` or `INSUFFICIENT_EVIDENCE_ABSTAIN`, with any findings and the evidence
cited) for an evidence capsule, and a validator scores it with one public scorer
([README](../../README.md)).

## The four levels

Four different things can be true of a result, and this repository keeps them apart on purpose.
A participant should always be able to say which one a number belongs to.

| Level | What happens | Where it runs | Who can see it | Reached by this page? | How to enter it |
| --- | --- | --- | --- | --- | --- |
| 1. Local example | You run public code on public synthetic fixtures. The scorer, the fixtures and the published truth are all in this repository. | Your machine only; no chain, no network | Only you | **Yes** | You are here. |
| 2. Shadow participation | Your own signed miner endpoint is queried by the operator's shadow service each window, scored under the committed profiles, and published with `stage: shadow` and `weight: 0`. | Your endpoint, public HTTPS; scored by the operator | Public record | No | [Shadow cohort page](shadow-cohort.md); build the endpoint with [miner guide](miner-guide.md) Parts D to F; apply with the issue form "Shadow cohort application" on the public repository. |
| 3. Independent validation | A party other than the operator recomputes scores from published inputs and gets the same answer. Today that is possible for the committed public fixtures (published truth, public scorer) and for the attestation digests, and not for hidden instances. | Your machine, with public inputs; the chain check reads the public test node | You, and anyone you show | No. Step 9 reproduces the operator's number on your machine; it is not independent validation | [Reviewer test guide](reviewer-test-guide.md) (verify the proof), [validator quickstart](../quickstart/validator.md), [second-validator readiness](../protocol/second-validator-readiness.md). |
| 4. Weighted | A uid appears in an approved weight row set on the chain by the validator. | Bittensor testnet 582 | Public chain | No | Not by application. It needs a new plan version approved by the maintainers outside this repository ([admission.md](../protocol/admission.md), "Approval"). Today the weighted uids are operated by Provenonce ([README](../../README.md), "Honest limits"). |

How to tell where a number comes from:

- A number printed by a command on your machine is **level 1**. It is real arithmetic over public
  fixtures. It says your install works and the scorer agrees with the published truth.
- A row with `stage: shadow` and `weight: 0` is **level 2**. It is a published record. It is
  never a number in a weight row.
- A check line that says PASS from a recomputation you can run yourself is **level 3** evidence
  for the claim that line makes, and for no other claim.
- A weight row on the chain is **level 4**. Reaching it is a decision of the maintainers, not
  something a command can do.

This page does not tell you that any outside uid is in the shadow cohort or is weighted, and it
promises no date and no payout at any level. The file `shadow/allowlist.json` in this repository
was empty when this page was last checked (Step 9 prints its entry count, and the smoke script checks
it). The state of the public repository and its pages is the
authority, not this page.

| Part | What | Time | Level |
| --- | --- | --- | --- |
| A | Prerequisites | 3 min | not applicable |
| B | Clone and set up | 5 min | 1 |
| C | The worked example: run the scorer and read the receipt | 5 min | 1 |
| D | See PASS, UNVERIFIED and FAIL on your machine | 3 min | 1 |
| E | How to read what you got | 5 min | not applicable |
| F | What to do next, and where to ask | 2 min | not applicable |

## Part A. Prerequisites

| Need | Version | Why |
| --- | --- | --- |
| An operating system | Linux or macOS. Windows through WSL2. Native Windows is not supported ([README](../../README.md), "Supported platforms"). | The bundle writer refuses to run where it cannot guard against a swapped symbolic link. |
| `git` | Any current release. This page was last run with the version printed in Step 1. | Clone the repository. |
| [uv](https://docs.astral.sh/uv/) | Any current release. This page was last run with the version printed in Step 1. | Installs Python and the pinned packages from `uv.lock`. |
| Python | 3.12 or later. CI tests 3.12 and 3.13. You do not install it: uv fetches a matching Python if you have none. | The code requires `>=3.12` ([pyproject.toml](../../pyproject.toml)). |
| A shell | `bash` or `zsh`. The commands on this page are plain POSIX shell. | |
| Disk and network | About 1 GB of disk for the packages and Python. The clone and `uv sync` need the network (the sync fills uv's cache). Nothing after that does: the remaining commands run with the network switched off. | The runner for this page sets uv offline, and the staging run turns any non-loopback network attempt into a hard failure. |

You need **no** wallet, hotkey, account, API key, test funds or Valkey/Redis server for this page.
Those appear first in [miner guide](miner-guide.md) Parts D and E, and nothing on this page
creates or asks for them. If any command here asks you for a key, stop: that is not this page.

**Permitted test resources.** On this page you may use exactly these, and no others:

- the public synthetic fixtures built by `institutional_v02.fixtures.build_case` and their
  published truth in `src/sn87_provenonce/institutional_v02/public_fixture_truth.json` and
  `protocol/golden_truth/`;
- the committed attestation files in `attestation/`, read as files;
- a scratch folder of your own (the commands write only under the folder you clone).

You may not point anything at a chain, a wallet or someone else's endpoint from this page. The
public test node is used only by the `network` steps of the [reviewer test
guide](reviewer-test-guide.md), and only to read.

## Part B. Clone and set up

### Step 1. Check your tools

```bash step id=tool-versions
git --version
uv --version
```

```text expect
re: git version .*
re: uv \d+\.\d+\.\d+.*
```

Your version numbers can differ from mine. If either command is not found, install it first (see
the links in Part A) and run this step again.

```bash step id=goto-home silent
cd ~
```

### Step 2. Clone the repository

If a folder `~/sn87-provenonce-public` already exists, git refuses to clone into it. Move or
rename it first (for example to `~/sn87-provenonce-public-old`), then run this step.

```bash step id=clone
git clone https://github.com/provenonce-ai/sn87-provenonce-public
```

```text expect
Cloning into 'sn87-provenonce-public'...
...
```

```bash step id=enter-repo silent
cd sn87-provenonce-public
```

### Step 3. Note which version you are testing

Put this value in anything you report.

```bash step id=version
git rev-parse --short HEAD
```

```text expect
re: [0-9a-f]{7,40}
```

### Step 4. Install the pinned packages

`--locked` makes uv use exactly the versions in `uv.lock` and refuse to change them. This is the
only step besides the clone that needs the network, and only if uv's cache is cold. It takes a few
minutes the first time.

```bash step id=install timeout=900
uv sync --locked --extra transport
```

```text expect
...
re: Installed \d+ packages? in .*
...
```

The `transport` extra is the chain library and the web stack. The demo (Step 6) does not need
it, but the staging run (Step 7) and the verifier (Part D) do: the staging run quantizes its
weight row with the chain library's own function, and without the extra it stops with "the
bittensor SDK is required". The README and the other guides always install with it, so this page
does too.

### Step 5. Check the install

```bash step id=install-check
uv run --extra transport python -c "import sn87_provenonce; print('install ok')"
```

```text expect
install ok
```

## Part C. The worked example

You will run the same path a validator takes on a public fixture, two ways: the 60-second demo
(one miner method, three fixtures) and the staging run (a validator and two miners, 16 fixture
instances, a baseline, and a receipt file). Both are local and offline.

### Step 6. Run the demo

```bash step id=demo
uv run --extra transport sn87-provenonce demo
```

```text expect
SN87 quickstart: IC-APPROVAL-APPLICABILITY (institution/0.2), profile IC-FIRST-LIGHT-MIN-1
scope: local, offline, in-process; unsigned wire bytes; synthetic public fixtures scored against published truth; no signed transport, no chain, no hidden instances
miner method: approval_witness

case stale_authority
re:   capsule sha256:[0-9a-f]{64} \(\d+ bytes sent, \d+ bytes returned\)
  miner state FINDINGS; published truth FINDINGS
  row: score=1 valid=True precision=1 recall=1
re:   dimensions: \{.*\}
case fresh_review
re:   capsule sha256:[0-9a-f]{64} \(\d+ bytes sent, \d+ bytes returned\)
  miner state NO_MATERIAL_DEVIATION; published truth NO_MATERIAL_DEVIATION
  row: score=1 valid=True precision=1 recall=None
re:   dimensions: \{.*\}
case incomplete
re:   capsule sha256:[0-9a-f]{64} \(\d+ bytes sent, \d+ bytes returned\)
  miner state INSUFFICIENT_EVIDENCE_ABSTAIN; published truth INSUFFICIENT_EVIDENCE_ABSTAIN
re:   row: score=\S+ valid=True precision=1 recall=None
re:   dimensions: \{.*\}

an abstain on an incomplete capsule earns the profile's epsilon floor, not a full score.
integrity predicates are asserted locally; see the README for what this omits.
```

Read it line by line. The `scope:` line is the first thing the demo tells you, and it is the
level: local, in process, unsigned, public fixtures, no chain. For each case, "miner state" is
what the example miner answered and "published truth" is what the repository says the right
answer is. `score=1` means they agree and the evidence references were all cited. The third case
gives the miner nothing to find, and abstaining is the right answer, but it scores only a small
floor value, not 1. The demo says so in its last lines.

### Step 7. Run the staging validator

The staging run is a small local subnet in one process: a validator derives 16 fictional
instances (12 are scored: 8 `stale_authority` and 4 `fresh_review`; the other 4, `incomplete`, are
diagnostic and do not count toward the estimate), sends them as bytes to two miners (the example method and the public-contract
baseline), scores every return with the one scorer, forms a weight row, and writes a receipt.
`--truth golden` takes the per-case truth from the published vectors, so this works for anyone;
nothing in it needs a private file.

```bash step id=staging timeout=300
uv run --extra transport python scripts/staging_subnet.py --truth golden --out results/staging
```

```text expect
LOCAL STAGING, FICTIONAL FIXTURES, NO CHAIN, NOT AN INCENTIVE-BEARING RESULT
re: truth source: published golden vectors \(75 cases in 2 files under protocol/golden_truth, digest sha256:[0-9a-f]{64}\)
re: \S*results/staging/STAGING_RUN_RECEIPT\.json \S*results/staging/STAGING_RUN_RECEIPT\.md
re: u16 \{1: 65535, 2: 65535\} NULL_NO_HEADROOM sha256:[0-9a-f]{64}
```

The last line is the result in short: the two miner uids (placeholders 1 and 2, not keys) get
equal weights (`u16` is the chain's unsigned 16-bit weight scale, where `65535` is the maximum), the
candidate against baseline comparison is `NULL_NO_HEADROOM` (headroom is how far a miner's estimate
is above the baseline's; none here), and the last field is the pinned digest of the run.
The first line repeats the label that is in every file the run writes.

### Step 8. Read the receipt headline

The receipt is a file, so you can read it at leisure. The headline block is the result; the rest
is the evidence for it (per-case scores, each miner's returns and their digests).

```bash step id=receipt-headline
grep -E '^- (Pinned digest|Candidate estimate|Candidate vs baseline)' results/staging/STAGING_RUN_RECEIPT.md
```

```text expect
re: - Pinned digest: `sha256:[0-9a-f]{64}`
- Candidate estimate: 1; baseline estimate: 1; delta 0
- Candidate vs baseline: **NULL_NO_HEADROOM** (null results are kept; no headroom is manufactured)
```

### Step 9. Check your result against the published record

This step turns the printout into a comparison against a record. The attestation file records, for
each of its testnet runs, the digest the validator pinned for its scoring. The staging run you
just did used the same seed and timestamp (the defaults), so if your scorer and the published
truth agree with the validator's, your digest equals the attested one. The snippet reads two
files on your machine and compares them. It also prints the counts that the prose on this page
relies on, so that a change to any of them fails the page: the 75 published truth cases appear in
Step 7's output, and here you get the instances by track, the number of integrity predicates and
the state of the shadow allowlist.

```bash step id=compare-digest
uv run --extra transport python - <<'EOF'
import json
from dataclasses import fields
from pathlib import Path

from sn87_provenonce.scoring import Integrity

receipt = json.loads(Path("results/staging/STAGING_RUN_RECEIPT.json").read_text())
attestation = json.loads(
    Path("attestation/SN87_TESTNET_ATTESTATION_02.json").read_text())
attested = {run["validator_pinned_digest"] for run in attestation["runs"]}
print("headline:", receipt["pinned"]["headline"]["candidate_vs_baseline"])
print("network attempts during the run:", receipt["volatile"]["network_attempts"])
print("attested runs read:", len(attestation["runs"]))
cases = receipt["pinned"]["per_case_scores"]
for track in ("scored", "diagnostic"):
    print(f"instances, {track}:", sum(case["track"] == track for case in cases))
print("integrity predicates:", len(fields(Integrity)))
allowlist = json.loads(Path("shadow/allowlist.json").read_text())
print("shadow allowlist entries:", len(allowlist["entries"]))
print("your digest equals the attested one:", attested == {receipt["pinned_digest"]})
EOF
```

```text expect
headline: NULL_NO_HEADROOM
network attempts during the run: 0
attested runs read: 21
instances, scored: 12
instances, diagnostic: 4
integrity predicates: 6
shadow allowlist entries: 0
your digest equals the attested one: True
```

`True` means: the public scorer, run by you on the public fixtures against the published truth,
reproduces the digest that the validator's records name. **This is reproducibility, not
independent validation.** The code you ran is the operator's code, and the file you compared with
is the operator's attestation file. It shows that your install reproduces the operator's number.
It does not show that the operator is right, and nobody independent has checked anything. It is
a statement about scoring of public fixtures. It is not a statement about the chain, about hidden instances or about any miner
other than the two in the receipt. Part E says what else it is not.

## Part D. See PASS, UNVERIFIED and FAIL on your machine

The public verifier checks the attestation file against the chain. Run it with no node to read,
and you see all three verdicts in one place, each meaning what it says. The flag
`--endpoint http://127.0.0.1:9` points the verifier at a port where nothing listens. That stands
in for "the public test node could not be reached". With network access you would drop the flag,
and the chain lines would turn into PASS or FAIL; that is the `network` step of the [reviewer
test guide](reviewer-test-guide.md).

### Step 10. Run the verifier with no node

```bash step id=verify-offline exit=3 timeout=300
uv run --extra transport python scripts/verify_attestation.py --endpoint http://127.0.0.1:9 \
  | grep -E '^(integrity|reproduces offline|chain corroboration|OVERALL|exit code)'
```

```text expect
re: integrity  PASS  digest recomputes \(sha256:[0-9a-f]{64}\)
re: reproduces offline: (PASS|UNVERIFIED)  \(.*\)
re: chain corroboration: UNVERIFIED  \(0 PASS / 0 FAIL / \d+ UNVERIFIED of \d+ runs\)
re: OVERALL UNVERIFIED: .*
exit code 3 (0 = PASS, 1 = FAIL, 3 = UNVERIFIED)
```

Read the four verdicts:

- `integrity PASS`: the check ran and the claim holds. The attestation file's digest recomputes
  from its own contents.
- `reproduces offline`: the digests of the scoring are recomputed from published inputs. In this
  public repository the plan digest cannot be recomputed (it is built by operator tooling that is
  not published), so there you see UNVERIFIED with the PASS count beside it; in a tree that holds
  the tooling you see PASS. Either way the line says which.
- `chain corroboration: UNVERIFIED`: the check **could not run here**, and the verifier claims
  nothing. This is not a failure. It is the honest answer to "I could not look".
- `OVERALL UNVERIFIED` and exit code 3: one UNVERIFIED keeps the whole verdict UNVERIFIED. It is
  not turned into PASS because most lines passed.

### Step 11. Make a check fail

Copy the attestation, change one number in the copy, and check the copy. The real file is not
touched.

```bash step id=tamper-make silent
uv run --extra transport python - <<'EOF'
import json
from pathlib import Path

source = Path("attestation/SN87_TESTNET_ATTESTATION_02.json")
data = json.loads(source.read_text())
data["runs"][0]["row"]["weights"][0] -= 1
Path("results/tampered.json").write_text(json.dumps(data, indent=2))
EOF
```

```bash step id=tamper-check exit=1 timeout=300
uv run --extra transport python scripts/verify_attestation.py \
  --attestation results/tampered.json --endpoint http://127.0.0.1:9 \
  | grep -E '^(integrity|OVERALL|exit code)'
```

```text expect
re: integrity  FAIL  .*
re: OVERALL FAIL: .*
exit code 1 (0 = PASS, 1 = FAIL, 3 = UNVERIFIED)
```

In plain words: the command changed one weight by one unit in a copy of the attestation file.
The file carries a digest of its own contents, so the verifier recomputes the digest, finds that
it no longer matches, prints `integrity  FAIL` and exits with code 1. The real file and the chain
are unchanged.

FAIL means the check ran and the claim does not hold. It is ranked above UNVERIFIED: a check that
ran and found a difference is worse than one that could not run. If this printed PASS, that would
be a bug worth reporting.

## Part E. How to read what you got

**PASS, FAIL, UNVERIFIED.** These are the only three verdicts of the verifier.

| Verdict | Means | Does not mean |
| --- | --- | --- |
| PASS | The check ran, and the one claim it makes holds. | That anything beyond that claim holds. |
| FAIL | The check ran, and the claim does not hold. | That the cause is known. |
| UNVERIFIED | The check could not run here. Nothing is claimed. | That it would pass, or that it would fail. |

**The comparison with the baseline.** Every bundle also scores a matched public-contract
baseline: an algorithm written from the public contract only, never weighted, never on chain. A
miner's estimate is compared with the baseline's, and the result is one of:

| Result | Means |
| --- | --- |
| `NULL_NO_HEADROOM` | The miner's estimate equals the baseline's. The difference is zero. |
| `ABOVE_BASELINE` | The miner's estimate is greater than the baseline's. |
| `BELOW_BASELINE` | The miner's estimate is less than the baseline's. |

**A baseline tie is not uplift.** (Uplift is a miner doing measurably better than the baseline on
cases it could not have looked up.) Your run printed `NULL_NO_HEADROOM`: the example miner and the
baseline both scored 1 on the same 12 scored instances. That is a tie, and a tie is kept and
reported, not hidden. It does not mean the example miner is better than the baseline, and it does
not mean the baseline is good. It means these public fixtures have no headroom: a method that
reads the review condition alone, as the baseline does, gets every public case right. The tie
belongs to the fixtures and to every case with published truth ([LIMITATIONS.md](../../LIMITATIONS.md),
item 8), not to the methods. The two methods do differ on capsules edited in memory from the same
generator (their truth is not published, so that shows they differ, not which is right). Only an
`ABOVE_BASELINE` on cases whose truth the miner could not have seen would be evidence of uplift.
Nothing on this page can produce one.

**What `score=1` and "digest equals the attested one" do not show.**

- They do not show that a miner works on hidden instances. The truth of the public fixtures is
  published, so a method that looks the answers up would also score 1. That is why the truth for
  hidden instances is kept private and why this page reaches level 1 only.
- They do not show signed transport. The bytes in the demo and the staging run are unsigned and
  the six integrity predicates (schema, policy, signature, nonce, evidence, deadline; Step 9 counts
  them) are asserted true in process ("integrity predicates asserted
  in-process" is in the receipt's `not_claimed` list).
- They do not show anything about the chain. The receipt's uids 1 and 2 are placeholders. The
  chain is touched only by the verifier of Part D, and only to read.
- They are not an incentive-bearing result. Nothing, not even a ranking, follows from them.

Read [LIMITATIONS.md](../../LIMITATIONS.md) before you cite any number from this repository.

## Part F. What to do next, and where to ask

You have reached level 1. Step 9 showed that your install reproduces the operator's number, which is reproducibility, not independent validation (level 3). To go further:

1. **Write and score your own method (still level 1).** [Miner guide](miner-guide.md) Part C: a
   one-function method scored against the published truth, and the reference method served over
   local HTTP. About 15 minutes.
2. **Verify the live proof yourself (level 3).** [Reviewer test guide](reviewer-test-guide.md)
   Part F reads the public test node, read only, with no key. One PASS or one FAIL there is a
   claim about that file against that chain.
3. **Run a signed endpoint (toward level 2).** [Miner guide](miner-guide.md) Parts D and E. This
   is where a wallet, a hotkey on netuid 582 and test funds first become your business; this
   repository does not do any of it for you.
4. **Apply for the shadow cohort (level 2).** [Shadow cohort page](shadow-cohort.md), "How to
   join": the route is your registered hotkey, a reachable signed endpoint, a signed announcement,
   the issue form "Shadow cohort application" on the public repository, and a reviewed pull
   request that adds your uid to `shadow/allowlist.json`. Only after that is merged is your uid
   queried. The page lists what is not promised: no dates, no number of places, no benefit
   beyond the published record.
5. **Weighted (level 4)** is not an application route. See the table at the top.

**Where to ask.** Open an issue from the [issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose).
Use "Setup failure" if a command on this page did not do what the page says (include the version
from Step 3 and your platform), and "Scoring question" if you disagree with a score. Report
security problems privately as described in [SECURITY.md](../../SECURITY.md). Paste no key, seed,
wallet file or token into an issue.

The commands wrote only inside the folder you cloned (the `results/` folder, uv's `.venv`) and
into uv's package cache. To start again from nothing, delete the folder you cloned.
