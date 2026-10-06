"""Import this before any private-executor import to skip the whole test module without them.

``import _requires_executors  # noqa: F401``: skips (module level) with the shared reason
only when a private reference executor module is not importable; a no-op in the full tree.
"""

import pytest
from conftest import REASON, executors_available

if not executors_available():
    pytest.skip(REASON, allow_module_level=True)
