"""Registered task classes. A new family is a new binding, never a new scorer.

Both bound classes are under common Provenonce control: their methods are the two reference
algorithms that also establish truth (role "reference"), so their rows are conformance
evidence, not method competition. Each class also binds a
matched public-contract baseline (``baselines``), which is evaluated beside them. The public
generators here are deterministic fixtures; sealed runs bind private generators.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial

from sn87_provenonce import profile
from sn87_provenonce.baselines import BASELINES
from sn87_provenonce.institutional_v02 import contracts as ic
from sn87_provenonce.institutional_v02.fixtures import build_case
from sn87_provenonce.pilot import contracts as tc
from sn87_provenonce.private_executors import PrivateReferenceExecutorUnavailable
from sn87_provenonce.scoring import ClassBinding
from sn87_provenonce.simulation.type_c import FIXTURES

_TYPE_C_PUBLIC = {
    "clean": "type-c-clean-control",
    "missing_gate": "type-c-missing-review",
    "order": "type-c-validation-before-submit",
    "continuity": "type-c-chain-break",
    "incomplete": "type-c-insufficient-evidence",
    "equivalent": "type-c-missing-review-equivalent-observation",
}


def _type_c_fixture(family: str, index: int) -> dict:
    fixture = next(f for f in FIXTURES if f.fixture_id == _TYPE_C_PUBLIC[family])
    return tc.capsule_from_fixture(fixture, qid=f"{fixture.fixture_id}-{index:03d}")


def _ic_fixture(family: str, index: int) -> dict:
    counter = iter(range(1_000))
    return build_case(family, identifier=lambda: f"fx-{family}-{index:03d}-{next(counter):03d}")


def _ic_executor():
    """The private IC executor, imported at the call that needs it (never at module import)."""
    try:
        from sn87_provenonce.institutional_v02 import references
    except ImportError as exc:
        raise PrivateReferenceExecutorUnavailable from exc
    return references


def _tc_executor():
    """The private Type C executor, imported at the call that needs it."""
    try:
        from sn87_provenonce.pilot import reference
    except ImportError as exc:
        raise PrivateReferenceExecutorUnavailable from exc
    return reference


def _agreed_truth(executor, capsule: dict) -> dict:
    return executor().agreed_truth(capsule)


def _bind(module, executor, profile_id: str, generate) -> ClassBinding:
    bound = profile.load(profile_id)
    return ClassBinding(
        class_id=bound.class_id,
        profile=bound,
        schema={"TYPE-C-RELEASE": "gra/0.1"}.get(bound.class_id, "institution/0.2"),
        validate_capsule=module.validate_capsule,
        validate_differential=module.validate_differential,
        defect_severity=module.DEFECT_SEVERITY,
        reference=partial(_agreed_truth, executor),
        candidates={m: partial(_method, executor, m) for m in ("state_machine", "relational")},
        generate=generate,
        baseline=BASELINES[bound.class_id],
    )


def _method(executor, method: str, capsule: dict) -> dict:
    return executor().make_differential(capsule, method)


TYPE_C_RELEASE = _bind(tc, _tc_executor, "GRA-W03-3", _type_c_fixture)
IC_APPROVAL_APPLICABILITY = _bind(ic, _ic_executor, "IC-FIRST-LIGHT-MIN-1", _ic_fixture)
BINDINGS = {b.class_id: b for b in (TYPE_C_RELEASE, IC_APPROVAL_APPLICABILITY)}


def with_candidates(binding: ClassBinding, methods: dict) -> ClassBinding:
    """The binding plus miner-owned methods, role "candidate"; the references are untouched.

    The preference row then covers references and candidates alike (no uid until assigned).
    """
    if set(methods) & set(binding.candidates):
        raise ValueError("candidate method id collides with a bound method")
    return replace(binding, candidates=binding.candidates | methods,
                   roles=binding.roles | dict.fromkeys(methods, "candidate"))
