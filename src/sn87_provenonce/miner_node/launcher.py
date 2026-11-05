"""``sn87-miner``: serve one miner method behind the signed endpoint, or sign an announcement.

  sn87-miner serve --role candidate --hotkey-env SN87_HOTKEY --netuid N \\
      --valkey-url redis://127.0.0.1:6379/0 [--probe-hotkey SS58]
  sn87-miner serve --role candidate --hotkey-keyfile PATH --netuid N \\
      --valkey-url-env SN87_VALKEY_URL --check
  sn87-miner serve --allow-any-sender --role candidate ...               # local development only
  sn87-miner serve --unsigned-loopback --role candidate --port 8787     # local development only
  sn87-miner announce --hotkey-env SN87_HOTKEY --netuid N --endpoint <https-origin>
  sn87-miner verify-announcement FILE --netuid N [--hotkey SS58]
  sn87-miner probe --endpoint URL --miner-hotkey SS58 --valkey-url URL \\
      [--probe-hotkey-keyfile PATH | --probe-hotkey-env NAME]            # self-test an endpoint

``serve`` runs ``pilot.server.create_app``: ``POST /v1/assurance`` authenticated with the
SDK's ``btauth/1`` envelope over the exact request bytes, a shared replay store (Valkey) that
fails closed, and a signed response. ``GET /ready`` reports the replay store. Only senders that
hold ``validator_permit`` on ``--netuid`` (read from the chain, read-only, once per epoch), or the
one ``--probe-hotkey`` the operator names, are accepted, behind a global rate limit; the opt-out
is ``--allow-any-sender`` (local and development use, logged). The method is
``--role candidate|baseline`` (the reference methods) or ``--method package.module:function``
(your own: one capsule dict in, one differential dict out).

No subcommand writes to a chain: nothing here registers a key, sets weights, publishes an
on-chain endpoint or reads a wallet by name. The sender allowlist makes read-only storage
queries. The signing key is read only inside this process,
from a file path or an environment variable name, and is never printed or logged.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sn87_provenonce.pilot import sender_policy as sp

from . import announcement as ann
from .core import ROLES, MethodError, MinerCore, StagingError
from .keys import HotkeyError, load_hotkey

DEFAULT_PORT = 8787
VALKEY_SCHEMES = {"redis", "rediss", "unix"}
TESTNET_NETUID = 582   # the netuid the built-in chain endpoint and genesis hash belong to
BANNER = "SN87 MINER: signed endpoint (btauth/1), no chain writes"


class ConfigError(Exception):
    """A configuration problem; the message is a stable code plus non-secret detail."""


def redact_url(url: str) -> str:
    """Scheme, host, port and path only: credentials and query never reach any output."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}{parts.path}"


def is_loopback(host: str) -> bool:
    """True only if the host is a loopback address, or ``localhost`` and EVERY address it
    resolves to is loopback (an unresolvable name is not loopback)."""
    if host == "localhost":
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        addresses = {info[4][0].split("%")[0] for info in infos}
        try:
            return bool(addresses) and all(ipaddress.ip_address(a).is_loopback
                                           for a in addresses)
        except ValueError:
            return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _source(value: str | None, env_name: str | None, label: str) -> str:
    if (value is None) == (env_name is None):
        raise ConfigError(f"{label}_SOURCE_REQUIRED: give exactly one of the two flags")
    if env_name is not None:
        found = os.environ.get(env_name)
        if not found:
            raise ConfigError(f"{label}_ENV_UNSET")
        return found
    assert value is not None
    return value


def build_core(args: argparse.Namespace) -> MinerCore:
    try:
        return MinerCore.from_role(args.role) if args.role else MinerCore.from_path(args.method)
    except (StagingError, MethodError) as error:
        raise ConfigError(str(error)) from None


def check_store_url(url: str) -> None:
    """Stable codes for a bad store URL; the URL itself is never echoed."""
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        raise ConfigError("VALKEY_URL_INVALID") from None
    if parts.scheme not in VALKEY_SCHEMES:
        raise ConfigError("VALKEY_URL_SCHEME_INVALID: use redis://, rediss:// or unix://")


def build_store(valkey_url: str, receiver: str) -> Any:
    from .transport_glue import make_store

    check_store_url(valkey_url)
    try:
        return make_store(valkey_url, receiver)
    except (ValueError, TypeError):
        raise ConfigError("VALKEY_URL_INVALID") from None


def probe_store(store: Any) -> str:
    """Read-only: PING and the eviction policy. Returns ``ok`` or a stable code."""
    from .transport_glue import probe

    return probe(store)


def build_signed_app(
    core: MinerCore, keypair: Any, store: Any, *, sender_policy: Any, max_inflight: int = 8,
    announcement_record: bytes | None = None,
) -> Any:
    """The Starlette app: ``create_app`` plus, optionally, the signed announcement served
    verbatim at the well-known path. ``sender_policy`` is required: a ``SenderPolicy`` (the
    default for ``serve``) or the explicit ``AllowAnySender`` opt-out."""
    from .transport_glue import make_app

    return make_app(core.handle, keypair, store, max_inflight=max_inflight,
                    announcement_record=announcement_record, sender_policy=sender_policy)


def valid_ss58(address: str) -> bool:
    """True for a well-formed SS58 address in the canonical form the SDK produces."""
    from bittensor import sp_core

    try:
        return bool(sp_core.ss58_encode(sp_core.ss58_decode(address), 42) == address)
    except Exception:  # noqa: BLE001 - any parse failure means not valid
        return False


def build_permit_provider(args: argparse.Namespace) -> Any:
    """The production snapshot source: a read-only chain read. Tests replace this."""
    from .transport_glue import (
        DEFAULT_CHAIN_ENDPOINT,
        DEFAULT_CHAIN_GENESIS,
        make_permit_provider,
    )

    if bool(args.chain_endpoint) != bool(args.chain_genesis):
        raise ConfigError("CHAIN_GENESIS_REQUIRED: give --chain-endpoint and --chain-genesis "
                          "together")
    if not args.chain_endpoint and args.netuid != TESTNET_NETUID:
        raise ConfigError("CHAIN_GENESIS_REQUIRED: the built-in chain is the testnet (netuid "
                          f"{TESTNET_NETUID}); for netuid {args.netuid} give --chain-endpoint "
                          "and --chain-genesis")
    return make_permit_provider(args.chain_endpoint or DEFAULT_CHAIN_ENDPOINT,
                                args.chain_genesis or DEFAULT_CHAIN_GENESIS)


def build_sender_policy(args: argparse.Namespace) -> Any:
    """The sender policy for ``serve``: the permit allowlist unless ``--allow-any-sender``."""
    try:
        if args.allow_any_sender:
            conflicting = [name for name, value in (
                ("--probe-hotkey", args.probe_hotkey),
                ("--trusted-sender", args.trusted_sender or None),
                ("--chain-endpoint", args.chain_endpoint),
                ("--chain-genesis", args.chain_genesis),
                ("--sender-refresh-seconds", args.sender_refresh_seconds)) if value is not None]
            if conflicting:
                raise ConfigError("SENDER_POLICY_FLAGS_CONFLICT: " + ", ".join(conflicting)
                                  + " mean nothing with --allow-any-sender")
            if not is_loopback(args.host):
                raise ConfigError("ALLOW_ANY_SENDER_NON_LOOPBACK: --allow-any-sender is for "
                                  "local development; bind a loopback --host")
            print("WARNING: --allow-any-sender: the sender allowlist is OFF; any key with a valid "
                  "signature may send. Local and development use only.", file=sys.stderr)
            return sp.AllowAnySender(rate_per_second=args.global_rate_per_second,
                                     burst=args.global_rate_burst)
        if args.netuid is None:
            raise ConfigError("NETUID_REQUIRED: the sender allowlist needs --netuid "
                              "(or --allow-any-sender for local development)")
        if args.probe_hotkey is not None and not valid_ss58(args.probe_hotkey):
            raise ConfigError("PROBE_HOTKEY_INVALID: --probe-hotkey is not an SS58 address")
        trusted = tuple(dict.fromkeys(args.trusted_sender or []))
        for address in trusted:
            if not valid_ss58(address):
                raise ConfigError("TRUSTED_SENDER_INVALID: --trusted-sender is not an SS58 "
                                  "address")
        refresh = (args.sender_refresh_seconds if args.sender_refresh_seconds is not None
                   else sp.DEFAULT_REFRESH_SECONDS)
        config = sp.SenderPolicyConfig(
            netuid=args.netuid, refresh_seconds=refresh, probe_hotkey=args.probe_hotkey,
            trusted_senders=trusted,
            rate_per_second=args.global_rate_per_second, burst=args.global_rate_burst,
            sender_rate_per_second=args.sender_rate_per_second,
            sender_burst=args.sender_rate_burst)
    except ValueError as error:
        raise ConfigError("SENDER_POLICY_INVALID: " + str(error)) from None
    return sp.SenderPolicy(build_permit_provider(args), config)


def _load_announcement(path: str, keypair: Any, netuid: int | None) -> bytes:
    if netuid is None:
        raise ConfigError("NETUID_REQUIRED: --announcement needs --netuid")
    try:
        record = Path(path).read_bytes()
    except OSError:
        raise ConfigError("ANNOUNCEMENT_FILE_UNREADABLE") from None
    try:
        ann.verify(record, netuid=netuid, now_ms=time.time_ns() // 1_000_000,
                   expected_hotkey=keypair.ss58_address, last_accepted=None,
                   allow_loopback=True)
    except ann.AnnouncementError as error:
        raise ConfigError(str(error)) from None
    return record


def serve_command(args: argparse.Namespace) -> int:
    if args.unsigned_loopback:
        return serve_unsigned(args)
    if not args.role and not args.method:
        raise ConfigError("METHOD_REQUIRED: give --role candidate|baseline or --method module:fn")
    if not 1 <= args.port <= 65535:
        raise ConfigError("PORT_INVALID")
    if not is_loopback(args.host) and not args.allow_non_loopback:
        raise ConfigError(f"NON_LOOPBACK_HOST_REFUSED: {args.host} (add --allow-non-loopback; "
                          "terminate TLS in front of this process)")
    if not 1 <= args.max_inflight <= 64:
        raise ConfigError("MAX_INFLIGHT_INVALID: 1 to 64")
    core = build_core(args)
    try:
        keypair = load_hotkey(keyfile=args.hotkey_keyfile, env=args.hotkey_env)
    except HotkeyError as error:
        raise ConfigError(str(error)) from None
    receiver = keypair.ss58_address
    valkey_url = _source(args.valkey_url, args.valkey_url_env, "VALKEY_URL")
    store = build_store(valkey_url, receiver)
    record = (_load_announcement(args.announcement, keypair, args.netuid)
              if args.announcement else None)
    policy = build_sender_policy(args)
    try:
        policy.load()
    except sp.SnapshotError as error:
        raise ConfigError(f"SENDER_SNAPSHOT_FAILED: {error}") from None
    if getattr(policy, "snapshot_size", None) == 0:
        print("WARNING: no hotkey holds validator_permit on this netuid (or the wrong chain or "
              "netuid was given): every sender except the probe key will be refused.",
              file=sys.stderr)
    app = build_signed_app(core, keypair, store, sender_policy=policy,
                           max_inflight=args.max_inflight, announcement_record=record)
    lines = [
        BANNER,
        f"method: {core.label} ({core.method_id})",
        f"hotkey: {receiver}",
        f"listen: http://{args.host}:{args.port}  POST /v1/assurance  GET /ready"
        + (f"  GET {ann.WELL_KNOWN_PATH}" if record else ""),
        f"replay store: {redact_url(valkey_url)} (credentials not shown)",
    ]
    lines.append(policy.describe())
    if core.cmt_commitment:
        lines.append(f"cmt: {core.cmt_commitment}")
    if not is_loopback(args.host):
        lines.append("warning: plain HTTP on a non-loopback address; terminate TLS in front")
    if args.check:
        status = probe_store(store)
        lines.append(f"replay store check: {status}")
        print("\n".join(["CONFIGURATION CHECK ONLY (nothing was started)", *lines]), flush=True)
        if status != "ok":
            print(f"MINER REFUSED: {status}", file=sys.stderr)
            return 2
        print("check: OK", flush=True)
        return 0
    print("\n".join(lines), flush=True)
    import signal

    import uvicorn

    # uvicorn stops gracefully on SIGTERM/SIGINT, then re-raises the signal to the handler it
    # found. A no-op handler (and a caught KeyboardInterrupt) turns that into a normal exit 0.
    signal.signal(signal.SIGTERM, lambda *_: None)
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False,
                    limit_concurrency=16, timeout_keep_alive=2)
    return 0


def serve_unsigned(args: argparse.Namespace) -> int:
    """Development mode: the unsigned loopback server (no key, no replay store, no signature)."""
    from . import loopback

    extra = [name for name, value in (
        ("--hotkey-keyfile", args.hotkey_keyfile), ("--hotkey-env", args.hotkey_env),
        ("--valkey-url", args.valkey_url), ("--valkey-url-env", args.valkey_url_env),
        ("--announcement", args.announcement), ("--method", args.method),
    ) if value]
    if extra:
        raise ConfigError("UNSIGNED_LOOPBACK_TAKES_NO: " + ", ".join(extra))
    if not args.role:
        raise ConfigError("METHOD_REQUIRED: --unsigned-loopback needs --role candidate|baseline")
    print(f"{loopback.LABEL}: the validator wire is `sn87-miner serve` without "
          "--unsigned-loopback", file=sys.stderr)
    if args.check:
        try:
            loopback.require_loopback(args.host)
            MinerCore.from_role(args.role)
        except (loopback.RefusedHost, StagingError) as error:
            raise ConfigError(str(error)) from None
        print("check: OK (unsigned loopback configuration)", flush=True)
        return 0
    return loopback.main(["--role", args.role, "--port", str(args.port), "--host", args.host])


def _announce_keypair(args: argparse.Namespace) -> Any:
    try:
        return load_hotkey(keyfile=args.hotkey_keyfile, env=args.hotkey_env)
    except HotkeyError as error:
        raise ConfigError(str(error)) from None


def _previous_sequence(args: argparse.Namespace, hotkey: str) -> int:
    """The sequence of the announcement this one replaces (``--previous FILE``), or -1. The file
    must name the same hotkey and netuid; it is read for its sequence only, not trusted."""
    if not args.previous:
        return -1
    try:
        body = json.loads(Path(args.previous).read_bytes())["announcement"]
        sequence = body["sequence"]
        if body["hotkey"] != hotkey or body["netuid"] != args.netuid or type(sequence) is not int:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise ConfigError("PREVIOUS_ANNOUNCEMENT_INVALID") from None
    return sequence


def announce_command(args: argparse.Namespace) -> int:
    keypair = _announce_keypair(args)
    now_ms = args.issued_at_ms if args.issued_at_ms is not None else time.time_ns() // 1_000_000
    last = _previous_sequence(args, keypair.ss58_address)
    sequence = args.sequence if args.sequence is not None else max(now_ms, last + 1)
    if sequence <= last:
        raise ConfigError(f"SEQUENCE_NOT_INCREASING: must be greater than {last}")
    if sequence > 2**53 - 1:
        raise ConfigError("SEQUENCE_EXHAUSTED: the previous sequence is at the maximum")
    record = ann.Announcement(
        netuid=args.netuid, hotkey=keypair.ss58_address, endpoint=args.endpoint,
        sequence=sequence, issued_at_ms=now_ms,
        expires_at_ms=now_ms + int(args.valid_days * 24 * 3600 * 1000),
    )
    try:
        signed = ann.sign(record, keypair, allow_loopback=args.allow_loopback_endpoint)
    except ann.AnnouncementError as error:
        raise ConfigError(str(error)) from None
    if args.out:
        try:
            with open(args.out, "xb") as stream:
                stream.write(signed)
        except OSError as error:
            raise ConfigError(f"OUTPUT_NOT_WRITTEN: {type(error).__name__}") from None
        print(f"wrote signed announcement ({len(signed)} bytes) to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(signed.decode() + "\n")
    print(f"hotkey={record.hotkey} netuid={record.netuid} sequence={record.sequence} "
          f"expires_at_ms={record.expires_at_ms}", file=sys.stderr)
    if args.axon_dry_run:
        print("ON-CHAIN ENDPOINT RECORD, DRY RUN (a chain write; this command never sends it):",
              file=sys.stderr)
        print(json.dumps(ann.serve_axon_dry_run(record), indent=2, sort_keys=True),
              file=sys.stderr)
    return 0


def verify_command(args: argparse.Namespace) -> int:
    last = (ann.Accepted(args.last_sequence, args.last_digest)
            if args.last_sequence is not None and args.last_digest else None)
    try:
        record = Path(args.file).read_bytes()
        a = ann.verify(record, netuid=args.netuid, now_ms=time.time_ns() // 1_000_000,
                       expected_hotkey=args.hotkey, last_accepted=last,
                       allow_loopback=args.allow_loopback_endpoint)
    except OSError:
        raise ConfigError("ANNOUNCEMENT_FILE_UNREADABLE") from None
    except ann.AnnouncementError as error:
        raise ConfigError(str(error)) from None
    print(f"announcement OK: hotkey={a.hotkey} netuid={a.netuid} endpoint={a.endpoint} "
          f"sequence={a.sequence} expires_at_ms={a.expires_at_ms}")
    return 0


def probe_command(args: argparse.Namespace) -> int:
    """Send one signed fixture request to a running endpoint from a throwaway caller key."""
    from .transport_glue import probe_exchange

    url = _source(args.valkey_url, args.valkey_url_env, "VALKEY_URL")
    check_store_url(url)
    caller = None
    if args.probe_hotkey_keyfile or args.probe_hotkey_env:
        try:
            caller = load_hotkey(keyfile=args.probe_hotkey_keyfile, env=args.probe_hotkey_env)
        except HotkeyError as error:
            raise ConfigError(str(error)) from None
    try:
        differential = probe_exchange(args.endpoint, args.miner_hotkey, url, caller=caller)
    except Exception as error:  # noqa: BLE001 - report a stable code, never a message
        from sn87_provenonce.pilot.transport import BoundaryError

        detail = str(error) if isinstance(error, BoundaryError) else type(error).__name__
        raise ConfigError(f"PROBE_FAILED: {detail}") from None
    codes = [finding["code"] for finding in differential.get("findings", [])]
    print(f"probe OK: signed request answered and verified; state={differential['state']} "
          f"findings={codes}")
    return 0


def _hotkey_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--hotkey-keyfile", metavar="PATH",
                   help="path to the hotkey key file (mode 0600; never printed)")
    p.add_argument("--hotkey-env", metavar="NAME",
                   help="NAME of an environment variable holding the hotkey seed, mnemonic or "
                        "key file JSON (the variable's value is never printed)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sn87-miner", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="serve a miner method behind the signed endpoint")
    group = s.add_mutually_exclusive_group()
    group.add_argument("--role", choices=sorted(ROLES), help="a reference method")
    group.add_argument("--method", metavar="MODULE:FUNCTION",
                       help="your own method: one capsule dict in, one differential dict out")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--allow-non-loopback", action="store_true",
                   help="bind a non-loopback host (put TLS in front of it)")
    _hotkey_flags(s)
    s.add_argument("--valkey-url", metavar="URL", help="replay store URL (credentials not shown)")
    s.add_argument("--valkey-url-env", metavar="NAME",
                   help="NAME of an environment variable holding the replay store URL")
    s.add_argument("--max-inflight", type=int, default=8)
    s.add_argument("--announcement", metavar="FILE",
                   help=f"signed announcement served at {ann.WELL_KNOWN_PATH}")
    s.add_argument("--netuid", type=int,
                   help="the subnet whose validator_permit holders may send (required unless "
                        "--allow-any-sender); also the netuid an --announcement must name")
    s.add_argument("--allow-any-sender", action="store_true",
                   help="DEVELOPMENT ONLY: turn the sender allowlist off, so any key with a "
                        "valid signature may send (the global rate limit stays). Logged.")
    s.add_argument("--trusted-sender", metavar="SS58", action="append",
                   help="a hotkey that may send without validator_permit (repeat for more; at "
                        f"most {sp.MAX_TRUSTED_SENDERS} with --probe-hotkey): the probe key, or "
                        "the address of a shadow service. It skips only the permit check, is "
                        "still rate limited, and is listed at start-up")
    s.add_argument("--probe-hotkey", metavar="SS58",
                   help="the key you use with `sn87-miner probe`: the same as one "
                        "--trusted-sender")
    s.add_argument("--sender-refresh-seconds", type=float, metavar="S",
                   help=f"re-read the permit list this often (default "
                        f"{sp.DEFAULT_REFRESH_SECONDS:g} = one epoch at tempo 360; "
                        f"{sp.MIN_REFRESH_SECONDS:g} to {sp.MAX_REFRESH_SECONDS:g})")
    s.add_argument("--global-rate-per-second", type=float, default=sp.DEFAULT_RATE_PER_SECOND,
                   help="requests per second all senders together may make "
                        f"(default {sp.DEFAULT_RATE_PER_SECOND:g})")
    s.add_argument("--global-rate-burst", type=int, default=sp.DEFAULT_BURST,
                   help=f"burst allowance of that limit (default {sp.DEFAULT_BURST})")
    s.add_argument("--sender-rate-per-second", type=float,
                   default=sp.DEFAULT_SENDER_RATE_PER_SECOND,
                   help="requests per second ONE sender (the probe key included) may make "
                        f"(default {sp.DEFAULT_SENDER_RATE_PER_SECOND:g})")
    s.add_argument("--sender-rate-burst", type=int, default=sp.DEFAULT_SENDER_BURST,
                   help=f"burst allowance of that limit (default {sp.DEFAULT_SENDER_BURST})")
    s.add_argument("--chain-endpoint", metavar="WSS_URL",
                   help="chain endpoint for the permit read; the built-in default is the public "
                        f"testnet and is used only for netuid {TESTNET_NETUID}; needs "
                        "--chain-genesis")
    s.add_argument("--chain-genesis", metavar="0xHASH",
                   help="genesis hash the endpoint must report before its answer is used")
    s.add_argument("--check", "--dry-run", dest="check", action="store_true",
                   help="validate the configuration, probe the replay store, exit; start nothing")
    s.add_argument("--unsigned-loopback", action="store_true",
                   help="DEVELOPMENT ONLY: serve the unsigned localhost wire (POST /cmt)")
    s.set_defaults(run=serve_command)

    a = sub.add_parser("announce", help="sign an endpoint announcement with the hotkey")
    _hotkey_flags(a)
    a.add_argument("--netuid", type=int, required=True)
    a.add_argument("--endpoint", required=True,
                   help="an https origin: scheme, host, optional port; no path")
    a.add_argument("--valid-days", type=float, default=7.0, help="at most 30")
    a.add_argument("--sequence", type=int,
                   help="default: the issue time in milliseconds, or one more than --previous "
                        "(--previous is the only guard that keeps it increasing across runs)")
    a.add_argument("--previous", metavar="FILE",
                   help="the announcement this replaces: the new sequence must exceed its own")
    a.add_argument("--issued-at-ms", type=int, help="default: now")
    a.add_argument("--out", metavar="FILE", help="write the record here (must not exist)")
    a.add_argument("--allow-loopback-endpoint", action="store_true",
                   help="accept http://127.0.0.1 style endpoints (local testing)")
    a.add_argument("--axon-dry-run", action="store_true",
                   help="also print the parameters of the on-chain endpoint record; sends nothing")
    a.set_defaults(run=announce_command)

    v = sub.add_parser("verify-announcement", help="verify a signed announcement file")
    v.add_argument("file")
    v.add_argument("--netuid", type=int, required=True)
    v.add_argument("--hotkey", help="the hotkey the chain lists for the uid")
    v.add_argument("--last-sequence", type=int,
                   help="sequence last accepted for this hotkey (with --last-digest)")
    v.add_argument("--last-digest", help="sha256:... of the record last accepted")
    v.add_argument("--allow-loopback-endpoint", action="store_true")
    v.set_defaults(run=verify_command)

    pr = sub.add_parser("probe", help="send one signed fixture request to a running endpoint")
    pr.add_argument("--endpoint", required=True, help="origin, https (http only on loopback)")
    pr.add_argument("--miner-hotkey", required=True, help="the endpoint's hotkey (SS58)")
    pr.add_argument("--valkey-url", metavar="URL", help="the caller-side replay store")
    pr.add_argument("--valkey-url-env", metavar="NAME")
    pr.add_argument("--probe-hotkey-keyfile", metavar="PATH",
                    help="the key file of the hotkey the endpoint was started with "
                         "`--probe-hotkey` (mode 0600; never printed)")
    pr.add_argument("--probe-hotkey-env", metavar="NAME",
                    help="NAME of an environment variable holding that probe key")
    pr.set_defaults(run=probe_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except ConfigError as error:
        print(f"MINER REFUSED: {error}", file=sys.stderr)
        return 2
    except ImportError:
        print("MINER REFUSED: TRANSPORT_EXTRA_MISSING: install with `uv sync --extra transport`",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
