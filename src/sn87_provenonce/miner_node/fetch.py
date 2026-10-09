"""Fetching an announcement, and the address check for connecting to an announced endpoint.

Standard library only. These are the guards a validator applies; they are code here so they are
tested, not only described. Nothing is sent to a chain. Loopback is refused unless a caller passes
``allow_loopback=True``, which exists for local tests.
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from .announcement import MAX_RECORD_BYTES, AnnouncementError, is_global_address, validate_endpoint

Resolver = Callable[..., list]
CONNECT_TIMEOUT = 3.0
TOTAL_TIMEOUT = 8.0


class FetchError(AnnouncementError):
    """A stable ``ANNOUNCEMENT_FETCH_*`` code; never a body, header or library message."""


def _fail(code: str) -> FetchError:
    return FetchError("ANNOUNCEMENT_FETCH_" + code)


def safe_connect_target(
    endpoint: str, *, allow_loopback: bool = False, resolver: Resolver | None = None,
) -> list[tuple[str, int]]:
    """Resolve the announced endpoint and return ``(ip, port)`` pairs that are safe to connect
    to. Call this at connect time, every time: a name can be re-pointed after the record was
    signed (DNS rebinding). Connect to the returned IP, not to the name. Every resolved address
    must be globally routable; one bad address refuses the whole endpoint."""
    validate_endpoint(endpoint, allow_loopback=allow_loopback)
    url = urlsplit(endpoint)
    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        infos = (resolver or socket.getaddrinfo)(url.hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        raise _fail("RESOLVE_FAILED") from None
    targets: list[tuple[str, int]] = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        except (ValueError, IndexError, TypeError):
            raise _fail("RESOLVE_FAILED") from None
        loopback = ip.is_loopback and allow_loopback
        if not loopback and not is_global_address(ip):
            raise _fail("ADDRESS_NOT_GLOBAL")
        targets.append((str(ip), port))
    if not targets:
        raise _fail("RESOLVE_FAILED")
    return targets


def fetch_announcement(
    url: str, *, allow_loopback: bool = False, resolver: Resolver | None = None,
    connect_timeout: float = CONNECT_TIMEOUT, total_timeout: float = TOTAL_TIMEOUT,
    ssl_context: ssl.SSLContext | None = None,
) -> bytes:
    """GET ``url`` and return at most ``MAX_RECORD_BYTES`` of body. No redirect is followed (any
    3xx is refused), no credentials, cookies or proxy settings are sent or read, the connection
    goes to a checked global IP address, and the whole exchange has a deadline. The returned
    bytes are untrusted until ``announcement.verify`` accepts them.

    HTTPS verifies the certificate and host name with the system trust store
    (``ssl.create_default_context``). ``ssl_context`` exists only so tests can trust a throwaway
    local certificate; production callers leave it ``None``."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        raise _fail("URL_INVALID")
    origin = f"{parts.scheme}://{parts.netloc}"
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    try:
        if parts.scheme == "http" and not allow_loopback:
            targets = _plain_http_targets(parts)
        else:
            targets = safe_connect_target(origin, allow_loopback=allow_loopback,
                                          resolver=resolver)
    except FetchError:
        raise
    except AnnouncementError:
        raise _fail("URL_INVALID") from None
    deadline = time.monotonic() + total_timeout
    ip, port = targets[0]
    conn = None
    current: list[socket.socket] = []  # the socket abort() shuts down (the TLS one once wrapped)
    expired = threading.Event()

    def abort() -> None:
        """One monotonic deadline for the whole exchange: when it passes, the socket is shut
        down, which interrupts a blocked connect-phase read, TLS handshake, header read or body
        read however slowly the peer drips bytes."""
        expired.set()
        for sock in current:
            with contextlib.suppress(OSError):
                # the base-class call, so a TLS socket is shut at the OS level without
                # touching SSL state that another thread is using
                socket.socket.shutdown(sock, socket.SHUT_RDWR)

    timer = threading.Timer(total_timeout, abort)
    timer.daemon = True
    timer.start()
    try:
        raw = socket.create_connection(
            (ip, port), timeout=max(0.05, min(connect_timeout, deadline - time.monotonic())))
        current.append(raw)
        if expired.is_set():
            raise _fail("TIMEOUT")
        raw.settimeout(max(0.05, deadline - time.monotonic()))
        sock = raw
        if parts.scheme == "https":
            context = ssl_context or ssl.create_default_context()
            sock = context.wrap_socket(raw, server_hostname=parts.hostname,
                                       do_handshake_on_connect=False)
            current.append(sock)  # wrap_socket detached raw: shut the live socket as well
            sock.settimeout(max(0.05, deadline - time.monotonic()))
            sock.do_handshake()
        conn = http.client.HTTPConnection(parts.hostname, port, timeout=total_timeout)
        conn.sock = sock
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        conn.request("GET", target, headers={"Host": parts.netloc, "Connection": "close",
                                             "Accept": "application/json",
                                             "User-Agent": "sn87-announcement-fetch/0.1"})
        response = conn.getresponse()
        if 300 <= response.status < 400:
            raise _fail("REDIRECT_REFUSED")
        if response.status != 200:
            raise _fail("STATUS_REFUSED")
        body = b""
        while len(body) <= MAX_RECORD_BYTES:
            if time.monotonic() > deadline:
                raise _fail("TIMEOUT")
            chunk = response.read(min(1024, MAX_RECORD_BYTES + 1 - len(body)))
            if not chunk:
                break
            body += chunk
        if expired.is_set():
            raise _fail("TIMEOUT")
        if len(body) > MAX_RECORD_BYTES:
            raise _fail("TOO_LARGE")
        return body
    except FetchError:
        raise
    except TimeoutError:
        raise _fail("TIMEOUT") from None
    except (OSError, http.client.HTTPException, ssl.SSLError):
        raise _fail("TIMEOUT" if expired.is_set() else "CONNECT_FAILED") from None
    finally:
        timer.cancel()
        if conn is not None:
            conn.close()
        else:
            for sock in current:
                with contextlib.suppress(OSError):
                    sock.close()


def _plain_http_targets(parts) -> list[tuple[str, int]]:
    """Plain HTTP is allowed only for the chain-address fetch, where the host is a global IP
    literal; the record is authenticated by its signature, not by the transport."""
    try:
        ip = ipaddress.ip_address(parts.hostname or "")
        port = 80 if parts.port is None else parts.port
    except ValueError:
        raise _fail("URL_INVALID") from None
    if not is_global_address(ip) or port == 0:
        raise _fail("ADDRESS_NOT_GLOBAL")
    return [(str(ip), port)]
