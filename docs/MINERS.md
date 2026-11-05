# Miners

> Answer capsules with a method of your own, and see how the public scorer rates it.

Quick links: [start here](guides/start-here.md) | [miner guide](guides/miner-guide.md) | [shadow cohort](guides/shadow-cohort.md) | [glossary](GLOSSARY.md) | [a miner's first day](diagrams/08-miner-first-day.md)

**Status.** Testnet 582, alpha. No outside miner is weighted today, and nothing here promises a
score, a date or any benefit ([LIMITATIONS.md](../LIMITATIONS.md)). The route is three stages:
local, shadow (scored and published with weight 0), then weighted. This page gets you through the
first and shows the way to the second.

## What a miner does

1. The validator sends you a **capsule**: the evidence for one case.
2. Your method returns one **Differential**: `FINDINGS`, `NO_MATERIAL_DEVIATION` or
   `INSUFFICIENT_EVIDENCE_ABSTAIN`, with any findings and the evidence they cite.
3. The public scorer rates it against the truth. You can run the same scorer on public fixtures
   on your own machine.

You run your own endpoint, on your own machine, with your own code. Nobody else runs it.

## Do this, in order

| Step | You do | You see | Page |
|---|---|---|---|
| 1 | Clone, install, run the demo | three scored rows on public fixtures | [start here](guides/start-here.md) |
| 2 | Write a method and score it against published truth | your own rows | [miner guide, Part C](guides/miner-guide.md#part-c-write-a-method-serve-it-locally-score-it) |
| 3 | Serve it locally and rehearse the signed endpoint with a throwaway key | a passing `probe` | [miner guide, Part D](guides/miner-guide.md#part-d-the-signed-endpoint-the-probe-and-the-announcement) |
| 4 | Register a hotkey on 582 with your own wallet | your uid (this repository does none of this for you) | [miner guide, Part E](guides/miner-guide.md#part-e-registration-and-test-funds-on-582) |
| 5 | Sign an announcement and apply to the shadow cohort | a public issue | [shadow cohort](guides/shadow-cohort.md) |
| 6 | Read your row in a published window result | `stage: shadow`, `weight: 0` | [window results](./protocol/window-results.md) |

## What the score looks at

| Part | In one line |
|---|---|
| Detection | Did you find the right defects, and no extra ones? |
| Evidence | Did you cite the references the truth requires? |
| Calibration | Did your stated confidence match what happened? |
| Integrity | Six checks (schema, policy, signature, nonce, evidence, deadline). One failure makes the score 0. |

An invalid or missing answer counts as 0 in your estimate. See the [scoring pipeline](diagrams/03-scoring-pipeline.md)
and the [profile page](./protocol/profile-application.md). Read the limits of the current
scoring in [LIMITATIONS.md](../LIMITATIONS.md) (items 3, 8, 16 and 18) before you rely on a score.

## What to know before you start

- **Do not send what you cannot see published.** After a window closes, the state, finding codes,
  severities, evidence references and confidence of your replies are published. Free text is not.
- **Your miner only answers senders it trusts.** By default that is permit holders. As the operator runs it, a shadow miner
  adds the shadow service address with `--trusted-sender`
  ([who may send](guides/miner-guide.md#who-may-send-the-sender-allowlist)).
- **A matched public baseline is scored beside you.** It ties the reference methods today
  (`NULL_NO_HEADROOM`), so a good score is not yet a sign of skill. Compare with the baseline.
- **Weighted is not by application.** It needs a new plan version approved by the maintainers
  outside this repository ([admission](./protocol/admission.md)).

## If you see this

| You see | Do this |
|---|---|
| `SENDER_NOT_PERMITTED` (403) | Add the sender with `--trusted-sender`, or check that it holds a permit. |
| `REMOTE_REJECTED_403` in a probe | You probed with a throwaway key. Start `serve` with `--probe-hotkey SS58` and run `probe` with `--probe-hotkey-keyfile`. |
| `RESPONSE_LATE` | Make the method faster. Deadlines are at most 15 seconds. |
| `MINER_REJECTED_ENVELOPE` | Update `sn87-miner`; it does not know a field of the request. |
| Anything else | The [error table](guides/miner-guide.md#part-g-troubleshooting-by-error-code). |

## Community and help

Open an issue from the [issue chooser](https://github.com/provenonce-ai/sn87-provenonce-public/issues/new/choose)
(setup failure, scoring question). Site: <https://provenonce.ai/sn87/>. Questions also go to the
"SN87, Provenonce" Telegram group linked from the site FAQ. Report security problems privately
([SECURITY.md](../SECURITY.md)).
