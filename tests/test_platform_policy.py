"""Native-Windows behaviour, simulated: no ``pwd``, no ``resource``, no ``O_NOFOLLOW``.

The import path of the public verifier must not fail at import time on such a platform, and the
fail-closed evidence controls must name the platform policy. Windows cannot be run here, so the
facilities are removed in a subprocess before anything is imported.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from sn87_provenonce import evidence_filesystem

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SIMULATE = textwrap.dedent(
    """
    import os, sys
    for name in ("pwd", "resource", "fcntl", "grp", "termios"):
        sys.modules[name] = None  # import raises ImportError, as on native Windows
    for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK"):
        if hasattr(os, flag):
            delattr(os, flag)
    sys.path.insert(0, {scripts!r})
    """
)


def _run(body: str) -> subprocess.CompletedProcess[str]:
    code = SIMULATE.format(scripts=str(ROOT / "scripts")) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=False,
    )


def test_public_verifier_imports_without_posix_modules():
    result = _run(
        """
        import verify_attestation, chain_read
        import sn87_provenonce.cli, sn87_provenonce.bundle
        import sn87_provenonce.evidence_filesystem
        print("imported")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout


def test_fake_home_check_refuses_with_policy_when_pwd_is_missing():
    result = _run(
        """
        import verify_attestation as va
        try:
            va.require_fake_home({"HOME": "/scratch"})
        except va.VerifyRefused as error:
            print("REFUSED", error)
        """
    )
    assert result.returncode == 0, result.stderr
    assert "REFUSED" in result.stdout
    assert "native Windows is unsupported" in result.stdout
    assert "WSL2" in result.stdout


def test_fake_home_check_with_explicit_real_home_needs_no_pwd():
    result = _run(
        """
        import verify_attestation as va
        va.require_fake_home({"HOME": "/scratch"}, real_home="/home/someone")
        print("ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_evidence_controls_fail_closed_without_posix_flags():
    result = _run(
        """
        from sn87_provenonce import evidence_filesystem as fs
        for call in (fs.directory_open_flags, fs.file_safety_flags):
            try:
                call(error_type=ValueError)
            except ValueError as error:
                print("CLOSED", error)
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("CLOSED") == 2
    assert result.stdout.count("unsupported on this platform") == 2


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX flags absent on this platform")
def test_flags_are_returned_where_supported():
    assert evidence_filesystem.directory_open_flags(error_type=ValueError) & os.O_NOFOLLOW
    assert evidence_filesystem.file_safety_flags(error_type=ValueError) & os.O_NOFOLLOW


def test_policy_text_states_supported_platforms():
    import verify_attestation as va

    assert "Linux and macOS" in va.PLATFORM_POLICY
    assert "WSL2" in va.PLATFORM_POLICY


def test_real_home_matches_pwd_where_available():
    import verify_attestation as va

    pwd = pytest.importorskip("pwd")
    assert va._real_home() == pwd.getpwuid(os.getuid()).pw_dir
