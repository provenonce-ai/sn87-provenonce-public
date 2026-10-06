"""The FICTIONAL source fixture is reproducible from its committed generator."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "src" / "sn87_provenonce" / "sources" / "fixtures"


def test_generator_reproduces_committed_fixture(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_fictional_source.py"),
                    str(tmp_path)], check=True)
    for name in ("fictional_launch_approvals.json", "fictional_launch_permission.json"):
        assert (tmp_path / name).read_bytes() == (FIXTURES / name).read_bytes()
