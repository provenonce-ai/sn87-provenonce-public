"""Commit-reveal submission path, tested against a fake chain and the SDK's own functions.

NO EXTRINSIC IS SENT. The submitter is the in-memory ``FakeChain``. The payload test checks the
arguments this module gives the SDK against the arguments the SDK's own weight intent gives it.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.metadata
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


crw = load("commit_reveal_weights")
fake = load("commit_reveal_fake_chain")
from sn87_provenonce.weights_dry_run import TESTNET_GENESIS  # noqa: E402

NETUID = 582
HOTKEY_PK = bytes(range(32))
ROW_UIDS, ROW_VALUES = [1, 2], [65535, 21845]


def document(commit_reveal=True, weights=None):
    return {"target": {
        "network": "test", "genesis": TESTNET_GENESIS, "sdk_version": "11.1.0",
        "netuid": NETUID, "block": 1000, "spec_version": 471, "version_key": 0,
        "min_allowed_weights": 1, "max_weights_limit": 65535, "validator_uid": 0,
        "registered": True, "validator_permit": True, "active": True,
        "rate_limit_blocks": 1, "last_update_block": 0, "commit_reveal": commit_reveal,
        "fixture_only": True,
    }, "weights": weights if weights is not None
        else [{"uid": 1, "weight": "0.75"}, {"uid": 2, "weight": "0.25"}]}


def runner(chain, tmp_path, mode=crw.MODE_TIMELOCKED, **kw):
    args = dict(submitter=chain, state_path=tmp_path / "state.json", mode=mode, netuid=NETUID,
                hotkey_public_key=HOTKEY_PK, encrypt=chain.encrypt, max_attempts=3)
    if mode == crw.MODE_SALTED:
        args["commit_digest"] = fake.fake_commit_digest
    return crw.CommitRevealRunner(**(args | kw))


def finish(run, chain):
    return run.run_until_terminal(chain.advance_to)


# ------------------------------------------------------------------ the interface rule
@pytest.mark.parametrize("bad", [None, object(), "chain"])
def test_refuses_without_a_submitter_object(bad, tmp_path):
    with pytest.raises(crw.SubmitterRequired):
        crw.CommitRevealRunner(submitter=bad, state_path=tmp_path / "s.json", netuid=NETUID,
                               hotkey_public_key=HOTKEY_PK)


def test_submitter_is_required_by_keyword_and_has_no_default():
    with pytest.raises(TypeError):
        crw.CommitRevealRunner(state_path="x", netuid=NETUID)  # type: ignore[call-arg]


def test_module_imports_no_wallet_chain_or_plain_path_code():
    for name in ("commit_reveal_weights", "commit_reveal_fake_chain"):
        tree = ast.parse((ROOT / "scripts" / f"{name}.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        banned = ("flip_", "pilot_chain", "wallet", "keyfile", "substrate", "websocket",
                  "httpx", "requests", "socket", "subprocess")
        assert not [m for m in imported if any(b in m for b in banned)], imported


def test_cli_has_no_submit_and_hides_the_salt(tmp_path, capsys):
    assert crw.main(["submit"]) == 2
    doc = tmp_path / "doc.json"
    doc.write_text(json.dumps(document()))
    assert crw.main(["plan", "--document", str(doc)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["equals_plain_path_row"] is True and summary["uids"] == ROW_UIDS
    assert "timelocked" in summary["mode_for_sdk"]
    state = tmp_path / "state.json"
    chain = fake.FakeChain()
    run = runner(chain, tmp_path, mode=crw.MODE_SALTED)
    run.start(document())
    run.step()
    assert crw.main(["status", "--state", str(state)]) == 0
    printed = capsys.readouterr().out
    assert '"salt"' not in printed and "COMMITTED" in printed
    assert crw.main(["status", "--state", str(tmp_path / "missing.json")]) == 1


# ------------------------------------------------------------------------ the row
def test_row_equals_what_the_plain_path_would_set():
    assert crw.commit_reveal_row(document()) == (ROW_UIDS, ROW_VALUES)
    assert crw.plain_equivalent_row(document()) == (ROW_UIDS, ROW_VALUES)
    assert crw.commit_reveal_row(document()) == crw.plain_equivalent_row(document())
    assert crw.plan_summary(document())["equals_plain_path_row"] is True


def test_a_plain_target_is_refused_by_this_path(tmp_path):
    with pytest.raises(crw.CommitRevealError, match="TARGET_NOT_COMMIT_REVEAL"):
        crw.commit_reveal_row(document(commit_reveal=False))
    with pytest.raises(crw.CommitRevealError, match="TARGET_NOT_COMMIT_REVEAL"):
        runner(fake.FakeChain(), tmp_path).start(document(commit_reveal=False))


def test_netuid_mismatch_is_refused(tmp_path):
    other = document()
    other["target"]["netuid"] = 7
    with pytest.raises(crw.CommitRevealError, match="NETUID_MISMATCH"):
        runner(fake.FakeChain(), tmp_path).start(other)


# ---------------------------------------------------- timelocked: the normal path
def test_timelocked_commit_then_chain_reveal_applies_the_same_row(tmp_path):
    chain = fake.FakeChain()
    run = runner(chain, tmp_path)
    run.start(document())
    first = run.step()
    assert first.phase == crw.COMMITTED and first.wait_until_block == 110
    assert chain.weights is None  # nothing applied before the reveal block
    final = finish(run, chain)
    assert final.phase == crw.REVEALED
    assert chain.weights == dict(zip(ROW_UIDS, ROW_VALUES, strict=True))
    assert [name for name, _ in chain.calls].count("submit_timelocked_commit") == 1
    assert chain.weights_log == [(110, chain.weights)]  # applied once, at the reveal block
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["commit"]["landed_block"] == 100 and state["row_digest"].startswith("sha256:")
    assert stat.S_IMODE((tmp_path / "state.json").stat().st_mode) == 0o600


def test_reveal_is_not_declared_early_and_a_missing_reveal_is_overdue(tmp_path):
    chain = fake.FakeChain()
    run = runner(chain, tmp_path, reveal_grace_blocks=4)
    run.start(document())
    run.step()
    chain.advance_to(105)
    early = run.step()
    assert early.phase == crw.COMMITTED and early.action == "WAIT_FOR_CHAIN_REVEAL"
    chain.drop_next_reveal()  # the chain fails to open the commit
    final = finish(run, chain)
    assert final.phase == crw.OVERDUE and chain.weights is None


def test_replayed_timelocked_commit_is_rejected_by_the_chain():
    chain = fake.FakeChain()
    commit = crw.build_timelocked_commit(
        chain.read_state(NETUID), ROW_UIDS, ROW_VALUES, hotkey_public_key=HOTKEY_PK,
        encrypt=chain.encrypt)
    chain.submit_timelocked_commit(commit)
    chain.advance(2)
    with pytest.raises(crw.SubmitRejected, match="COMMIT_REPLAY"):
        chain.submit_timelocked_commit(commit)


def test_the_fake_chain_refuses_a_real_ciphertext():
    chain = fake.FakeChain()
    commit = crw.TimelockedCommit(NETUID, 0, b"\x00" * 64, 1, 4, (1,), (1,))
    with pytest.raises(crw.SubmitRejected, match="FAKE_CHAIN_UNSUPPORTED_PAYLOAD"):
        chain.submit_timelocked_commit(commit)


# --------------------------------------------------------------- salted: windows
def test_salted_commit_and_reveal_in_the_window(tmp_path):
    chain = fake.FakeChain()
    run = runner(chain, tmp_path, crw.MODE_SALTED)
    run.start(document())
    committed = run.step()
    assert committed.phase == crw.COMMITTED and committed.wait_until_block == 110
    final = finish(run, chain)
    assert final.phase == crw.REVEALED
    assert chain.weights == dict(zip(ROW_UIDS, ROW_VALUES, strict=True))
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["commit"]["reveal_window"] == [110, 130]


def test_reveal_too_early_is_not_sent_and_the_chain_would_refuse_it(tmp_path):
    chain = fake.FakeChain()
    run = runner(chain, tmp_path, crw.MODE_SALTED)
    run.start(document())
    run.step()
    chain.advance(3)
    early = run.step()
    assert early.action == "WAIT_REVEAL_WINDOW" and early.wait_until_block == 110
    assert "submit_reveal" not in [name for name, _ in chain.calls]
    state = json.loads((tmp_path / "state.json").read_text())
    with pytest.raises(crw.SubmitRejected, match="REVEAL_TOO_EARLY"):
        chain.submit_reveal(NETUID, 0, ROW_UIDS, ROW_VALUES, state["salt"], 0)


def test_reveal_too_late_expires_without_sending(tmp_path):
    chain = fake.FakeChain()
    run = runner(chain, tmp_path, crw.MODE_SALTED)
    run.start(document())
    run.step()
    chain.advance_to(131)  # one block after the reveal epoch
    late = run.step()
    assert late.phase == crw.EXPIRED and late.action == "REVEAL_WINDOW_MISSED"
    assert "submit_reveal" not in [name for name, _ in chain.calls]
    state = json.loads((tmp_path / "state.json").read_text())
    with pytest.raises(crw.SubmitRejected, match="REVEAL_EXPIRED"):
        chain.submit_reveal(NETUID, 0, ROW_UIDS, ROW_VALUES, state["salt"], 0)
    assert chain.weights is None


def test_salt_reuse_is_refused_by_the_ledger_and_by_the_chain(tmp_path):
    chain = fake.FakeChain()
    salt = [1, 2, 3, 4, 5, 6, 7, 8]
    first = runner(chain, tmp_path / "a", crw.MODE_SALTED, salt_source=lambda: list(salt))
    first.start(document())
    assert finish(first, chain).phase == crw.REVEALED
    # same state directory, same salt: the ledger refuses before anything is sent
    again = runner(chain, tmp_path / "a", crw.MODE_SALTED, salt_source=lambda: list(salt))
    again.start(document())
    sent = len(chain.calls)
    with pytest.raises(crw.SaltReused):
        again.step()
    assert len(chain.calls) == sent
    # a different state directory has its own ledger: the chain refuses the duplicate hash
    elsewhere = runner(chain, tmp_path / "b", crw.MODE_SALTED, salt_source=lambda: list(salt))
    elsewhere.start(document())
    chain.advance(2)
    refused = elsewhere.step()
    assert refused.phase == crw.FAILED and refused.detail == "COMMIT_ALREADY_EXISTS"


def test_a_fresh_salt_is_used_by_default(tmp_path):
    assert len({tuple(crw.default_salt()) for _ in range(20)}) == 20
    chain = fake.FakeChain()
    run = runner(chain, tmp_path, crw.MODE_SALTED)
    run.start(document())
    run.step()
    assert len(json.loads((tmp_path / "state.json").read_text())["salt"]) == 8


def test_salted_mode_needs_a_digest_function_and_never_guesses_one(tmp_path):
    with pytest.raises(crw.CommitRevealError, match="COMMIT_DIGEST_FUNCTION_REQUIRED"):
        crw.CommitRevealRunner(submitter=fake.FakeChain(), state_path=tmp_path / "s.json",
                               mode=crw.MODE_SALTED, netuid=NETUID)
    import bittensor.intents.weights as sdk_weights
    assert not [n for n in dir(sdk_weights) if "hash" in n.lower()]  # why: no SDK helper exists


# ------------------------------------------------------------------------ restart
@pytest.mark.parametrize("mode", [crw.MODE_TIMELOCKED, crw.MODE_SALTED])
def test_restart_between_commit_and_reveal_resumes(mode, tmp_path):
    chain = fake.FakeChain()
    first = runner(chain, tmp_path, mode)
    first.start(document())
    assert first.step().phase == crw.COMMITTED
    chain.advance(3)
    del first  # the process ends here; only the state file survives
    second = runner(chain, tmp_path, mode)
    assert finish(second, chain).phase == crw.REVEALED
    submits = [n for n, _ in chain.calls if n.startswith("submit_")]
    assert submits.count("submit_timelocked_commit") + submits.count("submit_hash_commit") == 1
    assert chain.weights == dict(zip(ROW_UIDS, ROW_VALUES, strict=True))


@pytest.mark.parametrize("mode,operation", [(crw.MODE_TIMELOCKED, "submit_timelocked_commit"),
                                            (crw.MODE_SALTED, "submit_hash_commit")])
def test_crash_after_the_chain_accepted_the_commit_does_not_commit_twice(mode, operation,
                                                                        tmp_path):
    chain = fake.FakeChain()
    chain.crash_after(operation)
    first = runner(chain, tmp_path, mode)
    first.start(document())
    with pytest.raises(fake.SimulatedCrash):
        first.step()
    assert json.loads((tmp_path / "state.json").read_text())["phase"] == crw.COMMITTING
    second = runner(chain, tmp_path, mode)
    assert finish(second, chain).phase == crw.REVEALED
    assert [n for n, _ in chain.calls].count(operation) == 1


def test_crash_after_the_chain_accepted_the_reveal_does_not_reveal_twice(tmp_path):
    chain = fake.FakeChain()
    chain.crash_after("submit_reveal")
    first = runner(chain, tmp_path, crw.MODE_SALTED)
    first.start(document())
    first.step()
    chain.advance_to(112)
    with pytest.raises(fake.SimulatedCrash):
        first.step()
    assert json.loads((tmp_path / "state.json").read_text())["phase"] == crw.REVEALING
    second = runner(chain, tmp_path, crw.MODE_SALTED)
    result = second.step()
    assert result.phase == crw.REVEALED and result.action == "REVEAL_OBSERVED"
    assert [n for n, _ in chain.calls].count("submit_reveal") == 1


def test_a_run_in_progress_blocks_a_new_start_and_a_mismatch_is_refused(tmp_path):
    chain = fake.FakeChain()
    run = runner(chain, tmp_path)
    run.start(document())
    with pytest.raises(crw.CommitRevealError, match="RUN_IN_PROGRESS"):
        run.start(document())
    other = runner(chain, tmp_path, crw.MODE_SALTED)
    with pytest.raises(crw.CommitRevealError, match="STATE_DOES_NOT_MATCH_RUNNER"):
        other.step()
    with pytest.raises(crw.CommitRevealError, match="NO_RUN"):
        runner(chain, tmp_path / "none").step()
    finish(run, chain)
    run.start(document())  # a finished run does not block the next one


def test_a_stale_commit_is_replanned_when_the_epoch_moved_on(tmp_path):
    chain = fake.FakeChain()
    chain.crash_after("submit_hash_commit")
    first = runner(chain, tmp_path, crw.MODE_SALTED)
    first.start(document())
    with pytest.raises(fake.SimulatedCrash):
        first.step()
    # simulate the commit never having landed: a new chain with the same clock
    fresh = fake.FakeChain()
    fresh.block = 112  # next epoch
    second = runner(fresh, tmp_path, crw.MODE_SALTED)
    result = second.step()
    assert result.phase == crw.COMMITTED
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["commit"]["landed_block"] == 112
    assert any("replan" in h["note"] for h in state["history"])


# ------------------------------------------- rate limits, failures, boundaries, empty
def test_rate_limit_waits_then_commits(tmp_path):
    chain = fake.FakeChain(rate_limit_blocks=5)
    chain.last_update_block = chain.block - 2
    run = runner(chain, tmp_path)
    run.start(document())
    wait = run.step()
    assert wait.action == "WAIT_RATE_LIMIT" and wait.wait_until_block == 103
    assert "submit_timelocked_commit" not in [n for n, _ in chain.calls]
    assert finish(run, chain).phase == crw.REVEALED


def test_transient_failure_is_retried_and_permanent_failure_stops(tmp_path):
    chain = fake.FakeChain()
    chain.fail_next("submit_timelocked_commit", crw.SubmitRejected("NETWORK", transient=True))
    run = runner(chain, tmp_path)
    run.start(document())
    retry = run.step()
    assert retry.phase == crw.COMMITTING and retry.action == "RETRY_COMMIT"
    assert finish(run, chain).phase == crw.REVEALED
    chain2 = fake.FakeChain()
    chain2.fail_next("submit_timelocked_commit", crw.SubmitRejected("BAD_ORIGIN"))
    run2 = runner(chain2, tmp_path / "two")
    run2.start(document())
    assert run2.step().phase == crw.FAILED
    chain3 = fake.FakeChain()
    for _ in range(3):
        chain3.fail_next("submit_timelocked_commit",
                         crw.SubmitRejected("NETWORK", transient=True))
    run3 = runner(chain3, tmp_path / "three")
    run3.start(document())
    assert finish(run3, chain3).phase == crw.FAILED


def test_commit_near_the_end_of_an_epoch_waits_for_the_next(tmp_path):
    chain = fake.FakeChain(start_block=108)  # epoch 32 ends at block 109
    assert crw.blocks_to_epoch_end(108, NETUID, 20) == 1
    run = runner(chain, tmp_path)
    run.start(document())
    wait = run.step()
    assert wait.action == "WAIT_EPOCH_BOUNDARY" and wait.wait_until_block == 110
    assert "submit_timelocked_commit" not in [n for n, _ in chain.calls]
    final = finish(run, chain)
    assert final.phase == crw.REVEALED
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["commit"]["landed_block"] == 110
    assert chain.weights_log[0][0] == 131  # reveal epoch is the landing epoch plus one


def test_salted_window_is_computed_from_the_block_the_commit_landed_in(tmp_path):
    assert crw.salted_reveal_window(109, NETUID, 20, 1) == (110, 130)
    assert crw.salted_reveal_window(110, NETUID, 20, 1) == (131, 151)
    assert crw.salted_reveal_window(110, NETUID, 20, 2) == (152, 172)
    assert crw.epoch_bounds(crw.epoch_index(110, NETUID, 20), NETUID, 20) == (110, 130)


def test_an_empty_row_sends_nothing_and_an_empty_epoch_changes_nothing(tmp_path):
    chain = fake.FakeChain()
    run = runner(chain, tmp_path)
    run.start(document())
    finish(run, chain)
    applied = chain.read_applied_weights(NETUID)
    quiet = runner(chain, tmp_path / "empty")
    state = quiet.start(document(weights=[{"uid": 1, "weight": "0"}, {"uid": 2, "weight": "0"}]))
    assert state["phase"] == crw.SKIPPED_EMPTY
    before_calls = len(chain.calls)
    assert quiet.step().phase == crw.SKIPPED_EMPTY
    chain.advance(60)  # three epochs pass with no commit
    assert len(chain.calls) == before_calls
    assert chain.empty_epochs >= 2
    assert chain.read_applied_weights(NETUID) == applied


def test_a_chain_without_commit_reveal_is_refused_and_nothing_is_sent(tmp_path):
    chain = fake.FakeChain(commit_reveal_enabled=False)
    run = runner(chain, tmp_path)
    run.start(document())
    with pytest.raises(crw.CommitRevealError, match="CHAIN_COMMIT_REVEAL_NOT_ENABLED"):
        run.step()
    assert not [n for n, _ in chain.calls if n.startswith("submit_")]
    with pytest.raises(crw.SubmitRejected, match="COMMIT_REVEAL_DISABLED"):
        chain.submit_hash_commit(NETUID, 0, "x")


def test_max_steps_guard(tmp_path):
    chain = fake.FakeChain(rate_limit_blocks=10 ** 6)
    chain.last_update_block = chain.block
    run = runner(chain, tmp_path)
    run.start(document())
    with pytest.raises(crw.CommitRevealError, match="MAX_STEPS_EXCEEDED"):
        run.run_until_terminal(lambda _b: None, max_steps=3)


# --------------------------------------------------------- the SDK's own functions
def test_pinned_sdk_and_mode_choice():
    assert importlib.metadata.version("bittensor") == crw.SDK_VERSION == "11.1.0"
    import bittensor.intents.weights as sdk_weights
    assert sdk_weights.DEFAULT_COMMIT_REVEAL_VERSION == crw.COMMIT_REVEAL_VERSION
    # the SDK's single weight intent builds the timelocked commit when commit-reveal is on
    assert "_build_timelocked" in dir(sdk_weights) and hasattr(sdk_weights, "RevealWeights")


class SdkSubstrate:
    """Answers the storage reads the SDK's timelocked builder makes, at one block."""

    def __init__(self, state):
        self.state, self.composed = state, None

    async def block_number(self):
        return self.state.block

    async def block_hash(self, number):
        return "0xhash"

    async def block_time(self):
        return self.state.block_time

    async def query(self, container, name, *rest, block_hash=None):
        s = self.state
        return {"Tempo": s.tempo, "RevealPeriodEpochs": s.reveal_period_epochs,
                "LastEpochBlock": s.last_epoch_block, "PendingEpochAt": s.pending_epoch_at,
                "SubnetEpochIndex": s.subnet_epoch_index,
                "BlocksSinceLastStep": s.blocks_since_last_step}[name]

    async def compose(self, call):
        self.composed = call
        return call


def chain_state():
    return crw.ChainState(netuid=NETUID, block=5000, tempo=360, reveal_period_epochs=1,
                          commit_reveal_enabled=True, rate_limit_blocks=1, last_update_block=0,
                          last_epoch_block=4900, pending_epoch_at=0, subnet_epoch_index=13,
                          blocks_since_last_step=100, block_time=12.0)


def test_payload_arguments_equal_the_sdk_intent_arguments(monkeypatch):
    import bittensor_core
    from bittensor.intents import weights as sdk_weights
    captured = []

    def capture(**kwargs):
        captured.append(kwargs)
        return b"payload", 4242

    monkeypatch.setattr(bittensor_core, "get_encrypted_commit_v2", capture)
    state = chain_state()
    substrate = SdkSubstrate(state)
    built = asyncio.run(sdk_weights._build_timelocked(
        substrate, HOTKEY_PK, NETUID, 0, ROW_UIDS, ROW_VALUES, 0,
        sdk_weights.DEFAULT_COMMIT_REVEAL_VERSION))
    ours = crw.build_timelocked_commit(state, ROW_UIDS, ROW_VALUES, hotkey_public_key=HOTKEY_PK)
    assert len(captured) == 2 and captured[0] == captured[1]
    assert ours.commit_bytes == b"payload" and ours.reveal_round == 4242
    call = substrate.composed
    assert call.params["commit"] == ours.commit_bytes
    assert call.params["reveal_round"] == ours.reveal_round
    assert call.params["commit_reveal_version"] == ours.commit_reveal_version
    assert call.params["netuid"] == ours.netuid and call.params["mecid"] == ours.mecid
    assert built.extras["reveal_round"] == ours.reveal_round


def test_real_sdk_payload_has_a_future_reveal_round():
    from bittensor import timelock
    state = chain_state()
    commit = crw.build_timelocked_commit(state, ROW_UIDS, ROW_VALUES,
                                         hotkey_public_key=HOTKEY_PK)
    assert isinstance(commit.commit_bytes, bytes) and len(commit.commit_bytes) > 100
    assert commit.reveal_round > timelock.current_round()
    other = crw.build_timelocked_commit(state, ROW_UIDS, ROW_VALUES,
                                        hotkey_public_key=HOTKEY_PK)
    assert other.commit_bytes != commit.commit_bytes  # encryption is randomised
    with pytest.raises(crw.CommitRevealError, match="HOTKEY_PUBLIC_KEY_MUST_BE_32_BYTES"):
        crw.build_timelocked_commit(state, ROW_UIDS, ROW_VALUES, hotkey_public_key=b"short")


def test_drand_reveal_block_estimate_uses_the_sdk_round_time():
    from bittensor import timelock
    target = timelock.round_at("2026-12-01T00:00:00Z")
    reveal_ts = timelock.reveal_time(target).timestamp()
    assert crw.drand_reveal_block(target, block=1000, now_ts=reveal_ts - 120) == 1010
    assert crw.drand_reveal_block(target, block=1000, now_ts=reveal_ts + 5) == 1000
    assert crw.drand_reveal_block(target, block=1000, now_ts=reveal_ts - 121) == 1011


# ----------------------------------------------- review items: false reveal, double commit
def test_a_row_equal_to_the_previous_row_is_not_a_reveal_until_the_chain_applies_it(tmp_path):
    chain = fake.FakeChain()
    first = runner(chain, tmp_path / "one")
    first.start(document())
    assert finish(first, chain).phase == crw.REVEALED
    applied_at = chain.read_applied_block(NETUID)
    chain.advance(3)
    second = runner(chain, tmp_path / "two", reveal_grace_blocks=3)
    second.start(document())  # the same row again
    chain.drop_next_reveal()
    result = finish(second, chain)
    assert result.phase == crw.OVERDUE  # the old row matched, but nothing new was applied
    assert chain.read_applied_block(NETUID) == applied_at


def test_a_repeated_row_is_observed_once_the_chain_applies_it_again(tmp_path):
    chain = fake.FakeChain()
    for name in ("one", "two"):
        run = runner(chain, tmp_path / name)
        run.start(document())
        assert finish(run, chain).phase == crw.REVEALED
        chain.advance(3)
    assert len(chain.weights_log) == 2


def test_the_runner_waits_for_confirmation_before_replanning_a_commit(tmp_path):
    chain = fake.FakeChain(start_block=107)  # epoch 32 ends at block 109
    chain.crash_after("submit_hash_commit")
    first = runner(chain, tmp_path, crw.MODE_SALTED, commit_margin_blocks=0)
    first.start(document())
    with pytest.raises(fake.SimulatedCrash):
        first.step()
    fresh = fake.FakeChain()
    fresh.block = 110  # next epoch, but only 3 blocks after planning at 107
    waiting = runner(fresh, tmp_path, crw.MODE_SALTED, commit_confirm_blocks=5,
                     commit_margin_blocks=0)
    result = waiting.step()
    assert result.action == "WAIT_COMMIT_CONFIRMATION" and result.wait_until_block == 112
    assert not [n for n, _ in fresh.calls if n.startswith("submit_")]


def test_an_abandoned_commit_that_lands_later_is_detected(tmp_path):
    chain = fake.FakeChain()
    chain.crash_after("submit_hash_commit")
    first = runner(chain, tmp_path, crw.MODE_SALTED)
    first.start(document())
    with pytest.raises(fake.SimulatedCrash):
        first.step()
    state = json.loads((tmp_path / "state.json").read_text())
    old_id = state["commit"]["commit_id"]
    other = fake.FakeChain()
    other.block = 112
    second = runner(other, tmp_path, crw.MODE_SALTED)
    assert second.step().phase == crw.COMMITTED
    other._hash_commits[old_id] = fake._HashCommit(100, 32)  # the old commit shows up late
    result = second.step()
    assert result.phase == crw.FAILED and result.action == "DOUBLE_COMMIT_DETECTED"


def test_a_current_row_equal_to_the_wanted_row_does_not_confirm_a_reveal_after_restart(tmp_path):
    chain = fake.FakeChain()
    chain.crash_after("submit_reveal")
    first = runner(chain, tmp_path, crw.MODE_SALTED)
    first.start(document())
    first.step()
    chain.advance_to(112)
    with pytest.raises(fake.SimulatedCrash):
        first.step()
    # undo the chain-side record of this commit but leave an identical row applied
    # (an earlier run of the same row): equality alone must not mark this commit revealed
    state = json.loads((tmp_path / "state.json").read_text())
    chain._hash_commits[state["commit"]["commit_id"]].revealed = False
    second = runner(chain, tmp_path, crw.MODE_SALTED)
    result = second.step()
    assert result.action == "REVEALED"  # sent again; not taken on the strength of the row
    assert [n for n, _ in chain.calls].count("submit_reveal") == 2
