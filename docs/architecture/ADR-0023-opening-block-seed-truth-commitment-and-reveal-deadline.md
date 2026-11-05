# ADR-0023: Opening-block seed, truth commitment at open, reveal deadline (contest protocol 0.2)

**Status:** Proposed. The tooling and tests are committed. No schedule of this version is deployed
and nothing here sets, signs or submits a weight.

**Date:** 2026-11-05

**Deciders:** SN87 protocol maintainers. Deploying the new version and publishing reveals are
operator actions (see "Open decisions").

## Context

Three gaps in the windows of
[ADR-0020](ADR-0020-contest-windows-and-window-sizing-profile.md) motivate this record:

1. The truth that scores a window was committed only after the window closed. Miners were not sent
   a hash of it, so nothing tied the truth published later to the truth that existed while they
   answered.
2. The window seed came from the operator's master seed alone, so the instances were known to the
   operator before the window opened. ADR-0020 already recorded that a public randomness source
   could be mixed in by a later generator version.
3. The shadow page promised a reveal at close. The windows of the first schedule closed with only
   their commitments published.

## Decision

A new contest protocol version, generator `sn87-contest-generator/0.2`. Version 0.1 stays readable
and verifiable; new schedules use 0.2. Every document carries its schema version and every reader
dispatches on it.

1. **Truth hash at open, carried in each request.** The open phase also fixes the truth with the
   private reference (an injectable seam) and a random salt, and publishes `truth_commitment` with
   `cases_commitment` in the capsules file. The commitment function is unchanged (salted, bound to
   the seed commitment and the cases commitment), so it hides the truth. The service sends
   `{generator, window_id, cases_commitment, truth_commitment}` in every request as an optional
   `window_commitments` object of the signed envelope. A truth phase after open is refused.
2. **Refuse a differing hash.** `publish-truth`, `verify` and the results tool compare the truth
   file with the capsules file from open and refuse a different hash (`TRUTH_HASH_DIFFERS_FROM_OPEN`)
   or a missing open record (`OPEN_RECORD_MISSING`). The service refuses to score or publish such
   a truth and never makes a second one if the first is lost.
3. **Truth published after close in a checkable form.** Under the existing `truth_derived` policy
   the service publishes `truth.json` (cases and salt) after close and verifies it first. An
   outsider recomputes the hash from it and compares it with the hash they were sent. The policy
   gate for `publish-truth` is unchanged.
4. **Opening block in the seed.** The committed value becomes a pre-seed commitment; the window
   seed is `HMAC(preseed, frame(domain, schedule_id, window_id, block_number, block_hash))`. The
   block is the first block at or after `opens_at` (rule committed in the schedule), supplied as an
   input: command line flags, or a read-only provider. The service's default provider bisects over
   a read-only chain reader by block timestamp. Tests use fixed fake hashes.
5. **Reveal deadline.** Every window of a 0.2 schedule has `reveal_deadline` in the schedule, spec
   and commitments. The service flags `REVEAL_OVERDUE` in the index and the log when the deadline
   passes with no reveal uploaded. Older windows are held to `closes_at` plus `reveal_grace_hours`.
6. **Whole-schedule reveal tool.** The operator's `shadow_cohort.py reveal-schedule` derives every
   window's seed from the master seed and the committed schedule, checks each against its
   commitment, and writes a bundle. The public `verify-bundle` phase of `contest_window.py` checks
   it from the published commitments alone. It works for both protocol versions. The tool
   publishes nothing.

## Consequences

- Miners and outsiders can show a later truth publication is the one committed at open. They cannot
  show the truth is correct: the reference executors are still private.
- The block hash removes advance knowledge only. The operator still builds the instances and holds
  the executors; a block producer could influence a hash. Operator trust still needs independent
  validators that construct their own challenges. The docs say so.
- The truth must be computed at open, so a window cannot open without the private executors; the
  service holds the window and voids it at close (`NOT_OPENED_IN_TIME`) if they stay absent.
- Miners built before this change reject an envelope with `window_commitments` (422), so the miner
  package must be updated before the first 0.2 window opens. The server accepts both shapes.
- The window seed in a 0.2 file is derived, so the seed itself is revealed only with the pre-seed
  and the block; revealing them reveals nothing about the master seed or other windows.
- The chain-backed block provider (`ShadowChain.block_hash`, `block_time_ms`) is tested against a
  fake only. It has not been run against a live node.

## Open decisions

- Deploying the 0.2 service and updating miners. Publishing the reveal of the first schedule's
  windows with `reveal-schedule` is a separate public action.
- Whether per-case truth publication should stay behind the `truth_derived` policy.
- Whether the opening block should instead be a finalized block, to remove reorg ambiguity.

## Opening-block rules

An operator who could choose among candidate opening blocks would weaken the seed. These rules
narrow that as far as an offline check can, and the last paragraph says what remains.

- **The block is pinned by time, offline.** The block record carries its own timestamp and its
  parent's. `verify`, `verify-bundle` and the open phase require `parent_time < opens_at <= time`,
  so a later (or earlier) block fails without reading a chain. A block typed in by hand is refused
  unless `--allow-manual-block`, and is then marked `manual`. The block is printed, recorded
  before anything else and uploaded in the open record before any miner is queried. A re-open with
  a different block is refused.
- **The block is final.** The service's search stops at the finalized head, else 12 blocks behind
  the head, re-reads the chosen block's hash and times and refuses if they differ, and records the
  depth. This delays opening by the margin. It does not make a reorg impossible.
- **Reveals are tied to the open record.** A bundle entry is `OPENED` (with the published open
  record), `NOT_OPENED` (no seed) or, for 0.1, `REVEALED`. Verification requires the published open
  records for 0.2, so a bundle for windows that never opened does not verify as opened, and
  incomplete bundles fail unless `--allow-partial`. `--min-protocol` refuses a downgrade.
- **Truth is regenerable.** The truth salt is `HMAC(preseed, window id)`. A lost truth file is made
  again and must hash to the published value; if it cannot, the window is void
  (`TRUTH_LOST_AFTER_OPEN`) and its reveal is published, so nothing wedges. Salts must be 32
  lowercase hex characters and a stored truth must name its own window and seed commitment.
- **Deadlines are bounded and visible.** A reveal deadline is at most seven days after close; the
  index flag `REVEAL_OVERDUE` is checked by `verify-bundle --index`; the index lists voided
  windows with reasons per schedule.
- **Rejections are named.** A non-200 answer is `REMOTE_REJECTED_<status>`; a 422 is
  `MINER_REJECTED_ENVELOPE` (a miner that does not know `window_commitments`). Both are
  unavailability and are published per uid.
- **Network named by genesis hash.**

What remains: the block's timestamp is chosen by block producers within the chain's rules, so a
producer can nudge which block is first after the opening time; the offline check cannot show a
block is on the canonical chain (compare number, hash and time with a node); finality is a depth
margin unless the reader offers a finalized head; the operator still builds the instances and
holds the executors.
