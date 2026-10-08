"""scripts/check_issue_templates.py accepts the real templates and rejects broken ones."""

import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("check_issue_templates",
                                              ROOT / "scripts/check_issue_templates.py")
cit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cit
spec.loader.exec_module(cit)

TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "ISSUE_TEMPLATE"
    shutil.copytree(TEMPLATES, target)
    return target


def test_the_committed_templates_are_clean():
    assert cit.check_dir(TEMPLATES) == []
    assert cit.main([str(TEMPLATES)]) == 0


def test_the_required_templates_exist():
    for name in cit.REQUIRED_TEMPLATES:
        assert (TEMPLATES / name).is_file(), name


def test_a_missing_template_is_reported(tmp_path):
    d = _copy(tmp_path)
    (d / "security.yml").unlink()
    assert any("security.yml: missing" in p for p in cit.check_dir(d))


def test_invalid_yaml_is_reported(tmp_path):
    d = _copy(tmp_path)
    (d / "setup-failure.yml").write_text("name: [unclosed\n")
    assert any("does not parse as YAML" in p for p in cit.check_dir(d))
    assert cit.main([str(d)]) == 1


def test_missing_required_keys_are_reported(tmp_path):
    d = _copy(tmp_path)
    (d / "scoring-question.yml").write_text("name: x\nbody: []\n")
    problems = cit.check_dir(d)
    assert any("missing required key 'description'" in p for p in problems)
    assert any("missing required key 'body'" in p for p in problems)


def test_duplicate_ids_and_bad_types_are_reported(tmp_path):
    d = _copy(tmp_path)
    (d / "setup-failure.yml").write_text(
        "name: x\ndescription: y\nbody:\n"
        "  - type: input\n    id: a\n    attributes:\n      label: A\n"
        "  - type: input\n    id: a\n    attributes:\n      label: B\n"
        "  - type: video\n    attributes:\n      label: C\n")
    problems = cit.check_dir(d)
    assert any("duplicate id" in p for p in problems)
    assert any("type 'video'" in p for p in problems)


def test_the_security_template_cannot_collect_free_text(tmp_path):
    d = _copy(tmp_path)
    (d / "security.yml").write_text(
        "name: x\ndescription: y\nbody:\n"
        "  - type: textarea\n    id: details\n    attributes:\n      label: Details\n")
    assert any("must not collect free text" in p for p in cit.check_dir(d))


def test_config_must_disable_blank_issues_and_link_out(tmp_path):
    d = _copy(tmp_path)
    (d / "config.yml").write_text("blank_issues_enabled: true\n")
    problems = cit.check_dir(d)
    assert any("blank_issues_enabled must be false" in p for p in problems)
    assert any("contact_links must be a non-empty list" in p for p in problems)


def test_a_stray_file_is_reported(tmp_path):
    d = _copy(tmp_path)
    (d / "notes.txt").write_text("x")
    assert any("unexpected file" in p for p in cit.check_dir(d))


def test_the_subset_parser_reads_the_shapes_the_templates_use():
    doc = (
        "# comment\n"
        "name: A form\n"
        "flag: false\n"
        "quoted: \"[tag] \"\n"
        "single: 'it''s'\n"
        "empty: []\n"
        "body:\n"
        "  - type: markdown\n"
        "    attributes:\n"
        "      value: |\n"
        "        line one: with colon\n"
        "\n"
        "        line two\n"
        "  - type: dropdown\n"
        "    options:\n"
        "      - One\n"
        "      - Two (a, b)\n"
    )
    assert cit.parse_yaml_subset(doc) == {
        "name": "A form", "flag": False, "quoted": "[tag] ", "single": "it's", "empty": [],
        "body": [
            {"type": "markdown",
             "attributes": {"value": "line one: with colon\n\nline two\n"}},
            {"type": "dropdown", "options": ["One", "Two (a, b)"]},
        ],
    }


def test_the_subset_parser_rejects_what_it_cannot_read():
    bad = ["a:\n\tb: 1\n", "a: 1\na: 2\n", "a: b: c\n", "a: {x: 1}\n", "a: 1\n  b: 2\n",
           "a: \"open\n", "just text\n", "a: 'Builder's report'\n"]
    for text in bad:
        try:
            cit.parse_yaml_subset(text)
        except cit.YamlSubsetError:
            continue
        raise AssertionError(f"accepted {text!r}")


def test_doubled_single_quotes_are_accepted():
    assert cit.parse_yaml_subset("a: 'Builder''s report'\n") == {"a": "Builder's report"}
