"""The public quantizer copy equals scripts/pilot_chain_dry_run.py wherever both exist."""

import importlib.util
import json
from pathlib import Path

import pytest

from sn87_provenonce import weights_dry_run as public

ROOT = Path(__file__).parents[1]
ORIGINAL = ROOT / "scripts" / "pilot_chain_dry_run.py"

TARGET = {"network": "test", "genesis": public.TESTNET_GENESIS, "sdk_version": "11.1.0",
          "netuid": 582, "block": 100, "spec_version": 1, "version_key": 0,
          "min_allowed_weights": 1, "max_weights_limit": 65535, "validator_uid": 0,
          "rate_limit_blocks": 10, "last_update_block": 1, "registered": True,
          "validator_permit": True, "active": True, "commit_reveal": False}
DOCUMENT = {"target": TARGET, "weights": [{"uid": 1, "weight": "0.25"},
                                          {"uid": 2, "weight": "0.75"}]}


def test_quantizes_a_row_without_a_wallet():
    out = public.dry_run(DOCUMENT)
    assert out["state"] == "TARGET_CONFORMED_DRY_RUN" and out["broadcast"] is False
    assert out["uids"] == [1, 2] and out["u16_weights"] == [21845, 65535]


def test_refuses_the_wrong_network():
    with pytest.raises(ValueError, match="TESTNET_IDENTITY_REQUIRED"):
        public.dry_run({**DOCUMENT, "target": {**TARGET, "network": "finney"}})


def _outcome(fn, document):
    try:
        return json.dumps(fn(document), sort_keys=True)
    except ValueError as error:
        return f"ValueError:{error}"


@pytest.mark.skipif(not ORIGINAL.exists(), reason="ops file scripts/pilot_chain_dry_run.py absent")
def test_public_copy_equals_the_ops_original():
    spec = importlib.util.spec_from_file_location("pilot_chain_dry_run_original", ORIGINAL)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    assert original.TESTNET_GENESIS == public.TESTNET_GENESIS
    assert json.dumps(original.dry_run(DOCUMENT), sort_keys=True) == json.dumps(
        public.dry_run(DOCUMENT), sort_keys=True)
    cases = [
        DOCUMENT,
        {**DOCUMENT, "target": {**TARGET, "commit_reveal": True}},
        {**DOCUMENT, "weights": [{"uid": 1, "weight": "0"}, {"uid": 2, "weight": "0"}]},
        {**DOCUMENT, "weights": [{"uid": u, "weight": w} for u, w in
                                 ((1, "1"), (2, "3"), (3, "0.3333333333"), (7, "2.5"))]},
        {**DOCUMENT, "weights": [{"uid": 0, "weight": "1"}]},
        {**DOCUMENT, "weights": [{"uid": 1, "weight": "-1"}]},
        {**DOCUMENT, "weights": [{"uid": 1, "weight": 1}]},
        {**DOCUMENT, "weights": [{"uid": 1, "weight": "1"}, {"uid": 1, "weight": "2"}]},
        {**DOCUMENT, "target": {**TARGET, "last_update_block": 99}},
        {**DOCUMENT, "target": {**TARGET, "registered": False}},
        {**DOCUMENT, "target": {**TARGET, "sdk_version": "0.0.0"}},
        {**DOCUMENT, "target": {**TARGET, "min_allowed_weights": 3}},
    ]
    for document in cases:
        assert _outcome(original.dry_run, document) == _outcome(public.dry_run, document)
