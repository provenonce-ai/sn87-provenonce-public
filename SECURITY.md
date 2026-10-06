# Security policy

SN87 is alpha protocol software, deployed only on public testnet netuid 582 as conformance
evidence. Do not submit production credentials, wallet material, private keys, raw Tenant
Evidence, hidden challenge truth, customer data, or vulnerability details through public channels.

Report suspected vulnerabilities privately to Provenonce through an authorized company channel.
Include the affected commit, reproducible conditions, expected impact, and the minimum Evidence
needed to verify the report. Do not include unrelated sensitive material.

Handling: reports are acknowledged and fixed privately before any public detail is shared.
Private reporting address: ops@provenonce.co.

In scope: canonicalization and wire-rule bypasses, integrity-predicate or scoring errors that
change a recorded row, replay or signature handling in the signed transport, evidence-filesystem
boundary escapes, and secrets committed by mistake. Out of scope: findings that need access to
private custody, wallets or operator hosts, which this repository does not contain.

Supported versions: only the current development branch of the alpha release (`0.1.0a0`); it
receives no security backports. No version is supported for mainnet or consequential use.
