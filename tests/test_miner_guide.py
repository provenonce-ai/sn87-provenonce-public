"""The miner guide's troubleshooting table is built from the code, in both directions.

Every error code in the table must exist in the source, and every code the miner commands and
the signed endpoint can produce must be in the table. The codes are read from the source with
the ``ast`` module, so a code that is added, renamed or removed there fails this test until the
guide is updated. The HTTP status the guide gives for an endpoint code is checked against the
status the source sends.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "sn87_provenonce"
GUIDE = ROOT / "docs" / "guides" / "miner-guide.md"

# file -> names of the calls whose first string argument is an error code
SURFACES = {
    "miner_node/launcher.py": {"ConfigError"},
    "miner_node/keys.py": {"HotkeyError"},
    "miner_node/core.py": {"StagingError", "MethodError"},
    "miner_node/announcement.py": {"_fail"},  # codes carry the prefix ANNOUNCEMENT_
    "miner_node/fetch.py": {"_fail"},  # codes carry the prefix ANNOUNCEMENT_FETCH_
    "miner_node/loopback.py": {"RefusedHost", "_error"},
    "pilot/server.py": {"_error", "BoundaryError"},
    "pilot/transport.py": {"BoundaryError"},
    "pilot/client.py": {"BoundaryError"},
}
TOKEN = re.compile(r"[A-Z][A-Z0-9_.:]*[A-Z0-9]")


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _token(text: str) -> str | None:
    """The code at the start of an error message: ``CODE`` or ``CODE: detail``."""
    head = text.split(": ", 1)[0].strip()
    return head if TOKEN.fullmatch(head) else None


def _labels(tree: ast.AST) -> set[str]:
    """The labels given to ``_source(value, env_name, "LABEL")``: they prefix two codes."""
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and _call_name(node.func) == "_source"
                and len(node.args) == 3 and isinstance(node.args[2], ast.Constant)):
            found.add(node.args[2].value)
    return found


def _codes_of(arg: ast.expr, labels: set[str]) -> set[str]:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        token = _token(arg.value)
        return {token} if token else set()
    if isinstance(arg, ast.IfExp):
        return _codes_of(arg.body, labels) | _codes_of(arg.orelse, labels)
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        return _codes_of(arg.left, labels)
    if isinstance(arg, ast.JoinedStr) and arg.values:
        first = arg.values[0]
        if isinstance(first, ast.Constant):
            token = _token(first.value)
            return {token} if token else set()
        if (isinstance(first, ast.FormattedValue) and isinstance(first.value, ast.Name)
                and first.value.id == "label" and len(arg.values) > 1
                and isinstance(arg.values[1], ast.Constant)):
            suffix = arg.values[1].value.split(": ", 1)[0]
            return {label + suffix for label in labels}
    return set()


def source_codes() -> tuple[set[str], dict[str, set[int]]]:
    """Every error code the miner commands and the endpoint can produce, and the HTTP statuses
    the server sends with a literal ``_error("CODE", status)``."""
    codes: set[str] = set()
    statuses: dict[str, set[int]] = {}
    for rel, names in SURFACES.items():
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        labels = _labels(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _call_name(node.func) in names):
                continue
            for index, arg in enumerate(node.args):
                found = _codes_of(arg, labels)
                if not found:
                    continue
                if rel.endswith("miner_node/announcement.py"):
                    found = {"ANNOUNCEMENT_" + code for code in found}
                if rel.endswith("miner_node/fetch.py"):
                    found = {"ANNOUNCEMENT_FETCH_" + code for code in found}
                codes |= found
                if rel == "pilot/server.py" and index == 0 and len(node.args) == 2:
                    status = node.args[1]
                    if isinstance(status, ast.Constant) and isinstance(status.value, int):
                        statuses.setdefault(next(iter(found)), set()).add(status.value)
                break
    # main() prints this one directly, not through an exception
    launcher = (SRC / "miner_node/launcher.py").read_text(encoding="utf-8")
    codes |= set(re.findall(r"MINER REFUSED: ([A-Z_]+):", launcher))
    return codes, statuses


def guide_table(start: str = "## Part G.", end: str = "## Honest limits") -> dict[str, list[str]]:
    """Code -> the cells of its row, for the tables between two headings of the guide."""
    text = GUIDE.read_text(encoding="utf-8")
    part = text[text.index(start):text.index(end)]
    rows: dict[str, list[str]] = {}
    for line in part.splitlines():
        match = re.match(r"\| `([A-Z][A-Z0-9_.:]*[A-Z0-9])` \|(.*)\|\s*$", line)
        if match:
            rows[match.group(1)] = [cell.strip() for cell in match.group(2).split("|")]
    return rows


def test_every_code_in_the_guide_exists_in_the_source():
    codes, _ = source_codes()
    table = guide_table()
    assert len(table) > 60, "the table was not found"
    missing = sorted(set(table) - codes)
    assert not missing, f"codes in the guide that the source does not produce: {missing}"


def test_every_code_the_source_produces_is_in_the_guide():
    codes, _ = source_codes()
    table = guide_table()
    missing = sorted(codes - set(table))
    assert not missing, f"codes in the source that the guide does not explain: {missing}"


def test_every_endpoint_code_has_the_status_the_server_sends():
    """Literal ``_error(code, status)`` calls give their status. The codes that reach the server
    as a ``BoundaryError`` get the mapping server.py applies, which is asserted to be in its
    source: REPLAY_STORE* is 503, RATE_LIMITED 429, BODY_TOO_LARGE 413, anything else 401."""
    server = (SRC / "pilot/server.py").read_text(encoding="utf-8")
    for fragment in ('status = 503 if code.startswith("REPLAY_STORE") else 401',
                     'if code == "RATE_LIMITED":\n                status = 429',
                     'if code == "BODY_TOO_LARGE":\n                status = 413'):
        assert fragment in server, fragment
    _, statuses = source_codes()

    def expected(code: str) -> int:
        if code in statuses:
            assert len(statuses[code]) == 1, code
            return next(iter(statuses[code]))
        if code.startswith("REPLAY_STORE"):
            return 503
        return {"RATE_LIMITED": 429, "BODY_TOO_LARGE": 413}.get(code, 401)

    table = guide_table("### What the signed endpoint answers", "### What `probe`")
    assert len(table) == 23, len(table)
    for code, cells in table.items():
        assert cells[0] == str(expected(code)), (code, cells[0], expected(code))


def test_the_guide_says_the_last_step_depends_on_the_shadow_cohort_and_names_what_it_needs():
    text = GUIDE.read_text(encoding="utf-8")
    assert "**Depends on admission to the shadow cohort.**" in text
    assert "shadow-cohort.md" in text
    part = text[text.index("## Part F."):text.index("## Part G.")]
    for needed in ("admission decision", "published result for a closed window",
                   "Your uid in that record", "admission.md"):
        assert needed in part, needed
    assert "REHEARSAL ON A DEMO WINDOW" in part and "not a score, not 582" in part


def test_the_guide_has_the_parts_the_route_needs():
    text = GUIDE.read_text(encoding="utf-8")
    for heading in ("## Part A. Requirements and platform policy",
                    "## Part B. Install and run the public demo",
                    "## Part C. Write a method, serve it locally, score it",
                    "## Part D. The signed endpoint, the probe and the announcement",
                    "## Part E. Registration and test funds on 582",
                    "## Part F. The first score on 582",
                    "## Part G. Troubleshooting by error code",
                    "## Honest limits",
                    "## Part H. Report back"):
        assert heading in text, heading
    assert "NOT SENT" in text
