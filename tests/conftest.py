"""Shared skip marker for tests that need the Provenonce-private reference executors.

``@pytest.mark.requires_private_executors`` (or a module-level ``pytestmark``) skips a test
ONLY when one of the three executor modules is not importable, or when a named ops file the
test reads is absent (``requires_private_executors("scripts/evidence_bundle.py")``). In the
full private tree nothing is skipped.
"""

from importlib.util import find_spec
from pathlib import Path

import pytest

from sn87_provenonce.private_executors import MESSAGE, PrivateReferenceExecutorUnavailable

ROOT = Path(__file__).resolve().parents[1]
EXECUTORS = (
    "sn87_provenonce.institutional_v02.references",
    "sn87_provenonce.pilot.reference",
    "sn87_provenonce.simulation.type_c_reference",
)
REASON = MESSAGE


def executors_available() -> bool:
    try:
        return all(find_spec(name) is not None for name in EXECUTORS)
    except (ImportError, ValueError):  # ValueError: sys.modules[name] is None (blocked)
        return False


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_private_executors(*ops_files): skipped only when a private reference "
        "executor module (or a named ops file) is absent",
    )


def pytest_collection_modifyitems(config, items):
    present = executors_available()
    for item in items:
        marker = item.get_closest_marker("requires_private_executors")
        if marker is None:
            continue
        missing = [f for f in marker.args if not (ROOT / f).exists()]
        if not present or missing:
            reason = REASON + (f" (missing: {', '.join(missing)})" if missing else "")
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A test that reaches a missing executor is skipped with the shared reason.

    Only when an executor module is genuinely not importable (``executors_available()`` is
    false); in the full tree the same exception, e.g. from a broken executor dependency, stays
    a failure. Anything else still fails.
    """
    outcome = yield
    report = outcome.get_result()
    if (call.excinfo is not None
            and call.excinfo.errisinstance(PrivateReferenceExecutorUnavailable)
            and not executors_available()):
        report.outcome = "skipped"
        path, line, _ = item.location
        report.longrepr = (path, line + 1, f"Skipped: {REASON}")
