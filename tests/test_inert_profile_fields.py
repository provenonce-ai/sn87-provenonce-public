"""Guard for the inert profile fields ``rule_reliability`` and ``deterministic``.

Both fields are part of each committed profile and so of its commitment, but no scorer code
reads them (issues #57 and #58). If code starts reading one, this test fails until the change
has been reviewed: activating a field needs a decision by Provenonce and a new profile version.
"""

import ast
import json
from pathlib import Path

import pytest

from sn87_provenonce import profile
from sn87_provenonce.profile import REGISTRY, Profile

INERT = ("rule_reliability", "deterministic")
SRC = Path(profile.__file__).parent

# The single sanctioned site: ``Profile.truth_fields`` in profile.py names each field once as
# a document read (a string constant) and once as a dict key of what it returns. The reference
# truth emitters never name the fields; they splice in ``profile.truth_fields()`` (issue #71).
# Any other use fails the test.
ACCESSOR = "profile.py"
ACCESSOR_USES = 2  # document.get(name) and the returned dict key


def _uses(path: Path, name: str):
    """Yield (line, kind) for every syntactic use of ``name`` in one module."""
    tree = ast.parse(path.read_text("utf-8"))
    dict_keys = {id(k) for n in ast.walk(tree) if isinstance(n, ast.Dict)
                 for k in n.keys if k is not None}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == name:
            yield node.lineno, "dict-key" if id(node) in dict_keys else "string"
        elif isinstance(node, ast.Attribute) and node.attr == name:
            yield node.lineno, "attribute"
        elif isinstance(node, ast.Name) and node.id == name:
            yield node.lineno, "name"
        elif isinstance(node, ast.keyword) and node.arg == name:
            yield node.value.lineno, "keyword"
        elif isinstance(node, ast.arg) and node.arg == name:
            yield node.lineno, "argument"


@pytest.mark.parametrize("name", INERT)
def test_no_source_reads_the_inert_field(name):
    offenders, accessor = [], 0
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        for line, kind in _uses(path, name):
            if rel == ACCESSOR and kind in ("string", "dict-key"):
                accessor += 1
            else:
                offenders.append(f"{rel}:{line} ({kind})")
    assert not offenders, (
        f"{name} is reserved and inert; new use needs review: {offenders}"
    )
    assert accessor == ACCESSOR_USES, f"accessor sites changed for {name}: {accessor}"


@pytest.mark.parametrize("name", INERT)
def test_only_the_committed_profile_documents_carry_the_field(name):
    """Outside .py files, the name appears only in the committed profile JSON documents."""
    carriers = sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*")
                      if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in p.parts
                      and name in p.read_bytes().decode("utf-8", "ignore") and p.suffix != ".py")
    assert carriers == sorted(f"profiles/{pid}.json" for pid in REGISTRY)


@pytest.mark.parametrize("profile_id", sorted(REGISTRY))
@pytest.mark.parametrize("name", INERT)
def test_inert_field_is_bound_by_the_profile_commitment(profile_id, name):
    """Changing the value changes the commitment; done in memory on a copy, never on disk."""
    class_id, domain, pinned = REGISTRY[profile_id]
    document = json.loads((SRC / "profiles" / f"{profile_id}.json").read_text("utf-8"))
    assert name in document
    base = Profile.from_document(document, class_id=class_id, domain=domain)
    assert base.commitment == pinned
    changed = dict(document)
    changed[name] = (not document[name]) if isinstance(document[name], bool) else "0"
    assert changed[name] != document[name]
    moved = Profile.from_document(changed, class_id=class_id, domain=domain)
    assert moved.commitment != base.commitment
    # The profile still loads and its operative parameters are untouched: the field has no effect.
    for attr in ("weights", "epsilon", "theta", "gamma", "tail", "minimum", "invalid_ceiling",
                 "severity", "false_positive_floor", "coefficients"):
        assert getattr(moved, attr) == getattr(base, attr)
