"""The one error raised when a private reference executor is needed and absent.

The public tree ships no reference executors (``institutional_v02.references``,
``pilot.reference``, ``simulation.type_c_reference``). Public modules import them lazily, at
the call that needs one, and convert a failed import into this error.
"""

from __future__ import annotations

MESSAGE = (
    "private reference executor not available: "
    "requires the Provenonce-private reference executors"
)


class PrivateReferenceExecutorUnavailable(RuntimeError):
    """A call needs a private reference executor that is not installed."""

    def __init__(self) -> None:
        super().__init__(MESSAGE)
