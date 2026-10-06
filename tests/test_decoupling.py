"""The public tree imports without the three private reference executors.

A subprocess blocks ``institutional_v02.references``, ``pilot.reference`` and
``simulation.type_c_reference`` (``sys.modules[name] = None``), imports every package module,
every public script and the CLI, and checks that only a call that truly needs an executor
fails, with the one clear error. It runs in the full tree too: blocking simulates the export.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
MESSAGE = ("private reference executor not available: "
           "requires the Provenonce-private reference executors")

PROLOGUE = """
import sys
for name in ("sn87_provenonce.institutional_v02.references", "sn87_provenonce.pilot.reference",
             "sn87_provenonce.simulation.type_c_reference"):
    sys.modules[name] = None
"""


def _run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", PROLOGUE + body], capture_output=True,
                          text=True, cwd=ROOT, timeout=300)


def test_every_package_module_and_public_script_imports_with_executors_blocked():
    done = _run(f"""
import importlib, pathlib, pkgutil
sys.path.insert(0, {str(ROOT / "scripts")!r})
import sn87_provenonce
names = [m.name for m in pkgutil.walk_packages(sn87_provenonce.__path__, "sn87_provenonce.")
         if sys.modules.get(m.name, 0) is not None]
# every script with a __main__ guard (the others run on import) that does not import an
# executor itself (operator tooling of the private tree may), whichever tree this is
scripts = [p.stem for p in sorted(pathlib.Path({str(ROOT / "scripts")!r}).glob("*.py"))
           if "__main__" in p.read_text() and p.stem != "export_public"
           and not any(w in p.read_text() for w in ("pilot.reference", "pilot import reference",
                                                    "references", "type_c_reference"))]
for name in names + scripts:
    importlib.import_module(name)
blocked = [n for n in sys.modules if n.endswith(("institutional_v02.references",
           "pilot.reference", "simulation.type_c_reference")) and sys.modules[n] is not None]
assert not blocked, blocked
print(len(names))
""")
    assert done.returncode == 0, done.stderr
    assert int(done.stdout.strip()) > 50


def test_cli_demo_runs_and_executor_commands_fail_with_the_one_clear_error():
    done = _run("""
from sn87_provenonce.cli import main
assert main(["demo"]) == 0
assert main(["simulate-type-c-reference"]) == 1
""")
    assert done.returncode == 0, done.stderr
    assert "error: " + MESSAGE in done.stderr


def test_calls_that_need_an_executor_raise_the_dedicated_error():
    done = _run(f"""
from sn87_provenonce import classes
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable as E
from sn87_provenonce.simulation import type_c_conformance as tcc
from sn87_provenonce.simulation.type_c import FIXTURES
from sn87_provenonce.pilot.contracts import capsule_from_fixture
def must_raise(call):
    try:
        call()
    except E as error:
        assert str(error) == {MESSAGE!r} and isinstance(error, RuntimeError)
    else:
        raise AssertionError("no error")
capsule = capsule_from_fixture(FIXTURES[0])
must_raise(lambda: classes.TYPE_C_RELEASE.reference(capsule))
must_raise(lambda: classes.TYPE_C_RELEASE.candidates["relational"](capsule))
must_raise(lambda: classes.IC_APPROVAL_APPLICABILITY.reference(dict()))
must_raise(lambda: tcc.CANDIDATE_CASES)
must_raise(tcc.run_type_c_candidate_conformance)
print("ok")
""")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_pinned_reference_oracle_commitment_equals_the_executor_output():
    """The artifact module pins the oracle commitment so it imports without the executor."""
    from conftest import executors_available

    if not executors_available():
        return
    from sn87_provenonce.simulation.type_c_candidate_artifact import (
        REFERENCE_ORACLE_REPORT_COMMITMENT,
    )
    from sn87_provenonce.simulation.type_c_reference import run_type_c_simulation

    assert run_type_c_simulation()["report_commitment"] == REFERENCE_ORACLE_REPORT_COMMITMENT
