#!/usr/bin/env python3
"""Check the GitHub issue templates in .github/ISSUE_TEMPLATE.

Every template must parse as YAML and carry the keys GitHub requires; config.yml must disable
blank issues and offer contact links; the security template must not collect free text, so that
vulnerability details cannot be filed in a public issue.

  scripts/check_issue_templates.py [DIR]    # default: .github/ISSUE_TEMPLATE of this repository

Exit 0 when clean, 1 with one line per problem otherwise.

The check uses no third-party YAML library (the pinned dependency set stays unchanged). It reads
the block-style subset that GitHub issue forms use: nested mappings and sequences by indentation,
plain, single-quoted and double-quoted scalars, ``|`` block scalars, ``true``/``false``/``null``,
and empty ``[]``/``{}``. Anything else (tabs, flow collections with content, anchors, duplicate
keys, a plain scalar containing ``: ``) is reported as a parse error, so a template that passes
here is plain block YAML that any YAML parser reads the same way.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
REQUIRED_TEMPLATES = ("setup-failure.yml", "scoring-question.yml", "security.yml", "config.yml")
FIELD_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}
FREE_TEXT = {"input", "textarea"}
SECURITY_TEMPLATE = "security.yml"


class YamlSubsetError(ValueError):
    """The text is outside the block-style YAML subset, or is not valid in it."""


def _scalar(text: str, where: str):
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~"):
        return None
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise YamlSubsetError(f"{where}: bad double-quoted scalar") from exc
        if not isinstance(value, str):
            raise YamlSubsetError(f"{where}: bad double-quoted scalar")
        return value
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise YamlSubsetError(f"{where}: unterminated single-quoted scalar")
        body = text[1:-1]
        if "'" in body.replace("''", ""):
            raise YamlSubsetError(f"{where}: unescaped quote in single-quoted scalar")
        return body.replace("''", "'")
    if text[:1] in "[{&*!%@`>" or ": " in text or text.endswith(":") or " #" in text:
        raise YamlSubsetError(f"{where}: unsupported or ambiguous plain scalar {text!r}")
    return text


def _split_key(text: str, where: str):
    """Return (key, rest) for a ``key: rest`` entry, or None when text is not a mapping entry."""
    if text.startswith(("'", '"')):
        return None
    if text.endswith(":"):
        return text[:-1].strip(), ""
    key, sep, rest = text.partition(": ")
    if not sep or not key or key[0] in "[{":
        return None
    return key.strip(), rest.strip()


def parse_yaml_subset(source: str):
    raw = source.split("\n")
    for number, line in enumerate(raw, 1):
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise YamlSubsetError(f"line {number}: tab indentation")
    pos = [0]

    def peek():
        while pos[0] < len(raw):
            line = raw[pos[0]]
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return len(line) - len(line.lstrip()), stripped
            pos[0] += 1
        return None

    def block_scalar(parent_indent: int) -> str:
        lines = []
        while pos[0] < len(raw):
            line = raw[pos[0]]
            if line.strip() and len(line) - len(line.lstrip()) <= parent_indent:
                break
            lines.append(line)
            pos[0] += 1
        content = [ln for ln in lines if ln.strip()]
        if not content:
            return ""
        width = min(len(ln) - len(ln.lstrip()) for ln in content)
        return "\n".join(ln[width:] for ln in lines).rstrip("\n") + "\n"

    def value_after(rest: str, indent: int, where: str):
        if rest in ("|", "|-", "|+"):
            return block_scalar(indent)
        if rest:
            return _scalar(rest, where)
        nxt = peek()
        if nxt and (nxt[0] > indent or (nxt[0] == indent and nxt[1].startswith("- "))):
            return block(nxt[0])
        return None

    def block(indent: int):
        first = peek()
        if first[1] == "-" or first[1].startswith("- "):
            return sequence(indent)
        return mapping(indent)

    def sequence(indent: int):
        items = []
        while (cur := peek()) and cur[0] == indent and (cur[1] == "-" or cur[1].startswith("- ")):
            where = f"line {pos[0] + 1}"
            rest = cur[1][1:].strip()
            if _split_key(rest, where) is not None:
                raw[pos[0]] = " " * (indent + 2) + rest  # the entry starts a nested mapping
                items.append(mapping(indent + 2))
                continue
            pos[0] += 1
            items.append(value_after(rest, indent, where))
        return items

    def mapping(indent: int):
        out: dict = {}
        while (cur := peek()) and cur[0] == indent:
            where = f"line {pos[0] + 1}"
            if cur[1] == "-" or cur[1].startswith("- "):
                break
            entry = _split_key(cur[1], where)
            if entry is None:
                raise YamlSubsetError(f"{where}: expected 'key: value', got {cur[1]!r}")
            key, rest = entry
            if key in out:
                raise YamlSubsetError(f"{where}: duplicate key {key!r}")
            pos[0] += 1
            out[key] = value_after(rest, indent, where)
        return out

    first = peek()
    if first is None:
        return None
    value = block(first[0])
    if peek() is not None:
        raise YamlSubsetError(f"line {pos[0] + 1}: unexpected indentation or content")
    return value


def _load(path: Path, problems: list[str]):
    try:
        return parse_yaml_subset(path.read_text(encoding="utf-8"))
    except (YamlSubsetError, OSError, UnicodeDecodeError) as exc:
        problems.append(f"{path.name}: does not parse as YAML: {exc}")
        return None


def _check_field(name: str, index: int, item, seen: set[str], problems: list[str]) -> str | None:
    where = f"{name}: body[{index}]"
    if not isinstance(item, dict):
        problems.append(f"{where}: must be a mapping")
        return None
    kind = item.get("type")
    if kind not in FIELD_TYPES:
        problems.append(f"{where}: type {kind!r} is not one of {sorted(FIELD_TYPES)}")
        return None
    attrs = item.get("attributes")
    if not isinstance(attrs, dict):
        problems.append(f"{where}: missing attributes")
        return kind
    if kind == "markdown":
        if not str(attrs.get("value", "")).strip():
            problems.append(f"{where}: markdown needs attributes.value")
        return kind
    if not str(attrs.get("label", "")).strip():
        problems.append(f"{where}: {kind} needs attributes.label")
    ident = item.get("id")
    if not isinstance(ident, str) or not ident:
        problems.append(f"{where}: {kind} needs an id")
    elif ident in seen:
        problems.append(f"{where}: duplicate id {ident!r}")
    else:
        seen.add(ident)
    if kind in ("dropdown", "checkboxes"):
        options = attrs.get("options")
        if not isinstance(options, list) or not options:
            problems.append(f"{where}: {kind} needs a non-empty attributes.options list")
    return kind


def check_template(path: Path, problems: list[str]) -> None:
    data = _load(path, problems)
    if data is None:
        return
    name = path.name
    if not isinstance(data, dict):
        problems.append(f"{name}: top level must be a mapping")
        return
    for key in ("name", "description", "body"):
        if not data.get(key):
            problems.append(f"{name}: missing required key {key!r}")
    body = data.get("body")
    if not isinstance(body, list):
        if body:
            problems.append(f"{name}: body must be a list")
        return
    seen: set[str] = set()
    kinds = [_check_field(name, i, item, seen, problems) for i, item in enumerate(body)]
    if not any(k and k != "markdown" for k in kinds):
        problems.append(f"{name}: body needs at least one input field")
    if name == SECURITY_TEMPLATE and any(k in FREE_TEXT for k in kinds):
        problems.append(f"{name}: must not collect free text (no input or textarea)")


def check_config(path: Path, problems: list[str]) -> None:
    data = _load(path, problems)
    if data is None:
        return
    if not isinstance(data, dict):
        problems.append("config.yml: top level must be a mapping")
        return
    if data.get("blank_issues_enabled") is not False:
        problems.append("config.yml: blank_issues_enabled must be false")
    links = data.get("contact_links")
    if not isinstance(links, list) or not links:
        problems.append("config.yml: contact_links must be a non-empty list")
        return
    for i, link in enumerate(links):
        if not isinstance(link, dict) or not all(
                isinstance(link.get(k), str) and link.get(k) for k in ("name", "url", "about")):
            problems.append(f"config.yml: contact_links[{i}] needs name, url and about")
        elif not link["url"].startswith(("https://", "mailto:")):
            problems.append(f"config.yml: contact_links[{i}].url must be https or mailto")


def check_dir(directory: Path) -> list[str]:
    problems: list[str] = []
    if not directory.is_dir():
        return [f"{directory}: not a directory"]
    for required in REQUIRED_TEMPLATES:
        if not (directory / required).is_file():
            problems.append(f"{required}: missing")
    for path in sorted(directory.iterdir()):
        if path.suffix not in (".yml", ".yaml"):
            problems.append(f"{path.name}: unexpected file (templates are .yml)")
        elif path.name == "config.yml":
            check_config(path, problems)
        else:
            check_template(path, problems)
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    directory = Path(args[0]) if args else DEFAULT_DIR
    problems = check_dir(directory)
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        count = len(list(directory.glob("*.yml")))
        print(f"issue templates ok ({count} files in {directory})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
