"""The hand-maintained table of items outside the evidence-bundle matrix cites real things."""

import importlib
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
DOC = (ROOT / "docs" / "protocol" / "implementation-status.md").read_text()


def rows():
    section = DOC.split("## Items outside the evidence-bundle matrix")[1]
    section = section.split("Not in the matrix")[0]
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if (line.startswith("|") and len(cells) == 5 and cells[0] != "Item"
                and not set(cells[0]) <= {"-"}):
            yield cells


def test_the_extra_table_has_the_six_items():
    assert len(list(rows())) == 6


def test_every_cited_symbol_and_test_exists():
    for item, implemented, _state, tested, deployed in rows():
        module, symbol = implemented.strip("`").split(":")
        if module.endswith(".py"):
            assert re.search(rf"def {symbol}\(", (ROOT / module).read_text()), item
        else:
            assert hasattr(importlib.import_module(module), symbol), item
        assert deployed == "no", item
        private = tested.endswith(" (private suite)")  # the file is not in the public tree
        path, _, name = tested.removesuffix(" (private suite)").strip("`").partition("::")
        path = f"tests/{path}" if private else path  # a private-suite file is named bare
        if private and not (ROOT / path).exists():
            continue
        assert (ROOT / path).exists(), item
        assert f"def {name}(" in (ROOT / path).read_text(), item
