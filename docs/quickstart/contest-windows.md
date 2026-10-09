# Contest windows quickstart (draft)

**Not wired to weights. Testnet 582 weights are unchanged.** Everything on this page is shadow
tooling that reads and writes local files. It registers nothing, signs nothing and sends nothing to
a chain. The scoring profile it sizes windows with, `IC-FIRST-LIGHT-MIN-3`, is committed and active
nowhere. Background: [ADR-0020](../architecture/ADR-0020-contest-windows-and-window-sizing-profile.md),
[contest-windows.md](../protocol/contest-windows.md), [window-results.md](../protocol/window-results.md).

## What a contest window is

The operator commits to a hidden seed before a window opens. During the window, miners answer fresh
capsules generated from that seed. After the window closes, the operator publishes per-window
results (scores, and agreement with truth beside each score) and reveals the seed, so anyone can
regenerate the capsules and check the earlier commitment.

## Install

```bash
git clone <this repository> sn87-provenonce && cd sn87-provenonce
uv sync --locked --all-extras          # Python 3.12 or later; versions pinned by uv.lock
```

## Run the dry run

One command runs commit, open, two local miners, truth, results, reveal and verify, offline, into a
new directory:

```bash
uv run python scripts/contest_dry_run.py --out-dir /tmp/contest-demo
```

The two miners are the public candidate method (`approval_witness` from `miners/`) and the
public-contract baseline (`baselines.py`). Both answer the same capsules. The window is
`demo-0001`; its seed is a public demo constant, so its instances are public by construction and are
never used in a real window.

Truth for the demo window comes from the private reference executors when they are installed. In
this repository's public tree they are not, so the script reads the committed truth in
[examples/contest-window-demo](../../examples/contest-window-demo/), after checking that it describes
exactly the capsules regenerated from the seed. The output is the same either way:

- `/tmp/contest-demo/results/window_demo-0001.md` and `.json`: the scores-only page, as published at
  close (agreement, confusion and failure counts derive from truth and are withheld);
- `/tmp/contest-demo/results-full/`: the truth-derived aggregates, produced after the reveal with the
  explicit policy flag (the demo seed is public, so the flag is safe here);
- `/tmp/contest-demo/results-detail/`: the same with per-case rows;
- `commitments.json`, `window_demo-0001.capsules.json`, `window_demo-0001.reveal.json`: the public
  protocol files;
- `private/` and the `.private.` files: what a real operator would keep private.

The pages are deterministic: running the command again into a new directory gives identical bytes
(unless `--timing` is given, which records wall and CPU time). The committed copy of the pages is in
`examples/contest-window-demo/results` and `results-full`, and a test compares a fresh run with them.

Useful options: `--scoring-profile IC-FIRST-LIGHT-MIN-1` (score the same window under the committed
profile that is in use today; there the candidate and the baseline tie on estimate while their
agreement with truth differs), `--preset profile` (only the families the sizing profile assigns).

## Verify a committed window yourself

Anyone can check a window without the operator's files other than the public ones:

```bash
mkdir /tmp/verify && cp examples/contest-window-demo/commitments.json \
  examples/contest-window-demo/window_demo-0001.reveal.json /tmp/verify/
uv run python scripts/contest_window.py --phase verify --window demo-0001 --out-dir /tmp/verify
```

It recomputes the seed commitment, the specification commitment and the schedule commitment from the
reveal, then regenerates every capsule. A changed seed, mix or window time fails with a named error.

## Run the phases by hand

```bash
uv run python scripts/contest_window.py --phase init-master --master-seed-file ./master.hex
uv run python scripts/contest_window.py --phase commit --schedule schedule.json \
  --master-seed-file ./master.hex --out-dir ./out
uv run python scripts/contest_window.py --phase open --window cw-0001 --schedule schedule.json \
  --master-seed-file ./master.hex --out-dir ./out
```

`schedule.json` follows the schema `sn87-contest-schedule/0.1` (see the protocol page); it needs a
unique `schedule_id`. Anchor `commitments.json` to an independent timestamped channel before the first
window opens (the protocol page describes this; the tooling does not do it). Phases refuse
to run at the wrong time: committing after a window opens, revealing before it closes, publishing
results before it closes, and publishing per-case truth without the explicit policy flag. The
`truth` phase needs the private reference executors and says so when they are absent.

Results for a closed window:

```bash
uv run python scripts/contest_results.py --capsules out/window_cw-0001.capsules.json \
  --truth out/window_cw-0001.truth.private.json --responses responses.json --out-dir ./results \
  --profile IC-FIRST-LIGHT-MIN-3
```

This writes the scores-only page. Add `--commitments`, `--reveal` and
`--publish-closed-window-truth` for the truth-derived page once the seed is revealed and the policy
is decided.

## What this does not do

- It does not set weights or change the active scoring profile.
- Truth for a hidden window needs the private reference executors; outside parties verify
  commitments and capsules, and truth only if per-case truth of a closed window is later published
  (an open decision).
- It does not admit outside miners. The responses file is plain input; how responses arrive is out of
  scope.
