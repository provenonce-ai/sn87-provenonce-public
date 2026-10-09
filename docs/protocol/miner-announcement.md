# Miner endpoint announcement and discovery

**Status.** The record format, signing, verification and selection are implemented and tested
(`src/sn87_provenonce/miner_node/announcement.py`, `tests/transport/test_miner_announcement.py`).
The rule below is the specification a validator follows to find an outside miner. A validator-side
reader that applies it is not part of this repository. Nothing here claims that any uid on
testnet 582 publishes an endpoint.

How a miner applies for the shadow cohort with a signed announcement is in
[shadow-cohort.md](../guides/shadow-cohort.md).

Alpha, testnet only ([LIMITATIONS.md](../../LIMITATIONS.md)).

The signed endpoint (`POST /v1/assurance`, `btauth/1`, see
[ADR-0005](../architecture/ADR-0005-signed-http-and-replay-boundary.md)) answers anyone who can
sign a request, so a validator needs to know where a miner's endpoint is. A hotkey on the
metagraph says who the miner is, not where it listens. This document defines how a miner says
where, and how a validator decides to believe it.

## What a miner publishes

One record, signed by the miner's own hotkey (sr25519). Canonical JSON (`gra/0.1`), at most 4,096
bytes:

```text
{
  "announcement": {
    "schema_version": "sn87-miner-announcement/0.1",
    "netuid":         <integer, 0 to 65535>,
    "hotkey":         "<SS58 address of the miner hotkey>",
    "endpoint":       "https://<host>[:<port>]",
    "transport":      "gra-transport/0.1",
    "sequence":       <non-negative integer, increases with every new record>,
    "issued_at_ms":   <integer, Unix milliseconds>,
    "expires_at_ms":  <integer, Unix milliseconds>
  },
  "signature": { "crypto": "sr25519", "signer": "<same SS58 address>", "value": "0x<64 bytes hex>" }
}
```

* The signature covers the bytes `sn87-miner-announcement/0.1`, a NUL byte, then the canonical
  bytes of the `announcement` object. The prefix keeps this signature from being valid for any
  other message the same key signs.
* `endpoint` is an origin: `https`, a host, an optional port, no path, query, fragment or
  credentials, and only printable ASCII (no whitespace, control characters or backslashes). It is
  refused if the port is 0, the host is `localhost`, the host is a numeric form other than a plain
  dotted quad (a single decimal integer, or a form such as `0x7f.1`), or the host is an IP literal that is not globally
  routable (loopback, private, link-local including the cloud metadata address, multicast,
  reserved, or an IPv6 form that embeds such an IPv4 address). A host name is not resolved when a
  record is signed or verified. Plain `http` and loopback are accepted only through an explicit
  test-only parameter. The signed exchange itself requires HTTPS for any remote host
  (`pilot.client.exchange`).
* `transport` names the wire the endpoint speaks. Today that is `gra-transport/0.1`.

Create one with your own key (the key is read inside the process and never printed):

```bash
uv run sn87-miner announce --hotkey-keyfile PATH --netuid 582 \
  --endpoint https://example.invalid:8443 --valid-days 7 --out announcement.json
uv run sn87-miner verify-announcement announcement.json --netuid 582
# a validator also passes --last-sequence N --last-digest sha256:... for a hotkey it has seen
```

`sn87-miner serve --announcement announcement.json --netuid 582 ...` serves the record unchanged
at `GET /.well-known/sn87-miner-announcement.json` on the miner's own endpoint, after checking
that it verifies against the serving hotkey.

## Verification rules

`verify` accepts a record only if every check passes, and reports a stable `ANNOUNCEMENT_*` code
otherwise:

1. The record is at most 4,096 bytes, is canonical JSON, and has exactly the fields above.
2. The signature verifies under the hotkey the record names, and `signature.signer` equals that
   hotkey.
3. `netuid` equals the netuid the verifier is working on.
4. The hotkey equals the hotkey the chain lists for the uid being resolved.
5. The endpoint satisfies the endpoint rule above. This is a check on the text of the record only;
   see "Connecting" below for the check that must happen when connecting.
6. Freshness: `issued_at_ms` is not more than 5 minutes ahead of the verifier's clock;
   `expires_at_ms` is in the future; `expires_at_ms - issued_at_ms` is greater than zero and at
   most 30 days.
7. Rollback and conflict: the verifier stores, per hotkey, the accepted `sequence` and the SHA-256
   of the accepted record bytes (`Accepted`), and passes it to `verify` and `select`; the
   argument is required (`None` means the hotkey was never accepted). A lower sequence is
   `SEQUENCE_ROLLBACK`. The same sequence with different bytes is `SEQUENCE_CONFLICT`: a miner
   that changes anything signs a new record with a higher sequence. (`sn87-miner announce`
   defaults `sequence` to the issue time in milliseconds, or one more than the record named by
   `--previous` if that is larger, and refuses a sequence that does not exceed it. `--previous` is the only guard that keeps the
   sequence increasing across runs: without it the command trusts the clock. A previous sequence
   at the maximum, 2^53 - 1, gives `SEQUENCE_EXHAUSTED`.)

`select` applies these rules to every candidate record for a hotkey, ignores invalid ones, and
returns the valid record with the highest sequence together with the new `Accepted` to store. If
two valid records share the top sequence with different bytes, it returns nothing.

## The validator's discovery rule

Input: the netuid `N`, a uid `U`, the hotkey `H` the metagraph lists for `U`, and the validator's
stored `last_sequence[H]`.

1. **On-chain endpoint record, if present.** If the chain's endpoint record for `U` has a
   non-zero IP and port, fetch `http://<ip>:<port>/.well-known/sn87-miner-announcement.json`
   (`axon_fetch_url` builds the URL). The chain record is only the place to fetch from: it holds
   a raw IP and a port, no host name and no TLS information, so it cannot name the HTTPS
   endpoint by itself. Plain HTTP is acceptable for this fetch because the record is
   authenticated by its signature, not by the transport. `fetch.fetch_announcement` does the
   fetch: it connects only to a globally routable IP address (a name is resolved and every
   address must pass), reads at most 4,096 bytes, applies connect and total timeouts, refuses
   every redirect, ignores proxy settings and sends no credentials or cookies. Its tests run
   against a local server, which the function accepts only through an explicit test-only
   parameter.
2. **Signed announcement from an intake, otherwise.** If step 1 has no record or its fetch
   fails, use the signed records the validator operator has configured as an intake (for example
   a directory of announcement files). The intake is operator policy; the records are verified
   the same way.
3. **Verify.** Run every candidate through the verification rules with `netuid=N`,
   `expected_hotkey=H` and `min_sequence=last_sequence[H]`. Use `select` to pick one. Store its
   `sequence` as the new `last_sequence[H]`.
4. **Use.** Send the signed exchange to the record's `endpoint`, never to the chain address. A
   response counts only if it verifies under `H` (`pilot.client.verify_response`), as it does for
   any miner.

   *Connecting.* A host name can be re-pointed after a record was signed, so the validator calls
   `fetch.safe_connect_target(endpoint)` every time it connects and connects to the returned IP
   address, not to the name; every resolved address must be globally routable. The signed
   exchange client (`pilot.client.exchange`) checks only the scheme and the loopback exception,
   not the address class, so a validator that uses it directly must resolve and check first.
5. **Refresh.** Cache the record until `expires_at_ms`; fetch again before that, at an interval
   the validator chooses, and whenever the exchange fails to connect.
6. **No valid record.** The uid has no endpoint this round and is not queried. What that means
   for weights is a validator policy matter and is not defined here.
7. **Re-registration.** The record binds the hotkey, not the uid. If the hotkey for `U` changes,
   discard the stored record and the stored sequence and start again from step 1.

What the signature proves and does not prove: the holder of `H` signed this endpoint; it does not
prove the endpoint host is operated by that holder (the exchange does, because the response must
be signed by `H`). A miner can announce any public origin, so a validator sends at most one bounded,
fixed-size signed request per round to it and never follows redirects. Internal addresses are
refused by the endpoint rule and again at connect time. The record gives no
availability or latency guarantee.

## Publishing the on-chain endpoint record

The optional on-chain record is a chain write: the miner's hotkey signs a
`SubtensorModule.serve_axon` extrinsic, which stores an IP address, a port and a few small
fields against the hotkey's uid. Requirements: the hotkey is registered on the netuid, the
account can pay the transaction fee, and the chain's serving rate limit allows it. The call
carries no host name, scheme or certificate, so it can name an endpoint only by IP address and
port; the HTTPS origin still comes from the signed announcement (step 1 above).

Nothing in this repository submits that extrinsic. `sn87-miner announce --axon-dry-run` prints
the parameters it would use, labelled `NOT SENT`, and
`tests/transport/test_miner_announcement.py` checks that the parameter names equal the pinned
SDK's `serve_axon` parameters. Whether `version` and `protocol` need other values is for the
operator to confirm against the SDK and the chain before any submission. Submitting is an
operator action with the operator's own wallet; the rules in [AGENTS.md](../../AGENTS.md) forbid
chain actions from this repository without approval from Provenonce.

## Open decisions

These are for the maintainers and are not settled by this document:

1. Which route is supported on testnet 582: the on-chain endpoint record plus the well-known
   announcement (steps 1 and 3), the off-chain intake alone (steps 2 and 3), or both as
   written.
2. Whether Provenonce publishes on-chain endpoint records for the uids it operates (a chain
   write).
3. Where an off-chain intake lives (for example a reviewed directory in this repository, or a
   hosted file) and who may add to it.
4. The validator-side reader and its policy for uids with no valid record.
