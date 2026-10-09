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
* As the operator runs it, the shadow service holds no wallet and no registered hotkey. It signs
  its challenges with a throwaway key held in memory, generated for the run. There is no secret for
  you to hand over, and the form must never contain one.
* As the operator runs it, in each window the service generates fresh instances from a committed seed, finds the endpoints of
  allowlisted uids by the discovery rule in [miner-announcement.md](../protocol/miner-announcement.md),
  sends the signed challenges, validates the replies and scores them.
* We publish your responses after the window closes, together with the seed, so that anyone can
  regenerate the capsules and check the commitments. A published response contains the state, the
  finding codes, severities, evidence references and confidence, and a digest of the full reply.
  The free text of a reply (method, rationale) is not published. Do not send anything you are not
  willing to see published.
* A reply that fails the response checks (identity, binding, signature, replay, media type) is an
  integrity failure. A timeout, a refused connection or a rejected request is unavailability. The
  difference is defined in [admission.md](../protocol/admission.md).

## Where results are published

Results are static, public and read only, at `https://provenonce.ai/sn87/shadow`. For each
window the set holds a page and the JSON behind it:

* the seed **commitment**, published before the window opens;
* the window description and the capsules;
* the **reveal** of the seed, published after the window closes;
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

**What you cannot recompute.** The service derives truth for each fresh window with reference
executors that are not published, and it does not publish per-case truth. Where a window page says
`TRUTH_DERIVED`, the agreement figures are computed by the operator from that truth. You can check
the commitments and the capsules, and you can see every response, but you cannot recompute the
scores of a hidden window from the published files alone. Each window page says which figures are
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
