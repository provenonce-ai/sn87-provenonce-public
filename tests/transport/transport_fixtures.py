"""Fixtures for the signed-endpoint tests (imported by the test modules in this directory;
not a conftest.py, because a second ``conftest`` module would shadow ``tests/conftest.py``).

They run in the public tree and need no private file.

A Valkey-compatible server is required for the tests that use the ``redis`` fixture. Where it
comes from, in order:

1. ``SN87_TEST_VALKEY_URL`` (for example ``redis://127.0.0.1:6379/0``): an existing server, such
   as the container service in CI. The tests use random throwaway keys, so their keys never
   collide, and they delete the keys they created. Do not point this at a server that holds
   data you care about.
2. ``valkey-server`` or ``redis-server`` on PATH: a private server on a Unix socket in a
   temporary directory, stopped at the end.
3. Neither: the tests that need a server skip, with a reason. Set ``SN87_REQUIRE_TRANSPORT_TESTS=1``
   (CI does) to turn that skip into a failure.

Test keys are generated here from fresh random mnemonics. No key is read from disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

try:
    import bittensor  # noqa: F401
    import starlette  # noqa: F401
    import valkey  # noqa: F401
except ImportError as error:  # a job that lost --all-extras must fail, not pass with no tests
    if os.environ.get("SN87_REQUIRE_TRANSPORT_TESTS"):
        raise
    pytest.skip(f"the transport extra is not installed: {error.name}", allow_module_level=True)

from transport_support import throwaway_key  # noqa: E402
from valkey import Valkey  # noqa: E402

URL_ENV = "SN87_TEST_VALKEY_URL"
REQUIRE_ENV = "SN87_REQUIRE_TRANSPORT_TESTS"
NEEDS_SERVER = ("a Valkey-compatible server is needed: set SN87_TEST_VALKEY_URL, or put "
                "valkey-server or redis-server on PATH")


def _unavailable(reason: str):
    if os.environ.get(REQUIRE_ENV):
        pytest.fail(reason + f" ({REQUIRE_ENV} is set)")
    pytest.skip(reason)


def _wait(client: Valkey) -> bool:
    for _ in range(200):
        try:
            if client.ping():
                return True
        except Exception:
            time.sleep(0.05)
    return False


@pytest.fixture(scope="session")
def valkey_url():
    """URL of a usable server, started here when none was given."""
    given = os.environ.get(URL_ENV)
    if given:
        if not _wait(Valkey.from_url(given, socket_timeout=1, socket_connect_timeout=1)):
            _unavailable(f"{URL_ENV} is set but the server did not answer PING")
        yield given
        return
    binary = shutil.which("valkey-server") or shutil.which("redis-server")
    if binary is None:
        _unavailable(NEEDS_SERVER)
    # A short path: Unix socket paths are limited to about 100 bytes.
    with tempfile.TemporaryDirectory(prefix="sn87-replay-", dir="/tmp") as directory:
        sock = Path(directory) / "store.sock"
        process = subprocess.Popen([
            binary, "--port", "0", "--unixsocket", str(sock), "--unixsocketperm", "700",
            "--save", "", "--appendonly", "no", "--dir", directory,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = "unix://" + str(sock)
        try:
            if not _wait(Valkey.from_url(url)):
                pytest.fail("replay server did not start")
            yield url
        finally:
            process.terminate()
            process.wait(timeout=5)


@pytest.fixture
def redis(valkey_url):
    """A client for the server; the keys of the throwaway receivers used are removed after."""
    client = Valkey.from_url(valkey_url, decode_responses=True)
    before = set(client.scan_iter(match="sn87:gra:replay:*", count=1000))
    yield client
    leftover = set(client.scan_iter(match="sn87:gra:replay:*", count=1000)) - before
    if leftover:
        client.delete(*leftover)


@pytest.fixture
def keys():
    """(sender, server): two fresh random sr25519 keys, used for this test only."""
    return throwaway_key(), throwaway_key()
