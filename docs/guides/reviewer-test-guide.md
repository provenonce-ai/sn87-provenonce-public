# SN87 reviewer test guide

Walkthrough, about 30 to 40 minutes. You run SN87 on your own computer, check its proof on the
public test network, and report what did not work.

This guide is written once, here. `scripts/run_guide.py` runs its commands and compares the
output with the blocks below. The offline parts run on every change, on Linux and macOS, and a
change that breaks them fails the build until this file is updated. The parts marked `network`
(Part F and the second command of Part G) run in a separate job that does not block merges. The format is described in
[guide-format.md](../protocol/guide-format.md). Nothing in the guide is copied by hand from a
run: the numbers in Part F come from [the attestation file](../../attestation/SN87_TESTNET_ATTESTATION_02.json).

**Why it is safe.** You need no wallet, no keys and no account. The commands read the
public test network and write only inside the folder you clone and in uv's package cache.
Nothing you run sends or changes anything on a chain.

| Part | What | Time |
| --- | --- | --- |
| A | Open the public repository | 1 min |
| B | Install | 5 min |
| C | Inspect a CMT | 3 min |
| D | Run the two miners | 3 min |
| E | Run the offline demo | 3 min |
| F | Verify the live testnet proof (needs the network) | 8 min |
| G | Tamper demonstration (optional) | 2 min |
| H | Report back | 5 min |

## Part A. Open the public repository

Open <https://github.com/provenonce-ai/sn87-provenonce-public>. No sign-in is needed. Read the
top of the README: the question it asks, and the section "Verify the chain proof yourself".

You should see the README with the SN87 banner and the licence (MIT).

## Part B. Install

You need `git` and [uv](https://docs.astral.sh/uv/). You do not need to install Python: uv
fetches it. No GitHub account is needed.

### Step 1. Check your tools

```bash step id=git-version
git --version
```

```text expect
re: git version .*
```

```bash step id=uv-version
uv --version
```

```text expect
re: uv \d+\.\d+\.\d+.*
```

Your version numbers can differ.

### Step 2. Clone the repository

Go to your home folder first. The cleanup step at the end assumes you are there.

```bash step id=goto-home silent
cd ~
```

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

An error here means a network problem or a typo. The repository is public, so no sign-in is
involved.

### Step 3. Note which version you are testing

Put this value in any report you write, so the maintainers know what you ran.

```bash step id=version
git rev-parse --short HEAD
```

```text expect
re: [0-9a-f]{7,40}
```

### Step 4. Install the pinned packages

Stay in the `sn87-provenonce-public` folder. The first install takes a few minutes and fetches
about fifty packages.

```bash step id=install timeout=900
uv sync --locked --extra transport
```

```text expect
...
re: Installed \d+ packages? in .*
...
```

Always add `--extra transport` to uv commands in this guide. Without it the chain library is
missing, and every check later shows FAIL with "No module named 'bittensor'". That is an install
mistake, not a finding.

### Step 5. Run one sanity command

It only loads the code and prints one line.

```bash step id=sanity
uv run --extra transport python -c "import sn87_provenonce, bittensor; print('install ok')"
```

```text expect
install ok
```

## Part C. Inspect a CMT

A CMT is a Canonical Miner Task: the written specification of what a miner is asked to do, plus a
compiled report. It is a candidate schema and is not adopted. Only one task family compiles.

### Step 6. Find the specification and the reference CMT

The reference CMT is fictional and public. Fields the specification leaves open show the text
`not_in_v0_1`. Open these in any editor or in the GitHub web view; the listing proves they exist
in your clone.

```bash step id=cmt-files
ls docs/protocol/cmt-v0.1.md tests/cmt_vectors/ic_approval_applicability.cmt.json src/sn87_provenonce/cmt/__init__.py
```

```text expect
docs/protocol/cmt-v0.1.md
src/sn87_provenonce/cmt/__init__.py
tests/cmt_vectors/ic_approval_applicability.cmt.json
```

### Step 7. Recompile the CMT, byte for byte

This builds the CMT again from the code and compares it with the saved file.

```bash step id=cmt-recompile
uv run --extra transport python -c "from sn87_provenonce.cmt import *; from pathlib import Path; c=compile_cmt(task_family='IC-APPROVAL-APPLICABILITY'); print(cmt_commitment(c.manifest)); print(compiled_bytes(c)==Path('tests/cmt_vectors/ic_approval_applicability.cmt.json').read_bytes().rstrip(b'\n'))"
```

```text expect
re: sha256:[0-9a-f]{64}
True
```

`True` means the compiler reproduces the saved file byte for byte. The first line is the
commitment of the manifest; it is also written inside the saved file.

## Part D. Run the two miners

A miner reads an evidence capsule and answers one of three things: `FINDINGS`,
`NO_MATERIAL_DEVIATION` or `INSUFFICIENT_EVIDENCE_ABSTAIN`. The candidate miner is the new
method. The baseline miner is the plain method. Both run on three fictional cases.

### Step 8. Run both miners on the three cases

Each line shows the case, then the candidate answer, then the baseline answer.

```bash step id=miners
uv run --extra transport python -c "from sn87_provenonce.institutional_v02.fixtures import build_case as b; from sn87_provenonce.miners.witness_ic import approval_witness as w; from sn87_provenonce.baselines import ic_approval_applicability as a; [print(f, w(b(f))['state'], a(b(f))['state']) for f in ('stale_authority','fresh_review','incomplete')]"
```

```text expect
stale_authority FINDINGS FINDINGS
fresh_review NO_MATERIAL_DEVIATION NO_MATERIAL_DEVIATION
incomplete INSUFFICIENT_EVIDENCE_ABSTAIN INSUFFICIENT_EVIDENCE_ABSTAIN
```

The two methods agree on these three cases, and on every case that has published truth. That is
the result for this step. It is a property of the three cases, not proof that the methods are the
same: `tests/test_candidate_baseline_divergence.py` shows where they differ. The code is in
`src/sn87_provenonce/miners/witness_ic.py` (candidate) and `src/sn87_provenonce/baselines.py`
(baseline).

## Part E. Run the offline demo

### Step 9. Run one challenge end to end on your machine

The demo runs the `institution/0.2` path for the three public fixtures. It builds a capsule,
sends the canonical bytes to the miner method, takes the canonical response back, and scores it
against the published truth. It runs offline and touches no chain.

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

The scorer is in the public repository; the reference executors that compute expected truth for
hidden instances are not, so a stranger cannot copy the answers to hidden instances. The demo
scores against truth that was computed elsewhere and published for these three fixtures. Part F
shows how you can still check the live results on the chain.

### What an honest tie means

On testnet both miners get the same score, so both get the same weight. Neither method beat the
other, and the record does not hide that. The test had no room to tell them apart: on the
published fixtures the baseline reaches the same answers as the candidate. That is a statement
about those fixtures, not about the two methods. The methods differ on other capsules, and on a
finding the candidate cites only the records it needs while the baseline cites every event, which
the original scoring rule does not penalise. `tests/test_candidate_baseline_divergence.py` builds
those capsules from the public generator and shows both differences. A tie is not a failure and
not a win. No claim is made that the candidate is better.

## Part F. Verify the live testnet proof

Provenonce runs a validator on the Bittensor public test network, number 582, and it set
weights there many times.
<!-- BEGIN STATUS:guide_attested_runs -->
The file called attestation 02 lists 21 of those runs, from `r5-20261005-a` to `r5-20261006-e`.
<!-- END STATUS:guide_attested_runs -->
The next command checks that file against the chain itself. It only reads. It needs no wallet,
no key and no account, and it runs under a throwaway home folder.

### Step 10. Check attestation 02 against testnet 582

Stay in the `sn87-provenonce-public` folder. This step needs internet access (port 443 to the
public test node) and takes about one minute. The runner marks it `network`.

```bash step id=verify network timeout=600 exit=0,3
uv run --extra transport python scripts/verify_attestation.py --attestation attestation/SN87_TESTNET_ATTESTATION_02.json
```

<!-- BEGIN STATUS:guide_verify_expect -->
```text expect
SN87 testnet attestation verification (read only: no key, no chain write)
...
integrity  PASS  digest recomputes (sha256:57af3c99d683fd3c868bfe6cbcc3353451fab70f70c2a374c0eec11a9c552b7a)
...
run r5-20261005-a  block 8152574  PASS  uid 0 set weights in exactly block 8152574 (LastUpdate 8102381 at block 8152573, 8152574 at block 8152574) and the row at block 8152574 equals the attested row; block is inside the window 8152571-8152871
...
run r5-20261006-e  block 8160152  PASS  uid 0 set weights in exactly block 8160152 (LastUpdate 8159785 at block 8160151, 8160152 at block 8160152) and the row at block 8160152 equals the attested row; block is inside the window 8160150-8160450
...
chain corroboration: PASS  (21 PASS / 0 FAIL / 0 UNVERIFIED of 21 runs)
...
re: OVERALL (PASS|UNVERIFIED): .*
...
re: exit code [03] \(.*\)
```
<!-- END STATUS:guide_verify_expect -->

The report has two sections. Section 1 asks whether the published code, on your machine,
reproduces the numbers in the file. Section 2 asks whether the chain agrees with what the file
says happened. Only section 2 ties the file to the chain. Read them apart.

The expected public result is: file integrity PASS, chain corroboration PASS for every run, the
validator check PASS (recomputed from the published per-case truth), and the plan check
UNVERIFIED because the plan is built by Provenonce-private operator tooling. The overall verdict
is then `OVERALL UNVERIFIED` with exit code 3. In the private source tree, where that tooling is
present, the same command can report PASS and exit 0.

### Step 11. Read what PASS, FAIL and UNVERIFIED mean

- **PASS.** The check ran and the claim holds. It means what the check says and no more.
- **FAIL.** At least one check did not match: a number differs, the chain row differs, or the
  file was changed. Exit code 1. First check your setup: fresh clone, no edited files, installed
  with `--extra transport`. Run once more. If it stays FAIL, file a Setup failure issue (Part H)
  with the full output. A FAIL is a finding.
- **UNVERIFIED.** The check could not run here, so nothing is claimed. In the public repository,
  the plan check is always UNVERIFIED (private operator tooling), so the overall verdict is
  UNVERIFIED with exit code 3. A chain run can also be UNVERIFIED if the test node cannot serve that block;
  run again later.

The attestation lists completed runs only. A run that failed is left out, which is why the
run-id letters in the file can skip (see [attestation/README.md](../../attestation/README.md)).

This check shows that the numbers in the file match the chain, and that the published code
reproduces the published digests. It does not show that the subnet is good, valuable or
competitive.

## Part G. Tamper demonstration (optional)

### Step 12. Change one number in a copy and watch the check fail

The first command copies the attestation, changes one weight in the copy only (the weight of the
first run) and saves it as `tampered.json` in the repository folder. The real file is not
touched. The second command checks the copy.

```bash step id=tamper-make silent
uv run --extra transport python - <<'EOF'
import json
src = 'attestation/SN87_TESTNET_ATTESTATION_02.json'
data = json.load(open(src))
data['runs'][0]['row']['weights'][0] -= 1
json.dump(data, open('tampered.json', 'w'), indent=2)
EOF
```

```bash step id=tamper-check network timeout=600 exit=1
uv run --extra transport python scripts/verify_attestation.py --attestation tampered.json
```

```text expect
SN87 testnet attestation verification (read only: no key, no chain write)
...
re: integrity  FAIL  .*
...
re: run r5-20261005-a  block \d+  FAIL  .*
...
re: OVERALL FAIL: .*
...
re: exit code 1 \(.*\)
```

You should see FAIL, not PASS. The integrity line shows a digest mismatch, and the line for the
first run shows the chain holds one value while the file now says another. This is the point of
the demonstration: the check catches an edit. If it printed PASS here, report it.

## Honest limits

Read these before you judge what you saw. [LIMITATIONS.md](../../LIMITATIONS.md) has the full
list.

- **Provenonce-operated miners.** Provenonce runs both miners. This shows the validator pipeline
  working. It does not show an open market of independent miners.
- **Fictional tasks.** Every case is invented and the right answers are known in advance. This is
  not an accuracy figure and not customer work.
- **An honest tie.** Both miners get equal weights because the published fixtures cannot tell
  them apart; the methods themselves differ elsewhere. That is not evidence that one is better,
  and no uplift is claimed.
- **Testnet only.** Network 582. The plan digest depends on private operator tooling, so the public
  checker reports the plan check as UNVERIFIED. Test TAO has no value. Nothing here says anything about the main
  network.
- **No adoption claim.** Nothing here is a claim about adoption, customers or pricing.

## Part H. Report back

If every command worked, you are done. If a step failed, or an output differs from this guide,
that is a finding. Open an issue from the
[issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose). The
forms are in `.github/ISSUE_TEMPLATE/`:

```bash step id=templates
ls .github/ISSUE_TEMPLATE
```

```text expect
config.yml
scoring-question.yml
security.yml
setup-failure.yml
```

- **Setup failure** (`setup-failure.yml`): a command or an expected output in this guide did not
  work as written. Give your platform, the step number, the version from Step 3, the command, and
  the last 40 lines of output. Redact paths that identify you.
- **Scoring question** (`scoring-question.yml`): a score or a fixture you cannot explain.
- **Security** (`security.yml`): do not put vulnerability details in an issue. The form only asks
  for the private route described in [SECURITY.md](../../SECURITY.md).

Two questions are worth answering in a setup report even when nothing failed. Did every command
work, and which step failed if not? After the steps and the limits, can you say what is real (the
code and the testnet proof) and what is a demonstration (fictional tasks, Provenonce-run miners,
a tie)? Say what was unclear.

## Cleanup (optional)

When you are done you may delete the folder you cloned in Step 2 with your file manager. It
holds everything the guide created, including `tampered.json`. You can clone it again at any
time.
