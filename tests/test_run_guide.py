"""The guide runner: pass, output drift, exit code drift, timeout, and its isolation rules."""

import importlib.util
import io
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None,
                                reason="the runner needs git and bash")


def _load():
    spec = importlib.util.spec_from_file_location("run_guide", ROOT / "scripts/run_guide.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rg = _load()

FENCE = "```"


def step(cmd, expect=None, flags="", lang="bash"):
    text = f"{FENCE}{lang} step {flags}\n{cmd}\n{FENCE}\n"
    if expect is not None:
        text += f"{FENCE}text expect\n{expect}\n{FENCE}\n"
    return text


@pytest.fixture()
def tree(tmp_path):
    src = tmp_path / "src-tree"
    src.mkdir()
    (src / "hello.txt").write_text("hello\n")
    (src / ".venv").mkdir()
    (src / ".venv" / "junk").write_text("not copied")
    return src


def run(text, tree, network=False):
    guide = rg.parse_guide(text, Path("fake.md"))
    out = io.StringIO()
    results = rg.run_guide(guide, tree, network, out=out)
    return results, out.getvalue()


def test_a_passing_guide(tree):
    text = "Prose.\n\n" + step("echo one; echo two", "one\ntwo") + step("true", flags="silent")
    results, _ = run(text, tree)
    assert [r.status for r in results] == ["PASS", "PASS"]


def test_output_drift_fails_with_a_diff(tree):
    results, out = run(step("echo one; echo 2", "one\ntwo"), tree)
    assert results[0].status == "FAIL"
    assert "-two" in out and "+2" in out and "output drifted" in out


def test_exit_code_drift_fails(tree):
    results, out = run(step("echo ok; exit 3", "ok"), tree)
    assert results[0].status == "FAIL"
    assert "exit code 3, expected 0" in out
    results, _ = run(step("echo ok; exit 3", "ok", flags="exit=0,3"), tree)
    assert results[0].status == "PASS"


def test_timeout_is_reported_and_kills_the_step(tree):
    results, out = run(step("echo started; sleep 30", "started", flags="timeout=1"), tree)
    assert results[0].status == "TIMEOUT"
    assert "no exit within 1 s" in out and "started" in out


def test_wildcards_and_regexes(tree):
    text = step("printf 'a\\nb 12\\nc\\nd\\n'", "...\nre: b \\d+\n...\nd")
    assert run(text, tree)[0][0].status == "PASS"
    assert run(step("printf 'a\\nb x\\n'", "re: a\nre: b \\d+"), tree)[0][0].status == "FAIL"
    assert run(step("printf 'a\\nb\\n'", "a"), tree)[0][0].status == "FAIL"  # extra line


def test_network_steps_are_skipped_offline_and_run_with_the_flag(tree):
    text = step("echo net", "net", flags="network") + step("echo x", "x")
    results, _ = run(text, tree)
    assert [r.status for r in results] == ["SKIP", "PASS"]
    results, _ = run(text, tree, network=True)
    assert [r.status for r in results] == ["PASS", "PASS"]


def test_offline_steps_get_no_network_and_a_scratch_home(tree):
    text = step("echo $UV_OFFLINE $HTTPS_PROXY; cd ~; pwd", "re: 1 http://127.0.0.1:9\n~")
    assert run(text, tree)[0][0].status == "PASS"
    online = step("echo ${UV_OFFLINE:-unset}", "unset", flags="network")
    assert run(online, tree, network=True)[0][0].status == "PASS"


def test_environment_is_scrubbed(tree, monkeypatch):
    monkeypatch.setenv("SN87_SECRET_TOKEN", "leak")
    results, _ = run(step("echo \"[${SN87_SECRET_TOKEN:-}]\"", "[]"), tree)
    assert results[0].status == "PASS"


def test_working_directory_carries_over_and_the_tree_is_cloned(tree):
    base = "https://github.com/provenonce-ai/sn87-provenonce-public"
    text = (step("cd ~", flags="silent") + step(f"git clone {base}", "...")
            + step("cd sn87-provenonce-public", flags="silent")
            + step("cat hello.txt; ls -a | grep -c junk || true", "hello\n0"))
    results, out = run(text, tree)
    assert [r.status for r in results] == ["PASS"] * 4, out


def test_nothing_is_written_outside_the_temporary_directory(tree):
    before = sorted(p.name for p in tree.iterdir())
    temp_before = set(Path(rg.tempfile.gettempdir()).glob("sn87-guide-*"))
    text = step("echo data > made.txt; echo $TMPDIR > /dev/null; cat made.txt", "data")
    results, _ = run(text, tree)
    assert results[0].status == "PASS"
    assert sorted(p.name for p in tree.iterdir()) == before
    assert set(Path(rg.tempfile.gettempdir()).glob("sn87-guide-*")) == temp_before


def test_unannotated_shell_block_is_a_format_error():
    with pytest.raises(rg.GuideError, match="every command in a guide"):
        rg.parse_guide(f"{FENCE}bash\nls\n{FENCE}\n", Path("g.md"))
    guide = rg.parse_guide(f"{rg.NO_STEPS_MARK}\n{FENCE}bash display\nls\n{FENCE}\n",
                           Path("g.md"))
    assert guide.display_blocks == 1 and not guide.steps


@pytest.mark.parametrize("text", [
    f"{FENCE}shell-session\n$ ls\n{FENCE}\n",
    f"{FENCE}sh\nls\n{FENCE}\n",
    f"{FENCE}\n$ ls\n{FENCE}\n",
    f"- item\n\n    {FENCE}bash\n    ls\n    {FENCE}\n",
    f"> {FENCE}console\n> $ ls\n> {FENCE}\n",
    f"````markdown\n{FENCE}bash\nls\n{FENCE}\n````\n{FENCE}zsh\nls\n{FENCE}\n",
])
def test_every_shell_like_block_must_be_a_step_or_display(text):
    with pytest.raises(rg.GuideError, match="every command in a guide"):
        rg.parse_guide(text, Path("g.md"))


def test_a_step_inside_a_list_is_found_and_dedented():
    text = (f"1. Run it.\n\n   {FENCE}bash step\n   echo hi\n   {FENCE}\n"
            f"   {FENCE}text expect\n   hi\n   {FENCE}\n")
    guide = rg.parse_guide(text, Path("g.md"))
    assert [s.command for s in guide.steps] == ["echo hi"]
    assert guide.steps[0].expect[0].text == "hi"


def test_a_guide_with_no_steps_fails_unless_it_opts_out():
    with pytest.raises(rg.GuideError, match="no steps"):
        rg.parse_guide("Just prose.\n", Path("g.md"))
    assert rg.parse_guide(f"{rg.NO_STEPS_MARK}\nJust prose.\n", Path("g.md")).steps == []


def test_the_format_document_parses_and_runs_nothing():
    text = (ROOT / "docs/protocol/guide-format.md").read_text(encoding="utf-8")
    assert rg.parse_guide(text + rg.NO_STEPS_MARK, Path("f.md")).steps == []


@pytest.mark.parametrize("text,message", [
    (step("ls"), "needs an expect block"),
    (step("ls", "x", flags="silent"), "silent or ignore"),
    (f"{FENCE}text expect\nx\n{FENCE}\n", "without a step"),
    (step("ls", "x", flags="speed=3"), "unknown step attribute"),
    (step("ls", "re: (", flags=""), "bad regex"),
    (step("ls", "x", flags="timeout=0"), "timeout must be"),
    (step("ls", "x", flags="id=a") + step("ls", "x", flags="id=a"), "invalid or repeated"),
    (f"{FENCE}bash step\nls\n", "never closed"),
])
def test_format_errors(text, message):
    with pytest.raises(rg.GuideError, match=message):
        rg.parse_guide(text, Path("g.md"))


def test_the_command_line(tree, tmp_path, capsys):
    guide = tmp_path / "g.md"
    guide.write_text(step("echo hi", "hi"))
    assert rg.main(["--source", str(tree), str(guide)]) == 0
    guide.write_text(step("echo hi", "bye"))
    assert rg.main(["--source", str(tree), str(guide)]) == 1
    assert "output drifted" in capsys.readouterr().out
    guide.write_text(f"{FENCE}bash\nls\n{FENCE}\n")
    assert rg.main(["--list", str(guide)]) == 2
    guide.write_text("prose only\n")
    assert rg.main(["--list", str(guide)]) == 2


DISPLAY_ALLOWED = {"miner-guide.md": 1}


def test_shipped_guides_parse_and_have_a_marked_network_step():
    for path in sorted((ROOT / "docs" / "guides").glob("*.md")):
        guide = rg.parse_guide(path.read_text(encoding="utf-8"), path)
        # a criteria page without commands says so with the no-steps line
        assert guide.steps or rg.NO_STEPS_MARK in path.read_text(encoding="utf-8"), path
        # A shipped guide leaves no command unrun, except the one container command that the
        # miner guide shows for a replay store the runner replaces with a private one.
        assert guide.display_blocks == DISPLAY_ALLOWED.get(path.name, 0), path
    reviewer = rg.parse_guide((ROOT / "docs/guides/reviewer-test-guide.md").read_text(), Path("r"))
    assert {s.id for s in reviewer.steps if s.network} == {"verify", "tamper-check"}
    miner = rg.parse_guide((ROOT / "docs/guides/miner-guide.md").read_text(), Path("m"))
    assert {s.id for s in miner.steps if s.network} == {"burn-read"}
    assert {s.id for s in miner.steps if s.requires_valkey} == {
        "store-binary", "serve-check", "serve-signed"}


# ------------------------------------------------------------------ requires-valkey and leftovers
needs_server = pytest.mark.skipif(
    not any(shutil.which(n) for n in rg.VALKEY_BINARIES),
    reason="valkey-server or redis-server is needed on PATH")


def test_requires_valkey_is_a_known_flag():
    guide = rg.parse_guide(step("echo x", "x", flags="requires-valkey"), Path("g.md"))
    assert guide.steps[0].requires_valkey


def test_requires_valkey_step_is_skipped_without_a_server_and_fails_when_required(
        tree, monkeypatch):
    monkeypatch.setattr(rg.shutil, "which", lambda name: None)
    text = step("echo x", "x", flags="requires-valkey") + step("echo y", "y")
    monkeypatch.delenv(rg.REQUIRE_STORE_ENV, raising=False)
    results, out = run(text, tree)
    assert [r.status for r in results] == ["SKIP", "PASS"]
    assert "valkey-server or redis-server" in out
    monkeypatch.setenv(rg.REQUIRE_STORE_ENV, "1")
    results, out = run(text, tree)
    assert [r.status for r in results] == ["FAIL", "PASS"]
    assert rg.REQUIRE_STORE_ENV + " is set" in out


@needs_server
def test_requires_valkey_step_gets_a_private_server_and_only_that_step(tree):
    check = ("test -S \"${SN87_VALKEY_URL#unix://}\" && echo socket "
             "&& python3 - <<'PY'\nimport os, socket\ns = socket.socket(socket.AF_UNIX)\n"
             "s.connect(os.environ['SN87_VALKEY_URL'][len('unix://'):])\ns.sendall(b'PING\\r\\n')\n"
             "print(s.recv(16).decode().strip())\nPY")
    text = (step(check, "socket\n+PONG", flags="requires-valkey")
            + step("echo \"[${SN87_VALKEY_URL:-}]\"", "[]"))
    before = set(Path("/tmp").glob("sn87-gv-*"))
    results, out = run(text, tree)
    assert [r.status for r in results] == ["PASS", "PASS"], out
    assert set(Path("/tmp").glob("sn87-gv-*")) == before, "the private server is cleaned up"


def test_loopback_is_not_sent_to_the_dead_proxy(tree):
    text = step("echo $NO_PROXY", "127.0.0.1,localhost,::1")
    assert run(text, tree)[0][0].status == "PASS"


def test_a_server_left_running_by_a_step_is_stopped_when_the_step_ends(tree, tmp_path):
    pid_file = tmp_path / "pid"
    text = step(f"sleep 60 > /dev/null 2>&1 &\necho $! > {pid_file}", flags="silent")
    results, _ = run(text, tree)
    assert results[0].status == "PASS"
    pid = int(pid_file.read_text())
    for _ in range(40):  # the dead process can stay listed for a moment until it is reaped
        try:
            rg.os.kill(pid, 0)
        except ProcessLookupError:
            return
        rg.time.sleep(0.1)
    raise AssertionError("the background process is still running")


def test_the_guides_clone_uses_git_transport_and_shares_no_files_with_the_origin(tree):
    """A clone by path copies or hard-links the origin's object files and can fail if they move
    underneath it (seen on macOS runners). The mapped URL is a file:// URL, so git serves the
    objects through its transport and the clone shares no file with the origin."""
    base = "https://github.com/provenonce-ai/sn87-provenonce-public"
    text = (step("cd ~", flags="silent") + step(f"git clone -q {base}", flags="silent")
            + step("find sn87-provenonce-public/.git/objects -type f -links +1 | wc -l | tr -d ' '",
                   "0"))
    results, out = run(text, tree)
    assert [r.status for r in results] == ["PASS"] * 3, out
