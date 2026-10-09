"""Signed miner endpoint announcement: a pure data and signature object.

A miner publishes one record that says where its signed endpoint is, signed by the miner's
own hotkey (sr25519). Anyone can verify it from the hotkey address alone. Nothing here sends
anything anywhere: no network call, no chain call, no key file. The rule for how a validator
finds and trusts these records is in ``docs/protocol/miner-announcement.md``.

``serve_axon_dry_run`` only builds the parameters of the optional on-chain endpoint record and
labels them NOT SENT. This module has no code path that submits it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sn87_provenonce.canonical import canonical_bytes, parse_canonical

SCHEMA = "sn87-miner-announcement/0.1"
TRANSPORT = "gra-transport/0.1"  # the version string of pilot.transport.VERSION
DOMAIN = SCHEMA.encode() + b"\x00"  # domain separation for the signed bytes
WELL_KNOWN_PATH = "/.well-known/sn87-miner-announcement.json"
MAX_RECORD_BYTES = 4096
MAX_VALIDITY_MS = 30 * 24 * 3600 * 1000
MAX_FUTURE_SKEW_MS = 5 * 60 * 1000
FIELDS = {"schema_version", "netuid", "hotkey", "endpoint", "transport", "sequence",
          "issued_at_ms", "expires_at_ms"}


class AnnouncementError(ValueError):
    """A stable ``ANNOUNCEMENT_*`` code; never record text."""


def _fail(code: str) -> AnnouncementError:
    return AnnouncementError("ANNOUNCEMENT_" + code)


@dataclass(frozen=True)
class Announcement:
    netuid: int
    hotkey: str
    endpoint: str
    sequence: int
    issued_at_ms: int
    expires_at_ms: int
    transport: str = TRANSPORT

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA, "netuid": self.netuid, "hotkey": self.hotkey,
            "endpoint": self.endpoint, "transport": self.transport,
            "sequence": self.sequence, "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
        }


_PRINTABLE = re.compile(r"[\x21-\x7e]+")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_NAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_NUMERIC_LABEL = re.compile(r"(?:0x[0-9a-f]*|[0-9]+)")


def is_global_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Globally routable only: not loopback, private, link-local (which includes the cloud
    metadata address), multicast, reserved or unspecified, and, for an IPv6 address that embeds
    an IPv4 address (mapped, NAT64, 6to4), the embedded address must be global too."""
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        embedded = address.ipv4_mapped
        if embedded is None and address in ipaddress.ip_network("64:ff9b::/96"):
            embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        if embedded is None and address in ipaddress.ip_network("2002::/16"):
            embedded = ipaddress.IPv4Address((int(address) >> 80) & 0xFFFFFFFF)
        if embedded is not None and not is_global_address(embedded):
            return False
    return True


def validate_endpoint(endpoint: Any, *, allow_loopback: bool = False) -> str:
    """The endpoint is an origin: ``https://<host>[:<port>]``. Refused: any character outside
    printable ASCII (so no whitespace, control characters or backslashes), a path, query,
    fragment or credentials, port 0, ``localhost``, a numeric host that is not a plain dotted
    quad (``2130706433``, ``0x7f.1``), and an IP literal that is not globally routable
    (loopback, private, link-local including the metadata address, multicast, reserved).
    A host name is not resolved here; the validator must check the resolved address again when
    it connects (``fetch.safe_connect_target``), because a name can be re-pointed.

    ``allow_loopback`` is for local tests only: it accepts ``http`` and ``https`` to a loopback
    host or ``localhost``."""
    if (not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 253
            or _PRINTABLE.fullmatch(endpoint) is None or "\\" in endpoint):
        raise _fail("ENDPOINT_INVALID")
    if endpoint != endpoint.lower() or endpoint.rstrip("/").endswith(":"):
        raise _fail("ENDPOINT_INVALID")  # lower case only; no empty port
    try:
        url = urlsplit(endpoint)
        host, port = url.hostname, url.port
    except ValueError:
        raise _fail("ENDPOINT_INVALID") from None
    if (not host or url.path not in {"", "/"} or url.query or url.fragment
            or url.username or url.password or port == 0 or "%" in host):
        raise _fail("ENDPOINT_INVALID")
    loopback = False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
        if _NAME.fullmatch(host) is None or _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]):
            raise _fail("ENDPOINT_INVALID") from None
        loopback = host == "localhost" or host.endswith(".localhost")
    else:
        if "." in host and host.count(".") != 3 and address.version == 4:
            raise _fail("ENDPOINT_INVALID")
        loopback = address.is_loopback
    if loopback and not allow_loopback:
        raise _fail("ENDPOINT_NOT_GLOBAL")
    if address is not None and not loopback and not is_global_address(address):
        raise _fail("ENDPOINT_NOT_GLOBAL")
    if url.scheme == "https" or (url.scheme == "http" and allow_loopback and loopback):
        return endpoint.rstrip("/")
    raise _fail("ENDPOINT_NOT_HTTPS")


def _check_fields(a: Announcement, *, allow_loopback: bool = False) -> None:
    for name in ("netuid", "sequence", "issued_at_ms", "expires_at_ms"):
        value = getattr(a, name)
        if type(value) is not int or not 0 <= value <= 2**53 - 1:
            raise _fail("FIELD_INVALID")
    if a.netuid > 65535:  # u16 on chain
        raise _fail("FIELD_INVALID")
    if not isinstance(a.hotkey, str) or not a.hotkey or a.transport != TRANSPORT:
        raise _fail("FIELD_INVALID")
    validate_endpoint(a.endpoint, allow_loopback=allow_loopback)
    if not a.issued_at_ms < a.expires_at_ms <= a.issued_at_ms + MAX_VALIDITY_MS:
        raise _fail("VALIDITY_WINDOW_INVALID")


@dataclass(frozen=True)
class Accepted:
    """What a verifier stores per hotkey after accepting a record: its sequence and the SHA-256
    of the exact record bytes. Both are needed: a record with the same sequence but different
    bytes is a conflict, not a refresh."""

    sequence: int
    digest: str


def record_digest(record: bytes) -> str:
    return "sha256:" + hashlib.sha256(record).hexdigest()


def sign(announcement: Announcement, keypair: Any, *, allow_loopback: bool = False) -> bytes:
    """Return the canonical bytes of the signed record. ``keypair`` must be the hotkey named in
    the record; the signature covers ``DOMAIN`` plus the canonical bytes of the announcement."""
    from bittensor import sp_core

    _check_fields(announcement, allow_loopback=allow_loopback)
    if keypair.ss58_address != announcement.hotkey or keypair.crypto_type != sp_core.CRYPTO_SR25519:
        raise _fail("SIGNER_MISMATCH")
    body = announcement.to_dict()
    signature = bytes(keypair.sign(DOMAIN + canonical_bytes(body)))
    return canonical_bytes({
        "announcement": body,
        "signature": {"crypto": "sr25519", "signer": announcement.hotkey,
                      "value": "0x" + signature.hex()},
    }, max_bytes=MAX_RECORD_BYTES)


def verify(
    record: bytes, *, netuid: int, now_ms: int, expected_hotkey: str | None = None,
    last_accepted: Accepted | None, allow_loopback: bool = False,
) -> Announcement:
    """Verify one signed record. Raises ``AnnouncementError`` (stable code) on any failure.

    Checks, in order: size and canonical form; exact field set; signature by the hotkey the
    record names (sr25519, domain separated); ``netuid`` equals the caller's; the hotkey equals
    ``expected_hotkey`` (the hotkey the chain lists for the uid); the endpoint rule; freshness
    (not issued in the future beyond the skew, not expired, validity at most 30 days); and the
    rollback rule against ``last_accepted``, which is required (pass ``None`` only for a hotkey
    never accepted before): a lower sequence is ``SEQUENCE_ROLLBACK``, and the same sequence
    with different record bytes is ``SEQUENCE_CONFLICT``. A miner that changes anything signs a
    new record with a higher sequence."""
    from bittensor import sp_core

    if len(record) > MAX_RECORD_BYTES:
        raise _fail("TOO_LARGE")
    try:
        doc = parse_canonical(record, max_bytes=MAX_RECORD_BYTES)
    except Exception:
        raise _fail("NOT_CANONICAL") from None
    if (not isinstance(doc, dict) or set(doc) != {"announcement", "signature"}
            or not isinstance(doc["announcement"], dict) or set(doc["announcement"]) != FIELDS
            or doc["announcement"]["schema_version"] != SCHEMA
            or not isinstance(doc["signature"], dict)
            or set(doc["signature"]) != {"crypto", "signer", "value"}):
        raise _fail("SCHEMA_INVALID")
    body, sig = doc["announcement"], doc["signature"]
    a = Announcement(
        netuid=body["netuid"], hotkey=body["hotkey"], endpoint=body["endpoint"],
        sequence=body["sequence"], issued_at_ms=body["issued_at_ms"],
        expires_at_ms=body["expires_at_ms"], transport=body["transport"],
    )
    _check_fields(a, allow_loopback=allow_loopback)
    value = sig["value"]
    if (sig["crypto"] != "sr25519" or sig["signer"] != a.hotkey or not isinstance(value, str)
            or len(value) != 130 or not value.startswith("0x")):
        raise _fail("SIGNATURE_INVALID")
    try:
        raw = bytes.fromhex(value[2:])
        ok = sp_core.verify(DOMAIN + canonical_bytes(body), raw, a.hotkey)
    except Exception:
        ok = False
    if not ok:
        raise _fail("SIGNATURE_INVALID")
    if a.netuid != netuid:
        raise _fail("WRONG_NETUID")
    if expected_hotkey is not None and a.hotkey != expected_hotkey:
        raise _fail("WRONG_HOTKEY")
    if a.issued_at_ms > now_ms + MAX_FUTURE_SKEW_MS:
        raise _fail("ISSUED_IN_FUTURE")
    if a.expires_at_ms <= now_ms:
        raise _fail("EXPIRED")
    if last_accepted is not None:
        if a.sequence < last_accepted.sequence:
            raise _fail("SEQUENCE_ROLLBACK")
        if a.sequence == last_accepted.sequence and record_digest(record) != last_accepted.digest:
            raise _fail("SEQUENCE_CONFLICT")
    return a


def select(
    records: Iterable[bytes], *, netuid: int, hotkey: str, now_ms: int,
    last_accepted: Accepted | None, allow_loopback: bool = False,
) -> tuple[Announcement, Accepted] | None:
    """The record a validator should use for ``hotkey``, or ``None``. ``last_accepted`` is
    required (``None`` means this hotkey was never accepted): the validator keeps one
    ``Accepted`` per hotkey and stores the returned one. Invalid records are ignored. The valid
    record with the highest sequence wins; if two valid records share that sequence with
    different bytes, none is used (a conflict is never resolved by guessing)."""
    valid: list[tuple[Announcement, Accepted]] = []
    for record in records:
        try:
            a = verify(record, netuid=netuid, now_ms=now_ms, expected_hotkey=hotkey,
                       last_accepted=last_accepted, allow_loopback=allow_loopback)
        except AnnouncementError:
            continue
        valid.append((a, Accepted(a.sequence, record_digest(record))))
    if not valid:
        return None
    top = max(item[0].sequence for item in valid)
    best = {item[1].digest: item for item in valid if item[0].sequence == top}
    return next(iter(best.values())) if len(best) == 1 else None


def axon_fetch_url(ip: int, port: int, ip_type: int) -> str:
    """Where to fetch the announcement for an on-chain axon record (``ip`` as the chain's u128).
    Refuses loopback, private, link-local, multicast and other non-global addresses so a record
    on chain cannot point the validator at its own network. Plain ``http`` is acceptable for
    this fetch: the record is authenticated by its signature, not by the transport."""
    if ip_type not in {4, 6} or not 1 <= port <= 65535:
        raise _fail("AXON_INVALID")
    try:
        address = (ipaddress.IPv4Address(ip) if ip_type == 4 else ipaddress.IPv6Address(ip))
    except ValueError:
        raise _fail("AXON_INVALID") from None
    if not is_global_address(address):
        raise _fail("AXON_NOT_GLOBAL")
    host = f"[{address}]" if ip_type == 6 else str(address)
    return f"http://{host}:{port}{WELL_KNOWN_PATH}"


def serve_axon_dry_run(announcement: Announcement, *, version: int = 0, protocol: int = 4) -> dict:
    """The parameters the miner's own hotkey would submit in a ``SubtensorModule.serve_axon``
    extrinsic to publish an on-chain endpoint. DRY RUN: this returns data and sends nothing.

    The extrinsic carries a raw IP address (u128) and a port, not a host name or a scheme, so
    it can only be built when the announced endpoint host is an IP literal. ``version`` and
    ``protocol`` are passed through for the operator to confirm against the SDK before any
    real submission; this repository never makes that submission."""
    url = urlsplit(announcement.endpoint)
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        address = ipaddress.ip_address(url.hostname or "")
    except ValueError:
        return {"status": "NOT SENT", "buildable": False,
                "reason": "the announced host is a name; serve_axon carries an IP address only",
                "call": "SubtensorModule.serve_axon"}
    return {
        "status": "NOT SENT", "buildable": True, "call": "SubtensorModule.serve_axon",
        "signed_by": announcement.hotkey,
        "params": {
            "netuid": announcement.netuid, "version": version, "ip": int(address),
            "port": port, "ip_type": address.version, "protocol": protocol,
            "placeholder1": 0, "placeholder2": 0,
        },
    }
