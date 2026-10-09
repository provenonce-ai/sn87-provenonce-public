"""Truth and reference responses for tests that must also run without the private executors.

``truth_of(binding, capsule)`` returns the reference executor's truth when the executors are
installed (the private tree) and the published golden truth otherwise (the public tree).
``response_from_truth`` builds the response a method that agrees with the truth returns, from
the truth alone. Together they let a scorer test run unchanged in both trees. In the private
tree the executor's own answer is used, so those tests keep their full strength there; the
private test ``tests/institutional_v02/test_golden_truth.py`` shows that the golden truth and
this builder agree with the executors on every published case.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from conftest import executors_available

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import golden_truth  # noqa: E402

STORE = golden_truth.load()

RATIONALE = "Response built from the published truth of this capsule."
FINDING_RATIONALE = "The truth lists this defect for this capsule."


def truth_of(binding, capsule: dict[str, Any]) -> dict[str, Any]:
    """Executor truth if available, else the published golden truth (state and defects)."""
    if executors_available():
        return binding.reference(capsule)
    return STORE.truth_for(capsule)


def response_from_truth(capsule: dict[str, Any], truth: dict[str, Any],
                        method: str = "golden") -> dict[str, Any]:
    """The differential a method returns when it reproduces ``truth`` exactly."""
    findings = [{"code": d["code"], "severity": d["severity"],
                 "evidence_refs": list(d["required_refs"]), "rationale": FINDING_RATIONALE,
                 "confidence": "1"} for d in truth["defects"]]
    return {"schema_version": capsule["schema_version"], "qid": capsule["qid"],
            "capsule_commitment": capsule["evidence_commitment"], "method": method,
            "state": truth["state"], "rationale": RATIONALE, "findings": findings}
