"""Pure no-broadcast u16 weight quantizer. No wallet, RPC, or execution capability.

The u16 weight quantizer, kept in the public tree so a weight row can be quantized without
the operator tooling. In the private source repository ``tests/test_weights_dry_run.py`` asserts
it stays equal to the operator copy. The one ``bittensor`` call is imported at module top;
without the SDK the module still imports and ``dry_run`` raises ``RuntimeError``.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

try:
    from bittensor.intents.weights import normalize
except ImportError:  # the SDK is an optional extra
    normalize = None

TESTNET_GENESIS = "0x8f9cf856bf558a14440e75569c9e58594757048d7b3a84b5d25f6bd978263105"


def dry_run(document: dict) -> dict:
    if normalize is None:
        raise RuntimeError("the bittensor SDK is required: uv sync --locked --extra transport")
    target = document["target"]
    if target["network"] != "test" or target["genesis"] != TESTNET_GENESIS:
        raise ValueError("TESTNET_IDENTITY_REQUIRED")
    if target["sdk_version"] != "11.1.0":
        raise ValueError("SDK_VERSION_DRIFT")
    numeric = ["netuid", "block", "spec_version", "version_key", "min_allowed_weights",
               "max_weights_limit", "validator_uid", "rate_limit_blocks", "last_update_block"]
    if any(type(target[k]) is not int or target[k] < 0 for k in numeric):
        raise ValueError("INVALID_TARGET_INTEGER")
    if not 1 <= target["netuid"] < 4096 or not 1 <= target["max_weights_limit"] <= 65535:
        raise ValueError("INVALID_TARGET_CONSTRAINT")
    if any(target[k] is not True for k in ("registered", "validator_permit", "active")):
        raise ValueError("TARGET_NOT_WEIGHT_ELIGIBLE")
    if target["block"] - target["last_update_block"] < target["rate_limit_blocks"]:
        raise ValueError("WEIGHT_RATE_LIMIT_PENDING")
    if target["commit_reveal"] not in {True, False} or type(target["commit_reveal"]) is not bool:
        raise ValueError("UNKNOWN_SUBMISSION_MODE")
    rows = document["weights"]
    uids, weights = [], []
    for row in rows:
        uid = row["uid"]
        if type(uid) is not int or not 0 <= uid <= 65535 or uid in uids:
            raise ValueError("INVALID_OR_DUPLICATE_UID")
        if uid == target["validator_uid"]:
            raise ValueError("PILOT_SELF_REWARD_FORBIDDEN")
        if not isinstance(row["weight"], str):
            raise ValueError("DECIMAL_STRING_REQUIRED")
        try:
            value = Decimal(row["weight"])
        except InvalidOperation:
            raise ValueError("INVALID_WEIGHT") from None
        if not value.is_finite() or value < 0:
            raise ValueError("INVALID_WEIGHT")
        uids.append(uid)
        weights.append(value)
    base = {"schema_version": "gra-chain-dry-run/0.1", "broadcast": False,
            "target": target, "input_sha256": hashlib.sha256(
                json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()}
    positive = [(u, w) for u, w in zip(uids, weights, strict=True) if w > 0]
    if not positive:
        return base | {"state": "NO_VALID_WEIGHT_ROW", "uids": [], "u16_weights": []}
    if len(positive) < target["min_allowed_weights"]:
        raise ValueError("TARGET_MINIMUM_REQUIRES_UNSUPPORTED_PREFERENCES")
    uids, weights = map(list, zip(*positive, strict=True))
    total, peak = sum(weights), max(weights)
    if peak * 65535 > Decimal(target["max_weights_limit"]) * total:
        raise ValueError("TARGET_CAP_REQUIRES_REWARD_DISTORTION")
    values = [int((w / peak * 65535).to_integral_value(rounding=ROUND_HALF_EVEN)) for w in weights]
    quantized = [(u, v) for u, v in zip(uids, values, strict=True) if v > 0]
    if len(quantized) < target["min_allowed_weights"]:
        raise ValueError("QUANTIZATION_DROPS_BELOW_MINIMUM")
    out_uids, out_values = map(list, zip(*quantized, strict=True))
    if max(out_values) * 65535 > target["max_weights_limit"] * sum(out_values):
        raise ValueError("QUANTIZED_ROW_EXCEEDS_CAP")
    sdk_uids, sdk_values = normalize(uids, [float(w) for w in weights])
    if (sdk_uids, sdk_values) != (out_uids, out_values):
        raise ValueError("SDK_QUANTIZATION_DIVERGENCE")
    return base | {"state": "TARGET_CONFORMED_DRY_RUN", "uids": out_uids,
                   "u16_weights": out_values,
                   "submission_mode": "timelocked_commit" if target["commit_reveal"] else "plain",
                   "warning": "No transaction composed, signed, submitted, finalized or applied."}
