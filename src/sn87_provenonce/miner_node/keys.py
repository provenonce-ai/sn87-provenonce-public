"""Load the miner's signing key inside the process. Never prints, logs or returns key text.

Two sources, chosen by the operator: a key file PATH, or the NAME of an environment variable.
The key is read once, only here, and handed to the signer. Errors carry a stable code and
never the file contents, the variable value, or the underlying library message.

Accepted key text (file contents or variable value):

* a Bittensor wallet hotkey file as written by the SDK (unencrypted JSON), or
* a 32-byte seed as ``0x`` plus 64 hex digits, or
* a BIP-39 style mnemonic of 12, 15, 18, 21 or 24 words.

An encrypted key file is refused: decrypt it into a file only you can read, or supply the
seed or mnemonic through an environment variable. A key file readable by group or other
(POSIX mode bits 077) is refused.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

SEED_RE = re.compile(r"0x[0-9a-fA-F]{64}")
MNEMONIC_WORDS = {12, 15, 18, 21, 24}
MAX_KEY_BYTES = 8192


class HotkeyError(Exception):
    """A stable code only (``HOTKEY_*``); never key material or library text."""


def _parse(data: bytes) -> Any:
    from bittensor import sp_core  # lazy: the base install has no chain SDK

    if not data.strip() or len(data) > MAX_KEY_BYTES:
        raise HotkeyError("HOTKEY_FORMAT_UNRECOGNIZED")
    try:
        if sp_core.keyfile_data_is_encrypted(data):
            raise HotkeyError("HOTKEY_ENCRYPTED")
    except HotkeyError:
        raise
    except Exception:
        pass  # not recognisable as a keyfile blob; try the plain text forms
    text = data.strip()
    try:
        if text.startswith(b"{"):
            keypair = sp_core.deserialize_keypair_from_keyfile_data(text)
        else:
            phrase = text.decode()
            if SEED_RE.fullmatch(phrase):
                keypair = sp_core.Keypair.create_from_seed(phrase)
            elif len(phrase.split()) in MNEMONIC_WORDS:
                keypair = sp_core.Keypair.create_from_mnemonic(" ".join(phrase.split()))
            else:
                raise HotkeyError("HOTKEY_FORMAT_UNRECOGNIZED")
    except HotkeyError:
        raise
    except Exception:
        raise HotkeyError("HOTKEY_FORMAT_UNRECOGNIZED") from None
    if keypair.crypto_type != sp_core.CRYPTO_SR25519:
        raise HotkeyError("HOTKEY_NOT_SR25519")
    return keypair


def load_hotkey(*, keyfile: str | None = None, env: str | None = None) -> Any:
    """Return the signing keypair from exactly one of ``keyfile`` (a path) or ``env`` (a name)."""
    if (keyfile is None) == (env is None):
        raise HotkeyError("HOTKEY_SOURCE_REQUIRED")
    if env is not None:
        value = os.environ.get(env)
        if not value:
            raise HotkeyError("HOTKEY_ENV_UNSET")
        return _parse(value.encode())
    path = Path(keyfile).expanduser()
    try:
        info = os.stat(path)
    except OSError:
        raise HotkeyError("HOTKEY_FILE_UNREADABLE") from None
    if not stat.S_ISREG(info.st_mode):
        raise HotkeyError("HOTKEY_FILE_NOT_REGULAR")
    if os.name == "posix" and info.st_mode & 0o077:
        raise HotkeyError("HOTKEY_FILE_PERMISSIONS_TOO_OPEN")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_KEY_BYTES + 1)
    except OSError:
        raise HotkeyError("HOTKEY_FILE_UNREADABLE") from None
    return _parse(data)
