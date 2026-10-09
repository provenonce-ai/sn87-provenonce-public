"""``fetch_announcement`` and ``safe_connect_target``: the guards are code. A local test server
on loopback is used, which the functions accept only through the explicit test-only parameter."""

from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from transport_support import dotted, throwaway_key

from sn87_provenonce.miner_node import announcement as ann
from sn87_provenonce.miner_node import fetch

PUBLIC = dotted(93, 184, 216, 34)


class Server:
    def __init__(self, behaviour):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):  # noqa: N802
                outer.seen.append({"path": self.path, "headers": dict(self.headers)})
                behaviour(self)

        self.seen = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve():
    servers = []

    def start(behaviour):
        servers.append(Server(behaviour))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def ok(body):
    def behave(h):
        h.send_response(200)
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)
    return behave


def get(server, path=ann.WELL_KNOWN_PATH, **kwargs):
    return fetch.fetch_announcement(server.url + path, allow_loopback=True, **kwargs)


def test_fetch_returns_the_body_and_sends_no_credentials_or_cookies(serve):
    server = serve(ok(b'{"x":1}'))
    assert get(server) == b'{"x":1}'
    headers = {k.lower() for k in server.seen[0]["headers"]}
    assert headers == {"host", "connection", "accept", "accept-encoding", "user-agent"}


def test_fetch_refuses_loopback_unless_the_test_parameter_is_given(serve):
    server = serve(ok(b"{}"))
    with pytest.raises(fetch.FetchError, match="URL_INVALID|ADDRESS_NOT_GLOBAL"):
        fetch.fetch_announcement(server.url + "/x")
    assert server.seen == []


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_fetch_never_follows_a_redirect(serve, status):
    target = serve(ok(b"{}"))

    def redirect(h):
        h.send_response(status)
        h.send_header("Location", target.url + "/x")
        h.send_header("Content-Length", "0")
        h.end_headers()

    with pytest.raises(fetch.FetchError, match="REDIRECT_REFUSED"):
        get(serve(redirect))
    assert target.seen == []


def test_fetch_caps_the_body_at_the_record_limit(serve):
    exact = b"a" * ann.MAX_RECORD_BYTES
    assert get(serve(ok(exact))) == exact
    with pytest.raises(fetch.FetchError, match="TOO_LARGE"):
        get(serve(ok(exact + b"a")))

    def endless(h):
        h.send_response(200)
        h.end_headers()
        try:
            for _ in range(1000):
                h.wfile.write(b"x" * 1024)
        except OSError:
            pass

    with pytest.raises(fetch.FetchError, match="TOO_LARGE"):
        get(serve(endless))


def test_fetch_refuses_a_non_200_and_times_out_on_a_stalled_server(serve):
    def missing(h):
        h.send_response(404)
        h.send_header("Content-Length", "0")
        h.end_headers()

    with pytest.raises(fetch.FetchError, match="STATUS_REFUSED"):
        get(serve(missing))

    def stall(h):
        time.sleep(2)

    started = time.monotonic()
    with pytest.raises(fetch.FetchError, match="TIMEOUT"):
        get(serve(stall), connect_timeout=0.3, total_timeout=1.0)
    assert time.monotonic() - started < 1.9


def drip(h, chunks, pause=0.25):
    try:
        for chunk in chunks:
            h.wfile.write(chunk)
            h.wfile.flush()
            time.sleep(pause)
    except OSError:
        pass


def test_one_deadline_covers_a_slow_drip_of_headers_and_of_the_body(serve):
    def slow_headers(h):
        # never ends the header block; every read succeeds, so only a whole-exchange deadline
        # can stop it
        drip(h, [b"HTTP/1.1 200 OK\r\n"] + [b"X-Slow: a\r\n"] * 200)

    def slow_body(h):
        drip(h, [b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n"] + [b"x"] * 100)

    for behaviour in (slow_headers, slow_body):
        started = time.monotonic()
        with pytest.raises(fetch.FetchError, match="TIMEOUT"):
            get(serve(behaviour), connect_timeout=2.0, total_timeout=1.5)
        assert time.monotonic() - started < 3.0


def test_fetch_refuses_a_closed_port_and_bad_urls():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(fetch.FetchError, match="CONNECT_FAILED"):
        fetch.fetch_announcement(f"http://127.0.0.1:{port}/x", allow_loopback=True)
    for url in ("ftp://example.invalid/x", "https:" + "//user:pw" + chr(64) + "example.invalid/x"):
        with pytest.raises(fetch.FetchError, match="URL_INVALID"):
            fetch.fetch_announcement(url)


def test_plain_http_is_for_global_ip_literals_only():
    for url in (f"http://{dotted(10, 0, 0, 5)}:8091/x", f"http://{dotted(169, 254, 169, 254)}/x",
                "http://[::1]:8091/x"):
        with pytest.raises(fetch.FetchError, match="ADDRESS_NOT_GLOBAL"):
            fetch.fetch_announcement(url)
    with pytest.raises(fetch.FetchError, match="URL_INVALID"):
        fetch.fetch_announcement("http://example.invalid/x")  # a name needs https


def resolver(*addresses):
    def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]
    return resolve


def test_a_resolver_returning_something_that_is_not_an_address_is_a_fetch_error():
    def junk(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", port))]

    with pytest.raises(fetch.FetchError, match="RESOLVE_FAILED"):
        fetch.safe_connect_target("https://example.invalid", resolver=junk)


def test_plain_http_port_zero_is_refused():
    with pytest.raises(fetch.FetchError, match="ADDRESS_NOT_GLOBAL"):
        fetch.fetch_announcement(f"http://{PUBLIC}:0/x")


def test_safe_connect_target_returns_checked_addresses_only():
    assert fetch.safe_connect_target("https://example.invalid:8443",
                                     resolver=resolver(PUBLIC)) == [(PUBLIC, 8443)]
    assert fetch.safe_connect_target("https://example.invalid",
                                     resolver=resolver(PUBLIC))[0][1] == 443
    # a name re-pointed to an internal address after signing is refused at connect time
    for bad in ("127.0.0.1", dotted(10, 1, 2, 3), dotted(169, 254, 169, 254),
                dotted(192, 168, 1, 1)):
        with pytest.raises(fetch.FetchError, match="ADDRESS_NOT_GLOBAL"):
            fetch.safe_connect_target("https://example.invalid", resolver=resolver(bad))
    # one bad address among good ones refuses the endpoint
    with pytest.raises(fetch.FetchError, match="ADDRESS_NOT_GLOBAL"):
        fetch.safe_connect_target("https://example.invalid",
                                  resolver=resolver(PUBLIC, dotted(10, 0, 0, 1)))
    with pytest.raises(fetch.FetchError, match="RESOLVE_FAILED"):
        fetch.safe_connect_target("https://example.invalid", resolver=resolver())

    def failing(*args, **kwargs):
        raise socket.gaierror

    with pytest.raises(fetch.FetchError, match="RESOLVE_FAILED"):
        fetch.safe_connect_target("https://example.invalid", resolver=failing)
    # the announced string itself is validated too
    with pytest.raises(ann.AnnouncementError, match="ENDPOINT"):
        fetch.safe_connect_target("https:" + "//localhost", resolver=resolver(PUBLIC))


def test_a_fetched_record_still_has_to_verify(serve):
    key = throwaway_key()
    now = int(time.time() * 1000)
    record = ann.sign(ann.Announcement(
        netuid=582, hotkey=key.ss58_address, endpoint="https://example.invalid", sequence=1,
        issued_at_ms=now, expires_at_ms=now + 3_600_000), key)
    body = get(serve(ok(record)))
    result = ann.select([body], netuid=582, hotkey=key.ss58_address, now_ms=now,
                        last_accepted=None)
    assert result is not None and result[0].endpoint == "https://example.invalid"


# --- HTTPS: certificate validation stays on; one deadline covers handshake, headers, body ------

CERT_CONFIG = """[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = 127.0.0.1
[v3]
subjectAltName = IP:127.0.0.1
"""


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory):
    """A throwaway self-signed certificate for 127.0.0.1, made by the openssl command line tool
    in a temporary directory. No network; nothing outside the test uses it."""
    import os
    import shutil
    import subprocess

    openssl = shutil.which("openssl")
    if openssl is None:
        if os.environ.get("SN87_REQUIRE_TRANSPORT_TESTS"):
            pytest.fail("openssl is needed for the TLS fetch tests")
        pytest.skip("openssl is needed to make a throwaway certificate for the TLS fetch tests")
    directory = tmp_path_factory.mktemp("tls")
    (directory / "req.cnf").write_text(CERT_CONFIG)
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-keyout", str(directory / "server.pem"), "-out", str(directory / "cert.pem"),
                    "-config", str(directory / "req.cnf")], check=True, capture_output=True)
    return directory / "cert.pem", directory / "server.pem"


class TlsServer:
    """A loopback TLS server whose behaviour gets the connected, handshaken SSL socket."""

    def __init__(self, tls_material, behaviour, handshake_delay=0.0):
        import ssl

        cert, key = tls_material
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.client_context = ssl.create_default_context(cafile=str(cert))
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.url = f"https://127.0.0.1:{self.sock.getsockname()[1]}"
        self.behaviour, self.delay, self.closed = behaviour, handshake_delay, False
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while not self.closed:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        try:
            time.sleep(self.delay)
            tls = self.context.wrap_socket(conn, server_side=True)
            tls.recv(4096)
            self.behaviour(tls)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.closed = True
        self.sock.close()


@pytest.fixture
def tls_serve(tls_material):
    servers = []

    def start(behaviour, handshake_delay=0.0):
        servers.append(TlsServer(tls_material, behaviour, handshake_delay))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def tls_get(server, **kwargs):
    return fetch.fetch_announcement(server.url + ann.WELL_KNOWN_PATH, allow_loopback=True,
                                    ssl_context=server.client_context, **kwargs)


def tls_drip(tls, chunks, pause=0.25):
    try:
        for chunk in chunks:
            tls.sendall(chunk)
            time.sleep(pause)
    except OSError:
        pass


def test_https_fetch_works_with_a_trusted_certificate(tls_serve):
    body = b'{"x":1}'
    server = tls_serve(lambda tls: tls.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\n" + body))
    assert tls_get(server) == body


def test_https_certificate_validation_is_on_by_default(tls_serve):
    import ssl

    server = tls_serve(lambda tls: tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"))
    # production call: no injected context, so the self-signed certificate must be refused
    with pytest.raises(fetch.FetchError, match="CONNECT_FAILED"):
        fetch.fetch_announcement(server.url + "/x", allow_loopback=True)
    context = ssl.create_default_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


def test_one_deadline_covers_a_slow_tls_handshake_headers_and_body(tls_serve):
    def slow_headers(tls):
        tls_drip(tls, [b"HTTP/1.1 200 OK\r\n"] + [b"X-Slow: a\r\n"] * 200)

    def slow_body(tls):
        tls_drip(tls, [b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n"] + [b"x"] * 100)

    cases = [(slow_headers, 0.0), (slow_body, 0.0), (slow_body, 30.0)]  # last: stalled handshake
    for behaviour, delay in cases:
        started = time.monotonic()
        with pytest.raises(fetch.FetchError, match="TIMEOUT"):
            tls_get(tls_serve(behaviour, delay), connect_timeout=2.0, total_timeout=1.5)
        assert time.monotonic() - started < 3.0
