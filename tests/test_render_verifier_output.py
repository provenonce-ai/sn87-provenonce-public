"""The verifier output shown in the READMEs is generated, and its offline lines cannot drift."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("render_verifier_output_test",
                                                  ROOT / "scripts/render_verifier_output.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rvo = _load()


def test_both_readmes_carry_the_block_and_its_offline_lines_are_current(capsys):
    assert rvo.main(["--check"]) == 0
    assert "current" in capsys.readouterr().out
    for path in rvo.TARGETS:
        block = rvo.current_block(path)
        assert block is not None and "(generated)" not in block


def test_a_drifted_block_is_detected(tmp_path, monkeypatch, capsys):
    stale = tmp_path / "README.md"
    original = rvo.TARGETS[0].read_text(encoding="utf-8")
    stale.write_text(original.replace("validator  PASS", "validator  FAIL"), encoding="utf-8")
    monkeypatch.setattr(rvo, "TARGETS", [stale])
    assert rvo.main(["--check"]) == 1
    assert "STALE" in capsys.readouterr().err


def test_the_block_reports_what_a_public_run_reports():
    block = rvo.current_block(rvo.TARGETS[0])
    assert "validator  PASS" in block and "plan       UNVERIFIED" in block
    assert "OVERALL UNVERIFIED" in block and "exit code 3" in block
