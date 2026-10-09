"""Second-validator readiness check: statuses, the open decision, and absent-file handling."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("second_validator_check",
                                              ROOT / "scripts/second_validator_check.py")
svc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = svc
spec.loader.exec_module(svc)

STATUSES = {svc.READY, svc.NOT_READY, svc.NEEDS_DECISION}


def by_id(items):
    return {i.id: i for i in items}


def test_every_item_has_a_valid_status_and_evidence():
    items = svc.run_checks(ROOT)
    assert len({i.id for i in items}) == len(items) >= 15
    for item in items:
        assert item.status in STATUSES and item.evidence and item.area and item.title


def test_truth_custody_is_listed_open_and_never_decided(tmp_path):
    for root in (ROOT, tmp_path):
        items = by_id(svc.run_checks(root))
        for key in ("TRUTH_CUSTODY_D05", "SCORING_TRUTH_HIDDEN_INSTANCES",
                    "WEIGHTS_COMMIT_REVEAL_ENABLED_ON_TESTNET", "ADMISSION_CRITERIA_VALUES"):
            assert items[key].status == svc.NEEDS_DECISION and not items[key].mechanical


def test_no_real_submitter_is_reported_not_ready():
    items = by_id(svc.run_checks(ROOT))
    assert items["WEIGHTS_REAL_SUBMITTER"].status == svc.NOT_READY
    assert items["CLIENT_ENDPOINT_DISCOVERY_READER"].status == svc.NOT_READY


def test_mechanical_items_follow_the_files_present(tmp_path):
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    empty = by_id(svc.run_checks(root))
    assert empty["WEIGHTS_COMMIT_REVEAL_PATH_AND_TESTS"].status == svc.NOT_READY
    assert empty["SCORING_TRUTH_PUBLIC_FIXTURES"].status == svc.NOT_READY
    assert empty["ADMISSION_PLAN_VERSION_TOOL"].status == svc.NOT_READY
    assert empty["VERIFIER_ATTESTATION_INTEGRITY"].status == svc.NOT_READY
    for rel in ("scripts/commit_reveal_weights.py", "scripts/commit_reveal_fake_chain.py",
                "tests/test_commit_reveal_weights.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    assert by_id(svc.run_checks(root))["WEIGHTS_COMMIT_REVEAL_PATH_AND_TESTS"].status \
        == svc.READY


def test_truth_file_states(tmp_path):
    truth = tmp_path / svc.TRUTH_FILE
    truth.parent.mkdir(parents=True)
    for text, expected in (("{", svc.NOT_READY), ('{"cases": {}}', svc.NOT_READY),
                           ('{"cases": {"a": {}}}', svc.READY)):
        truth.write_text(text)
        assert by_id(svc.check_scoring(tmp_path))["SCORING_TRUTH_PUBLIC_FIXTURES"].status \
            == expected


def test_cli_output_and_require_ready(capsys):
    assert svc.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {d["id"] for d in data} >= {"TRUTH_CUSTODY_D05", "WEIGHTS_REAL_SUBMITTER"}
    assert svc.main(["--require-ready"]) == 1  # open decisions keep the check from passing
    assert "NEEDS_DECISION" in capsys.readouterr().out


def test_the_readiness_document_agrees_with_the_script():
    """The statuses in the document are the script's statuses for items that do not depend on
    the tree or the machine."""
    text = (ROOT / "docs/protocol/second-validator-readiness.md").read_text()
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].startswith("`") and cells[0].endswith("`"):
            rows[cells[0].strip("`")] = cells[1]
    items = by_id(svc.run_checks(ROOT))
    assert set(rows) == set(items)  # every item is documented, none invented
    for key, shown in rows.items():
        if shown in ("machine", "tree"):
            continue
        assert shown == items[key].status, key


def test_root_imports_come_from_that_tree_not_this_environment(tmp_path):
    root = tmp_path / "tree"
    package = root / "src" / "sn87_provenonce"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")  # a tree whose package has none of the modules
    items = by_id(svc.run_checks(root))
    assert items["WEIGHTS_QUANTIZER"].status == svc.NOT_READY
    assert items["CLIENT_SIGNED_EXCHANGE"].status == svc.NOT_READY
    assert by_id(svc.run_checks(ROOT))["WEIGHTS_QUANTIZER"].status == svc.READY
