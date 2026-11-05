# Shadow cohort: admission criteria

<!-- guide: no-steps -->

**Status.** Testnet 582 only, alpha ([LIMITATIONS.md](../../LIMITATIONS.md)). This page is the
public admission criteria for the shadow cohort. It changes no weight, no plan version and no
chain state. Nothing on this page says that any uid is in the cohort.

## What the shadow cohort is

The shadow cohort is the set of outside uids on netuid 582 that are queried, scored and published
in every contest window without being weighted. It is the middle stage of the route in
[admission.md](../protocol/admission.md): `local`, then `shadow`, then `weighted`. This page is
about the middle stage and about what would have to be true to leave it.

## What shadow means

* Each window, a shadow uid receives the same capsules as every other method, answers them through
  the signed endpoint, and is scored with the public scoring code, applied to truth the operator derives.
* Its result is published with `stage: shadow` and `weight: 0`. A shadow result is a record, not a
  number in a weight row. It never reaches one. As the operator describes it in
  [admission.md](../protocol/admission.md) ("Shadow scoring"), the shadow code reads the score
  summary only and has no path to the weight quantizer.
* As the operator runs it (see [admission.md](../protocol/admission.md), "Shadow scoring"; the
  service is not in this repository), every window is scored under two profiles, side by side and
  labelled:

| Profile | Status | How it is shown |
|---|---|---|
| `IC-FIRST-LIGHT-MIN-1` | The default profile; the profile the maintainers use on the live path (operator statement) | Shown first, as the profile in use. |
| `IC-FIRST-LIGHT-MIN-2` | Committed, not the default | Beside it, labelled "committed, not active". It sets no weight. |

  See [profile-application.md](../protocol/profile-application.md) for what each profile means.
* As the operator runs it, a public-contract baseline and the public candidate method (run
  in-process, labelled "reference") are scored on the same capsules, so a row for your uid has
  rows to compare with. This repository cannot verify that.

## How to join

You do every step that touches the chain. The maintainers do none of them.

1. **Register a hotkey and uid on netuid 582 yourself.** [Miner guide, Part E](miner-guide.md)
   lists what you do with your own wallet tools. The guide performs none of it.
2. **Run the signed endpoint.** Follow [Part D of the miner guide](miner-guide.md): generate or
   supply your hotkey, start a replay store, check the configuration, and run `sn87-miner serve`
   behind a TLS reverse proxy on a public HTTPS origin. Use `sn87-miner probe` to check it before
   you apply.
3. **Announce it.** Sign an announcement for that HTTPS origin with your registered hotkey
   (`sn87-miner announce`, Step 14 of the miner guide) and serve it with
   `sn87-miner serve --announcement announcement.json --netuid 582 ...`. It is then available at
   `GET /.well-known/sn87-miner-announcement.json` on your endpoint. Check it with
   `sn87-miner verify-announcement announcement.json --netuid 582`. The format and the discovery
   rule are in [miner-announcement.md](../protocol/miner-announcement.md). Publishing the
   on-chain endpoint record as well is optional, is a chain write, and is yours to sign and send.
4. **Open the issue form.** On the public repository
   (`provenonce-ai/sn87-provenonce-public`) choose "Shadow cohort application". It asks for your
   uid, hotkey, netuid, endpoint origin, the URL of your signed announcement, the `sn87-miner`
   version or commit, your platform, and four confirmations. Paste no key, seed, wallet file or
   token. Everything in the issue is public.
5. **Review.** A maintainer checks the announcement against the rules in
   [miner-announcement.md](../protocol/miner-announcement.md) and the hotkey against the chain
   (read only). If it passes, a maintainer opens a reviewed pull request that adds the uid to
   `shadow/allowlist.json` and cites your issue. That file is in the public repository and is
   changed only by a reviewed pull request that cites the intake issue; the first such pull request
   that adds a uid also creates or fills it. Only after that pull request is merged is your uid
   queried.

A failure in steps 1 to 3 is a setup problem: see Part G of the miner guide, or open the "Setup
failure" issue form. Questions go to the same issue tracker or to the "SN87, Provenonce" Telegram group linked from
the SN87 site (provenonce.ai/sn87/faq).

## What we do and do not do

* We never register, fund or change anything on chain for you. Your registration, your hotkey and
  any on-chain record are yours.
* As the operator runs it, the shadow service holds no wallet and no registered hotkey, and it
  writes nothing to a chain. It signs its challenges with one stable transport signing key, read
  from a key file only the operator can read. That key is not registered, not funded and not a
  hotkey of any uid; its public address is printed by the operator's `shadow_cohort.py --config CONFIG
  signer-address` (operator-side tooling, not in this repository). There is no secret for you to hand over, and the form must never contain one.
  The service refuses to start without that key file, and refuses a key file that is inside a
  wallet folder, owned by another user, or the registered hotkey of a uid on the subnet. (Only a
  rehearsal may use a random key per run, which an allowlisted miner refuses.)
* **Your miner must trust that address.** `sn87-miner serve` accepts only validator-permit holders
  by default. The service is not one, so add `--trusted-sender <shadow service address>` to your
  `serve` command (see "Who may send" in the [miner guide](miner-guide.md)). The service address
  is **not published yet**: once the operator has configured the key, the shadow page at
  `https://provenonce.ai/sn87/shadow` shows the address (the address only), and you should take it
  from there; until that page shows it, ask in the intake issue. Until you add it, your
  miner answers the service with 403 and the window records you as unavailable.
* As the operator runs it, in each window the service generates fresh instances from a committed seed, finds the endpoints of
  allowlisted uids by the discovery rule in [miner-announcement.md](../protocol/miner-announcement.md),
  sends the signed challenges, validates the replies and scores them.
* Schedules committed from contest protocol 0.2 on also fix the truth when the window opens: the
  service computes the truth hash (salted, so it hides the truth) at open, publishes it with the
  cases commitment, and sends both in every request to your miner, inside the signed request body
  under `window_commitments`. Your miner can keep that record: after the window the published truth
  must hash to exactly the value it was sent. A miner built before this change rejects the extra
  field, so update `sn87-miner` before the first 0.2 window opens.
* The window seed of a 0.2 window also mixes in the hash of the first block at or after the opening
  time, so the instances are not known to anyone, the operator included, until that block exists.
  That removes advance knowledge only. It does not make the operator a neutral party: the operator
  still builds the instances and holds the reference executors, so trust in the scoring needs
  independent validators who construct their own challenges. Do not read the block hash as more
  than that.
* Intended practice, not yet done for any window: we publish your responses after the window closes, together with the seed, so that anyone can
  regenerate the capsules and check the commitments. A published response contains the state, the
  finding codes, severities, evidence references and confidence, and a digest of the full reply.
  The free text of a reply (method, rationale) is not published. Do not send anything you are not
  willing to see published.
* A reply that fails the response checks (identity, binding, signature, replay, media type) is an
  integrity failure. A timeout, a refused connection or a rejected request is unavailability. The
  difference is defined in [admission.md](../protocol/admission.md).

## Where results are published

Intended practice, not yet done for any window: results are static, public and read only, at `https://provenonce.ai/sn87/shadow`. For each
window the set holds a page and the JSON behind it:

* the seed **commitment**, published before the window opens (for a 0.2 window it commits to a
  pre-seed; the window seed is derived from the pre-seed and the opening block);
* the window description and the capsules, with, for a 0.2 window, the cases commitment, the truth
  commitment and the opening block, which are also what each request carried;
* the **reveal** of the seed, published after the window closes and by the window's
  `reveal_deadline`;
* for a 0.2 window under the `truth_derived` policy, the per-case **truth** with its salt
  (`truth.json`), published after close;
* the responses, and the results under `IC-FIRST-LIGHT-MIN-1` and under `IC-FIRST-LIGHT-MIN-2`;
* one record per uid, with `stage: shadow` and `weight: 0`.

The format of a window result is in [window-results.md](../protocol/window-results.md).

**Verify a window.** Copy the schedule's commitments file to `commitments.json`, and the window's
`reveal.json` and `capsules.json` to `window_<window id>.reveal.json` and
`window_<window id>.capsules.json`, all in one folder. Then run the verify phase of
`scripts/contest_window.py` with `--window <window id> --out-dir <that folder>`. It recomputes the
seed, specification and schedule commitments and regenerates every capsule, and fails with a named
error on any difference. The steps, with a committed demo window, are in
[Verify a committed window yourself](../quickstart/contest-windows.md).

**Check the truth of a 0.2 window.** Put `truth.json` beside the other files as
`window_<window id>.truth.json` and run the same verify phase. It recomputes the truth commitment
from the published truth and its salt, and refuses (`TRUTH_HASH_DIFFERS_FROM_OPEN`) unless that
hash equals the one in the capsules file published at open and carried in every request. The
service itself refuses to publish or score a truth whose hash differs.

**Reveal deadline.** Every window of a 0.2 schedule has a `reveal_deadline` in the committed
schedule and in the commitments file. The index marks a window `REVEAL_OVERDUE` once the deadline
has passed with no reveal uploaded, and the service logs `REVEAL_OVERDUE` on every tick until it
is. A schedule cannot set a deadline more than seven days after close. Windows committed before 0.2 have no deadline field and are held to their close plus
`reveal_grace_hours` (default 24, at most 168). The index lists, per schedule, how many windows were
published void and why.

**Inactive report profiles.** The operator can name committed profiles in the optional
`report_profiles` setting (up to four). The service then scores them beside the two it always
scores and publishes them as `reports` in the window record and as `results-PROFILE.json`, each
labelled `profile_status: INACTIVE`, stage `shadow`, weight 0: they are not the profile in use and
no weight path reads them. A profile that records redundancy groups (`IC-FIRST-LIGHT-MIN-4`) also
publishes its groups and flags. Admission-ready records for these profiles are under
`data/WINDOW/report-PROFILE/`. Each query's dispatch and reply times are published as
milliseconds from the start of the window's queries (a monotonic reading, never a clock time).
`IC-FIRST-LIGHT-MIN-4` needs at least 36 scored cases, and the service refuses to commit a
schedule whose windows are sized below a report profile's minimum. The setting is off by default.

**Reveal a whole schedule (operator, local).** The seeds of windows that closed without a
published reveal can be derived and published as one bundle. The operator's shadow service tool has
a local `reveal-schedule` command (it is not part of the public tree) that takes the master seed
file, the committed `schedule.json` and the published commitments file. It derives every window's
seed from the master seed and the committed schedule, checks each against its published
commitment, and writes the bundle (mode 0600, never overwritten). It publishes nothing. For a 0.2
schedule it takes the published open records with `--open-dir` (files named
`window_<id>.open.json`, the published `open.json` of each window, or `window_<id>.capsules.json`);
the opening block comes from those records, never from free-form input, and a window with no
open record is written as an explicit `NOT_OPENED` entry with no seed.

**Check a reveal bundle.** Anyone can check a bundle with only the published commitments file:

```text
uv run python scripts/contest_window.py --phase verify-bundle \
  --bundle reveal-bundle.json --commitments commitments.json
```

It recomputes, for every window in the bundle, the seed (or pre-seed) commitment and the
specification commitment, and fails with a named error on any difference. Beside the bundle it
takes `--open-dir` (required for 0.2: each reveal must match the cases commitment, truth
commitment and opening block published when the window opened, and a window the bundle calls
`NOT_OPENED` must have no published record), `--min-protocol 2` (refuse a 0.1 bundle),
`--index index.json` (fail on a window the index marks `REVEAL_OVERDUE` that the bundle does not
cover, and list each schedule's voided windows with reasons) and `--now`. Closed windows the
bundle does not cover are an error (`BUNDLE_INCOMPLETE`) unless `--allow-partial`. For a 0.2
bundle it also checks offline that each block is the first at or after the window's opening
(parent before, block at or after) but does not read a chain: compare each block number, hash and
time with a node of the network.

**What you cannot recompute.** For windows before 0.2 the service does not publish per-case truth;
where a window page says `TRUTH_DERIVED`, the agreement figures are computed by the operator from
truth you cannot see. For a 0.2 window under `truth_derived` you can check the published truth
against the hash sent at open, but the reference executors that produced it are still not
published, so you cannot recompute that truth from a capsule, and you cannot show it is correct,
only that it was not changed after the window opened. Each window page says which figures are
published and which are withheld. Do not rely on a check the page does not claim.

## Proposed criteria for moving from shadow to weighted

These are **proposals**. They are committed as a file,
[shadow/criteria-proposed.json](../../shadow/criteria-proposed.json), made with
`scripts/admission_plan.py criteria` and marked `PROPOSED_NEEDS_AUTHORITY_APPROVAL`. They can
change, and a change is a new file with a new digest.

| Rule | Proposed value |
|---|---|
| `consecutive_windows` | 7 (the latest 7 window indexes, none missing) |
| `min_valid_responses_per_window` | 24 in each of those windows |
| `max_integrity_failures_per_window` | 0 |
| `require_endpoint_announcement_valid` | true: a valid announced endpoint |
| `require_signature_verified` | true: the announcement signature is verified |
| `results_must_be_shadow_with_weight_zero` | always on |
| `allowed_profile_ids` | `IC-FIRST-LIGHT-MIN-1`: every one of those windows must be scored under a listed profile |
| `require_score_beats_public_baseline` | always on: in every one of those windows your estimate must be strictly above the public baseline's estimate on the same scored instances. A tie is not uplift, and a uid that scores zero cannot pass however many valid replies it sent. |

The rules are machine-checkable. Anyone can run the checker on published results:

```text
uv run python scripts/admission_plan.py check --criteria shadow/criteria-proposed.json \
    --results RESULTS_DIR --uid U --hotkey SS58 --netuid 582 --endpoint-record record.json \
    --now-ms NOW --now-window W
```

What to feed it:

* `RESULTS_DIR`: an empty folder holding a copy of `data/<window id>/uid-<N>.json` (under
  `/sn87/shadow`) from each of the latest windows. The checker reads every `*.json` file in the
  folder, so give each copy a distinct name, for example `<window id>-uid-<N>.json`.
* `--uid` and `--hotkey`: your uid and its SS58 hotkey.
* `--now-window`: the window index of the latest window (the `window_index` field of its
  `window.json`).
* `--now-ms`: the current time in milliseconds since the Unix epoch.
* `--endpoint-record`: your signed announcement file.

It prints `PASS` or `FAIL` with one reason per problem. The rules and reason codes are in
[admission.md](../protocol/admission.md), "Criteria".

Known limit: the baseline comparison uses each window's own fresh instances and profile. With
the committed families and the active profile the public baseline scores the same as the
reference methods, so under today's windows no uid can pass this rule; see
[admission.md](../protocol/admission.md), "Open decisions". The rule is not relaxed for this.

Passing the checker does not move a uid. Moving a uid to `weighted` needs a new plan version that
names it, approved by the maintainers outside this repository, and the live weight path does not
read this repository's checker. See [admission.md](../protocol/admission.md), "Approval".

## What is not promised

* No dates. This page gives no start, window or review schedule.
* No benefit of any kind from being in the cohort beyond the published record.
* No number of places. The allowlist is reviewed uid by uid and may be closed or emptied.
* Shadow is not a commitment to weight. A uid can pass every proposed rule and not be weighted, and
  the proposed rules can change before any uid is considered.
* Providing an endpoint does not guarantee that a window is valid or scored. A window can be void,
  for example when the sample is too small or the operator's own checks fail, and a void window says
  nothing about your uid.
