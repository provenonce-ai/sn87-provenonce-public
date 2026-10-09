#!/usr/bin/env python3
"""Second-validator readiness: check what can be checked mechanically, list the rest.

  uv run python scripts/second_validator_check.py [--json] [--require-ready] [--root DIR]

READ ONLY. NO NETWORK, NO CHAIN, NO KEYS, NO WALLET.

Each item is READY, NOT_READY or NEEDS_DECISION. A mechanical item is decided by a check run
here (a file is present and parses, a module imports, a digest recomputes). READY on an item
whose evidence says "files present" means exactly that: the files exist, and this script does
not run their tests. ``--root`` runs the checks in a child process inside that tree, with
its ``src`` first on the module path. That executes code from the tree: use it only on a tree
you trust. The replay-store check looks for a server binary and does not
check its eviction policy. Items that depend
on a decision of the maintainers are listed as NEEDS_DECISION and are never decided here; the
truth-custody decision (D05) is one of them. See docs/protocol/second-validator-readiness.md
for what each item means.

Exit code 0 unless ``--require-ready`` is given, which exits 1 when any item is not READY.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

READY, NOT_READY, NEEDS_DECISION = "READY", "NOT_READY", "NEEDS_DECISION"
ROOT = Path(__file__).resolve().parents[1]
EXECUTORS = (
    "sn87_provenonce.institutional_v02.references",
    "sn87_provenonce.pilot.reference",
    "sn87_provenonce.simulation.type_c_reference",
)
# built from parts: the document may be absent from a tree, so it is not cited as a path
ANNOUNCEMENT_SPEC = ("docs", "protocol", "miner-announcement.md")
FILES_PRESENT = "files present (tests not run here)"
TRUTH_FILE = "src/sn87_provenonce/institutional_v02/public_fixture_truth.json"


@dataclass(frozen=True)
class Item:
    id: str
    area: str
    title: str
    status: str
    mechanical: bool
    evidence: str


def executors_available() -> bool:
    try:
        return all(importlib.util.find_spec(name) is not None for name in EXECUTORS)
    except (ImportError, ValueError):
        return False


def _exists(root: Path, *paths: str) -> list[str]:
    return [p for p in paths if not (root / p).is_file()]


def _imports(module: str) -> str | None:
    try:
        importlib.import_module(module)
        return None
    except Exception as error:  # noqa: BLE001 - any import failure is a not-ready item
        return f"{module}: {type(error).__name__}"


def _item(id_: str, area: str, title: str, ok: bool, evidence: str, *,
          mechanical: bool = True, bad: str = NOT_READY) -> Item:
    return Item(id_, area, title, READY if ok else bad, mechanical, evidence)


def check_inputs(root: Path) -> list[Item]:
    items = []
    missing = _exists(root, "src/sn87_provenonce/institutional_v02/fixtures.py",
                      "src/sn87_provenonce/institutional_v02/contracts.py")
    items.append(_item("INPUT_PUBLIC_FIXTURES", "inputs", "public fixture generator and contract",
                       not missing, FILES_PRESENT if not missing else f"missing {missing}"))
    problem = None
    try:
        from sn87_provenonce.cmt import compile_cmt, verify_cmt
        from sn87_provenonce.cmt.hashing import cmt_canonical_bytes
        compiled = compile_cmt()
        verify_cmt(cmt_canonical_bytes(compiled.manifest),
                   compiled.compatibility.manifest_commitment)
    except Exception as error:  # noqa: BLE001
        problem = type(error).__name__
    items.append(_item("INPUT_CMT_VERIFIES", "inputs",
                       "the task manifest compiles and its commitment verifies", problem is None,
                       "verified" if problem is None else f"failed: {problem}"))
    return items


def check_scoring(root: Path) -> list[Item]:
    items = []
    problem = None
    try:
        from sn87_provenonce.classes import IC_APPROVAL_APPLICABILITY
        from sn87_provenonce.profile import REGISTRY, object_commitment
        profile = IC_APPROVAL_APPLICABILITY.profile
        domain = REGISTRY[profile.profile_id][1]
        if object_commitment(profile.document, domain) != profile.commitment:
            problem = "profile commitment does not recompute"
    except Exception as error:  # noqa: BLE001
        problem = type(error).__name__
    items.append(_item("SCORING_PUBLIC_SCORER_AND_PROFILE", "scoring",
                       "public scorer loads and the bound profile commitment recomputes",
                       problem is None, "recomputed" if problem is None else problem))
    truth_state = "absent"
    truth_path = root / TRUTH_FILE
    if truth_path.is_file():
        try:
            cases = json.loads(truth_path.read_text(encoding="utf-8")).get("cases")
            truth_state = "present" if isinstance(cases, dict) and cases else "empty"
        except (OSError, ValueError):
            truth_state = "unparseable"
    items.append(_item("SCORING_TRUTH_PUBLIC_FIXTURES", "scoring",
                       "published truth for the public fixtures is present and parses",
                       truth_state == "present", truth_state))
    items.append(Item(
        "SCORING_TRUTH_HIDDEN_INSTANCES", "scoring",
        "truth for hidden instances computed outside the maintainers",
        NEEDS_DECISION, False,
        "the reference executors that compute it are not published (reference executors "
        f"importable in this tree: {executors_available()}); who holds truth for hidden "
        "instances is the truth-custody decision (D05), which is not made here"))
    return items


def check_client(root: Path) -> list[Item]:
    items = []
    problems = [p for p in (_imports("sn87_provenonce.pilot.client"),
                            _imports("sn87_provenonce.pilot.server"),
                            _imports("sn87_provenonce.pilot.transport")) if p]
    items.append(_item("CLIENT_SIGNED_EXCHANGE", "signed client",
                       "signed request and verified response client imports",
                       not problems, "imports" if not problems else "; ".join(problems)))
    binary = shutil.which("valkey-server") or shutil.which("redis-server")
    items.append(_item("CLIENT_REPLAY_STORE_AVAILABLE", "signed client",
                       "a Valkey-compatible server is installed here (local to this machine)",
                       binary is not None,
                       "found on PATH" if binary else "no valkey-server or redis-server on PATH"))
    spec = (root.joinpath(*ANNOUNCEMENT_SPEC)).is_file()
    items.append(_item("CLIENT_ENDPOINT_DISCOVERY_SPEC", "signed client",
                       "how a validator finds a miner's endpoint is specified", spec,
                       "the miner announcement specification is present" if spec
                       else "the miner announcement specification is absent in this tree"))
    items.append(Item("CLIENT_ENDPOINT_DISCOVERY_READER", "signed client",
                      "a validator-side reader that applies the discovery rule is in this tree",
                      NOT_READY, False,
                      "the specification is public; a reader that applies it is not part of "
                      "the public tree"))
    return items


def check_weights(root: Path) -> list[Item]:
    items = []
    problem = _imports("sn87_provenonce.weights_dry_run")
    try:
        pinned = importlib.metadata.version("bittensor")
    except importlib.metadata.PackageNotFoundError:
        pinned = None
    items.append(_item("WEIGHTS_QUANTIZER", "weights path",
                       "the u16 quantizer imports and the SDK is the pinned version",
                       problem is None and pinned == "11.1.0",
                       f"bittensor {pinned}" if problem is None else problem))
    missing = _exists(root, "scripts/commit_reveal_weights.py",
                      "scripts/commit_reveal_fake_chain.py",
                      "tests/test_commit_reveal_weights.py")
    items.append(_item("WEIGHTS_COMMIT_REVEAL_PATH_AND_TESTS", "weights path",
                       "commit-reveal payload, schedule and state code, fake chain and tests",
                       not missing, FILES_PRESENT if not missing else f"missing {missing}"))
    items.append(Item("WEIGHTS_REAL_SUBMITTER", "weights path",
                      "a real submitter that sends the commit and reads the chain",
                      NOT_READY, False,
                      "none in this repository: the submitter is an interface and no extrinsic "
                      "is sent by any code here"))
    plain = root.joinpath("scripts", "flip_live.py").is_file()
    items.append(Item("WEIGHTS_PLAIN_PATH_OPERATOR_TOOLING", "weights path",
                      "plain weight submission with its approval gates",
                      READY if plain else NOT_READY, True,
                      "present in this tree (operator tooling; not exported)" if plain
                      else "not part of the public tree"))
    items.append(Item("WEIGHTS_COMMIT_REVEAL_ENABLED_ON_TESTNET", "weights path",
                      "commit-reveal switched on for the testnet subnet", NEEDS_DECISION, False,
                      "a chain parameter owned by the subnet owner; not read or set here"))
    return items


def check_admission_and_verifier(root: Path) -> list[Item]:
    items = []
    missing = _exists(root, "scripts/admission_plan.py", "tests/test_admission_plan.py",
                      "docs/protocol/admission.md")
    items.append(_item("ADMISSION_PLAN_VERSION_TOOL", "admission",
                       "tool and tests for plan versions, stages and the criteria checker",
                       not missing, FILES_PRESENT if not missing else f"missing {missing}"))
    items.append(Item("ADMISSION_CRITERIA_VALUES", "admission",
                      "the published admission criteria values are approved", NEEDS_DECISION,
                      False, "values are proposals until an approval record cites the digest"))
    attestations = sorted((root / "attestation").glob("SN87_TESTNET_ATTESTATION_*.json")) \
        if (root / "attestation").is_dir() else []
    verifier = root / "scripts/verify_attestation.py"
    ok, detail = False, "no attestation file or verifier"
    if attestations and verifier.is_file():
        try:
            spec = importlib.util.spec_from_file_location("verify_attestation_probe", verifier)
            module = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(verifier.parent))
            try:
                spec.loader.exec_module(module)
            finally:
                sys.path.pop(0)
            results = [module.check_integrity(json.loads(p.read_text(encoding="utf-8")))
                       for p in attestations]
            ok = all(r[0] for r in results)
            detail = f"{len(results)} attestation digests recompute" if ok \
                else "; ".join(r[1] for r in results if not r[0])
        except Exception as error:  # noqa: BLE001
            detail = f"verifier failed to run: {type(error).__name__}"
    items.append(_item("VERIFIER_ATTESTATION_INTEGRITY", "verification",
                       "the public verifier recomputes the attestation digests offline",
                       ok, detail))
    plan_tool = root.joinpath("scripts", "flip_to_testnet.py").is_file() \
        and executors_available()
    items.append(Item("VERIFIER_PLAN_DIGEST_RECOMPUTE", "verification",
                      "the approved plan digest recomputes outside the maintainers",
                      READY if plan_tool else NOT_READY, True,
                      "recomputable here (private tree)" if plan_tool
                      else "needs the private plan tool and reference executors; reported "
                           "UNVERIFIED by the public verifier"))
    items.append(Item("TRUTH_CUSTODY_D05", "decision",
                      "who holds truth for hidden instances in the contest phase",
                      NEEDS_DECISION, False,
                      "open decision D05; this check does not decide it"))
    return items


def run_checks(root: Path = ROOT) -> list[Item]:
    """Run every check against ``root``. For a root other than this checkout the checks run
    in a child process whose working directory is the root and whose module path starts with
    the root's ``src``, so imports come from that tree and not from this environment."""
    if Path(root).resolve() != ROOT:
        return _run_in_child(Path(root).resolve())
    return _run_here(root)


def _run_in_child(root: Path) -> list[Item]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(root / "src"), *filter(None, [os.environ.get("PYTHONPATH")])])}
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--in-process", "--root", str(root),
         "--json"], cwd=root, env=env, capture_output=True, text=True, timeout=300, check=False)
    try:
        return [Item(**row) for row in json.loads(proc.stdout)]
    except ValueError:
        return [Item("CHECK_RUN", "meta", "the checks ran against the given root", NOT_READY,
                     True, f"child process failed: {proc.stderr.strip()[-200:]}")]


def _run_here(root: Path) -> list[Item]:
    checks: tuple[Callable[[Path], list[Item]], ...] = (
        check_inputs, check_scoring, check_client, check_weights, check_admission_and_verifier)
    return [item for check in checks for item in check(root)]


def render(items: list[Item]) -> str:
    width = max(len(i.id) for i in items)
    lines = [f"{'ITEM':<{width}}  STATUS          KIND        EVIDENCE"]
    for i in items:
        kind = "checked" if i.mechanical else "stated"
        lines.append(f"{i.id:<{width}}  {i.status:<14}  {kind:<10}  {i.evidence}")
    counts = {s: sum(i.status == s for i in items) for s in (READY, NOT_READY, NEEDS_DECISION)}
    lines.append("")
    lines.append("  ".join(f"{k}: {v}" for k, v in counts.items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--in-process", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    items = _run_here(args.root.resolve()) if args.in_process else run_checks(args.root)
    print(json.dumps([asdict(i) for i in items], indent=2) if args.json else render(items))
    if args.require_ready and any(i.status != READY for i in items):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
