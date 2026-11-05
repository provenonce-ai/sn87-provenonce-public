"""Closed, per-family baseline lists for the weight gate.

A family registers once, before its test, the complete set of methods a candidate must beat and
the minimum effect its preregistration states. The gate takes the set from here, never from the
caller: a caller that leaves a registered method out is refused (``registered_gate`` in
``bundle``). A registration is closed: registering the same family again with anything different
raises, so a method cannot be quietly added or dropped afterwards. Registering only records the
lists; it binds nothing and sets no weight.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyBaselines:
    methods: tuple[str, ...]  # every method the candidate must beat, ablations included
    min_effect: float         # the preregistered minimum lead, applied beside the gate's margin


_REGISTRY: dict[str, FamilyBaselines] = {}


def register(class_id: str, methods: tuple[str, ...] | list[str], min_effect: float) -> None:
    entry = FamilyBaselines(tuple(sorted(set(methods))), float(min_effect))
    if not entry.methods or len(entry.methods) != len(list(methods)):
        raise ValueError("a registration lists each method once and at least one")
    if not 0.0 <= entry.min_effect < 1.0:
        raise ValueError("minimum effect must be in [0, 1)")
    if _REGISTRY.setdefault(class_id, entry) != entry:
        raise ValueError(f"baseline list of {class_id!r} is closed and differs")


def registered(class_id: str) -> FamilyBaselines | None:
    return _REGISTRY.get(class_id)
