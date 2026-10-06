# Miner quickstart (draft)

**Draft.** Target: public testnet netuid 582, alpha protocol, conformance evidence only
([LIMITATIONS.md](../../LIMITATIONS.md)). Nothing here registers a key, creates a wallet or
touches a chain. Wallets, hotkeys and funds are the operator's.

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

The localhost server below needs only `uv sync --locked` (no chain SDK, no test tools). Add
`--extra transport` (pins `bittensor`, `starlette`, `uvicorn`, `valkey`, `httpx`) for the
signed-HTTP endpoint and the verifier.

## Run the localhost miner server

```bash
uv run python scripts/miner_serve.py --role candidate --port 8787
```

It binds loopback only (any other `--host` is refused), loads no key and sends nothing to a chain.
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
behaviour, error codes and limits are in the docstring of `scripts/miner_serve.py`.

## Write your own method

A method is a function from one validated capsule to one differential, written from the public
contract only (`institutional_v02/contracts.py`, `canonical.py`). `miners/witness_ic.py` is a worked
example; `miners.register(class_id, method_id, fn)` registers a method. The boundary revalidates
every response against the strict models. `tests/test_separation.py` shows how Provenonce checks
that a method sees nothing beyond the public contract. `docs/runtime/reference-miner.md` describes
the transport-neutral response boundary for the v0alpha1 objects.

## Serve on testnet

1. Register your own hotkey on netuid 582 with your own wallet (operator action; not covered here).
2. Run a signed-HTTP miner endpoint behind TLS. Requests are authenticated with the SDK's
   signed-request scheme before parsing; a shared Valkey store with `noeviction` provides replay
   protection. The design is in
   [ADR-0005](../architecture/ADR-0005-signed-http-and-replay-boundary.md); the endpoint code is
   `src/sn87_provenonce/pilot/server.py`.
3. Check the validator's published expectations (deadline, 262,144-byte wire limit).

## Resources

No resource numbers are published here. Local, deterministic-method timings exist only in
Provenonce's private measurement records, and they are not network, signing, TLS or production
capacity, and not model-inference cost. Measure your own engine.

## Limits

Both reference methods are Provenonce code. Each bundle also reports a matched public-contract
baseline (`public_contract_baseline`, never weighted, never on chain) and a per-method
`comparison`; on the public fixtures the reference methods show `NULL_NO_HEADROOM` (no measured
headroom over the baseline). Plain weight mode, no commit-reveal. Do not expect scores to rank
competing methods yet. Validator scoring is private ([README](../../README.md)).
