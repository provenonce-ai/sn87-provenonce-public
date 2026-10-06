# Local validator runtime

The local validator command exercises the whitepaper-defined boundary from a typed
`AssuranceRequest` through miner-response collection and the non-compensable integrity gate.
It uses only committed public-safe vectors and explicit in-memory adapters.

```bash
uv run sn87-provenonce run-local-validator
uv run sn87-provenonce run-local-validator --output-dir ./evidence/validator-run-001
uv run sn87-provenonce verify-validator-bundle ./evidence/validator-run-001
```

The demonstration returns three integrity-passed protocol states and one integrity-failed
response solely because of its synthetic invalid-signature fact. The output states explicitly that no scoring,
weight planning, or broadcast occurred.

The output is semantically committed under the domain
`SN87:LOCAL_VALIDATOR_REPORT:v0alpha1`. The optional output-directory form writes a
create-only two-file bundle containing the report and a byte-level manifest. Verification
rejects changed bytes, a changed semantic commitment, an altered claim boundary, missing
files, unexpected entries, links, concurrent entry mutation, and directory substitution.
Reads are bounded and creation verifies through the same retained directory snapshot. An
existing destination is never replaced.

The runtime preserves target order while allowing independent exchanges to proceed
concurrently. One timeout bounds the complete transport, content-verification, and integrity
decision for each miner. A timeout, transport failure, or verification failure affects only
its own outcome. Failure messages from adapters are not copied into the result. Verifier
implementations are asynchronous and must offload CPU-bound work rather than block the event
loop.

This is not a network service. `btauth/1` is not approximated here: the future HTTP adapter
must use the pinned official `bittensor.http_auth` implementation over the exact raw request
body and must provide a shared replay store when deployed across processes or hosts.
