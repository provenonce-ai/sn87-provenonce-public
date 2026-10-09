# Miner quickstart (draft)

**Draft.** Target: public testnet netuid 582, alpha protocol, conformance evidence only
([LIMITATIONS.md](../../LIMITATIONS.md)). Nothing here registers a key, creates a wallet or
touches a chain. Wallets, hotkeys and funds are the operator's.

For a single walkthrough that runs every command in CI, with the expected output after each, use
the [miner guide](../guides/miner-guide.md). This page is the reference it draws on.

## What a miner does

Receives a capsule (a bounded, canonical `institution/0.2` or `gra/0.1` JSON object), returns one
`Differential`: `FINDINGS`, `NO_MATERIAL_DEVIATION` or `INSUFFICIENT_EVIDENCE_ABSTAIN`. Findings
need an exact code, confidence and evidence references; evidence credit is binary, so cite every
required reference. Missing or late responses count as raw failures.

## Install

```bash
git clone <this repository> sn87-provenonce && cd sn87-provenonce
uv sync --locked --extra dev           # Python 3.12 or later; versions pinned by uv.lock
uv run pytest tests/test_miner_serve.py tests/runtime/test_reference_miner.py
uv run sn87-provenonce demo
```

The unsigned localhost server below needs only `uv sync --locked` (no chain SDK, no test tools).
Add `--extra transport` (pins `bittensor`, `starlette`, `uvicorn`, `valkey`, `httpx`) for the
signed endpoint (`sn87-miner serve`, see [Serve on testnet](#serve-on-testnet)) and the verifier.

## One method, two servers

A method is one function, capsule in and differential out. Two servers call the same method
object and return the same canonical bytes for the same capsule:

| | `sn87-miner serve` (default) | `scripts/miner_serve.py`, or `sn87-miner serve --unsigned-loopback` |
| --- | --- | --- |
| Wire | `POST /v1/assurance`, `btauth/1` signed request and signed response | `POST /cmt`, canonical capsule bytes, no signature |
| Replay protection | shared Valkey store, fails closed | none |
| Key | your hotkey, read inside the process | none |
| Bind | loopback by default; TLS in front for anything else | loopback only, enforced |
| Use | testnet, and local runs that exercise the real wire | development only |

`tests/transport/test_miner_launcher.py` checks that the signed endpoint's `differential` equals
the loopback body byte for byte for the same capsule.

## Run the unsigned localhost miner server (development only)

```bash
uv run python scripts/miner_serve.py --role candidate --port 8787
```

It is unsigned. It binds loopback only (any other `--host` is refused), loads no key and sends
nothing to a chain.
At startup it compiles the task description (the CMT) and verifies its commitment; it exits with
an error if that fails. In a second terminal:

```bash
curl http://127.0.0.1:8787/health
```

Send it a fixture capsule (`POST /cmt`: body is the canonical capsule bytes, the answer is the
canonical response bytes):

```bash
uv run python - <<'PY'
import json
import urllib.request

from sn87_provenonce.canonical import canonical_bytes
from sn87_provenonce.institutional_v02.fixtures import build_case

capsule = build_case("stale_authority")
request = urllib.request.Request("http://127.0.0.1:8787/cmt",
                                 data=canonical_bytes(capsule), method="POST")
with urllib.request.urlopen(request) as response:
    answer = json.load(response)
print(answer["state"], [finding["code"] for finding in answer["findings"]])
PY
```

Expected output: `FINDINGS ['STALE_APPROVAL']`. Stop the server with Ctrl-C (SIGINT) or SIGTERM.
`--role baseline` serves the matched public-contract baseline instead; the header
`X-CMT-Commitment` is optional and must equal the server's commitment if present. The full wire
behaviour, error codes and limits are in the docstring of `scripts/miner_serve.py`
(`src/sn87_provenonce/miner_node/loopback.py`).

## Write your own method

A method is a function from one validated capsule to one differential, written from the public
contract only (`institutional_v02/contracts.py`, `canonical.py`). `miners/witness_ic.py` is a worked
example; `miners.register(class_id, method_id, fn)` registers a method. To serve your own function
without registering it, give `sn87-miner serve` its import path: `--method package.module:function`
(it receives the capsule exactly as sent and validates its own input). The boundary revalidates
every response against the strict models. `tests/test_separation.py` shows how Provenonce checks
that a method sees nothing beyond the public contract. `docs/runtime/reference-miner.md` describes
the transport-neutral response boundary for the v0alpha1 objects.

## Serve on testnet

`sn87-miner serve` runs the signed endpoint behind `pilot.server.create_app`: `POST /v1/assurance`
authenticated with the SDK's `btauth/1` envelope over the exact request bytes, a shared replay
store that refuses requests when it cannot prove freshness, and a signed response. `GET /ready`
reports the replay store. It never touches a chain: it does not register a key, set weights or
publish an on-chain endpoint. The design is in
[ADR-0005](../architecture/ADR-0005-signed-http-and-replay-boundary.md).

1. Register your own hotkey on netuid 582 with your own wallet (operator action; not covered
   here).
2. Run a replay store. Any Valkey-compatible server whose `maxmemory-policy` is `noeviction`
   works; the tests and CI use Valkey 9.1.2. For example:

   ```bash
   docker run -d --name sn87-replay -p 127.0.0.1:6379:6379 \
     valkey/valkey:9.1.2@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd
   ```

   That digest is the image CI tests against.

   A new store refuses requests (`REPLAY_STORE_WARMING`, `/ready` returns 503) for one freshness
   window, about 13 seconds, so a restart cannot re-admit an old request.
3. Check the configuration. Nothing is started; the replay store is pinged and its eviction policy
   verified:

   ```bash
   uv sync --locked --extra transport
   uv run sn87-miner serve --role candidate --hotkey-keyfile PATH \
     --valkey-url redis://127.0.0.1:6379/0 --check
   ```

   `--hotkey-keyfile PATH` takes a key file only you can read (mode 0600: a looser mode is
   refused). `--hotkey-env NAME` takes the name of an environment variable that holds the seed,
   mnemonic or key file text. The key is read inside the process and never printed or logged;
   `--valkey-url-env NAME` keeps a store password out of the command line, and credentials in a
   URL are never echoed. An encrypted key file is refused.
4. Serve:

   ```bash
   uv run sn87-miner serve --role candidate --hotkey-keyfile PATH \
     --valkey-url redis://127.0.0.1:6379/0 --port 8787
   ```

   `--role candidate|baseline` selects a reference method; `--method package.module:function`
   selects your own. The default bind is loopback. To listen on another address, add
   `--allow-non-loopback` and put TLS in front (a reverse proxy): validators call HTTPS for any
   remote endpoint.
5. Test it with a signed request. `probe` sends one fixture capsule from a throwaway caller key
   and verifies the signed response; the caller-side replay store can be the same Valkey:

   ```bash
   uv run sn87-miner probe --endpoint http://127.0.0.1:8787 \
     --miner-hotkey YOUR_HOTKEY_SS58 --valkey-url redis://127.0.0.1:6379/0
   ```

   Expected: `probe OK: signed request answered and verified; state=FINDINGS
   findings=['STALE_APPROVAL']`. The probe waits out its own caller-side store's start-up window
   (about 13 seconds) the first time.
6. Announce the endpoint so a validator can find it: sign a record with your hotkey and serve it
   at the well-known path. The record format, the verification rules, the validator's discovery
   rule and the optional on-chain endpoint record are in
   [docs/protocol/miner-announcement.md](../protocol/miner-announcement.md). As of this draft the
   on-chain endpoint record is not published by this repository, and which route validators read
   on testnet 582 is an open decision listed in that document.
7. Check the validator's published expectations (deadline, 262,144-byte wire limit).

## Resources

No resource numbers are published here. Local, deterministic-method timings exist only in
Provenonce's private measurement records, and they are not network, signing, TLS or production
capacity, and not model-inference cost. Measure your own engine.

## Limits

Both reference methods are Provenonce code. Each bundle also reports a matched public-contract
baseline (`public_contract_baseline`, never weighted, never on chain) and a per-method
`comparison`; on the public fixtures the reference methods show `NULL_NO_HEADROOM` (no measured
headroom over the baseline). Plain weight mode, no commit-reveal. Do not expect scores to rank
competing methods yet. The scorer is public and the truth of the public fixtures is published; the truth of hidden
instances is private ([README](../../README.md)).
