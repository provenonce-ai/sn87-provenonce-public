#!/usr/bin/env python3
"""Run the commands of a guide in an isolated temporary clone and compare their output.

  uv run python scripts/run_guide.py docs/guides/*.md             # offline steps only
  uv run python scripts/run_guide.py --network docs/guides/*.md   # also the steps marked network
  uv run python scripts/run_guide.py --list docs/guides/*.md      # parse and lint, run nothing

A guide is a markdown file. The text is for the reader; the fenced blocks are for this runner.
The format is described in docs/protocol/guide-format.md. In short:

  * A block whose info string is ``<lang> step [id=..] [timeout=N] [exit=0,3] [network]
    [silent|ignore]`` is a command. It runs with ``bash -e -o pipefail``. The working directory
    carries over from one step to the next, as in a terminal.
  * The next ``<lang> expect`` block is the expected output of that step. Each line is a literal
    line, ``re: <regex>`` (full match of the line) or ``...`` (any number of lines, including
    none). Without ``...`` the output must match line for line.
  * Steps marked ``network`` run only with ``--network``; they are reported as skipped otherwise.
  * Steps marked ``requires-valkey`` get a private replay store: a ``valkey-server`` or
    ``redis-server`` from PATH, started on a Unix socket for the run, its URL in the
    environment variable ``SN87_VALKEY_URL``. With no server on PATH they are skipped, or they
    fail when ``SN87_GUIDE_REQUIRE_VALKEY`` is set (CI sets it).

Isolation. The runner copies the tree it belongs to (tracked and untracked files that git does
not ignore) into a temporary directory, commits the copy there and maps the public repository
URL to that copy, so a literal ``git clone https://github.com/...`` in a guide clones the tree
under test, not the network. Every step runs with a scratch ``HOME`` and ``TMPDIR`` inside the
temporary directory and a minimal environment (no tokens, no keys). Steps that are not marked
``network`` also get ``UV_OFFLINE=1`` and a dead proxy, so they work from the local package
cache only, and ``UV_PYTHON`` names the interpreter the runner itself runs under. The two cache
locations of uv are the one place outside the temporary directory
that a tool may touch. This is hygiene, not a sandbox: a guide is code that its author wrote,
like a CI script, and runs with the privileges of the caller.

Exit code: 0 all steps passed (skipped steps do not fail), 1 a step failed, 2 a usage or guide
format error. Reads and writes only the temporary directory it creates, plus the uv caches.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE_URLS = ("https://github.com/provenonce-ai/sn87-provenonce-public",
               "https://github.com/provenonce-ai/sn87-provenonce-public.git")
SHELL_LANGS = {"bash", "sh", "shell", "zsh", "console", "shell-session", "shellsession",
               "sh-session", "fish", "terminal", "shellscript"}
NO_STEPS_MARK = "<!-- guide: no-steps -->"
DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 1800
MAX_OUTPUT = 2_000_000
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
             "dist", "build", "node_modules"}
STEP_FLAGS = {"step", "network", "silent", "ignore", "display", "requires-valkey"}
VALKEY_BINARIES = ("valkey-server", "redis-server")
# Names of environment variables, spelled in two pieces so that a secret scanner does not read
# the name of a variable as a credential.
STORE_URL_ENV = "SN87_" + "VALKEY_URL"
REQUIRE_STORE_ENV = "SN87_GUIDE_" + "REQUIRE_VALKEY"
STEP_KEYS = {"id", "timeout", "exit"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Fences are found at any indent and inside block quotes, so a command in a list item is seen.
FENCE = re.compile(r"^(?P<indent>[ \t>]*)(?P<fence>`{3,}|~{3,})\s*(?P<info>.*)$")
CWD_TRAP = 'trap \'pwd -P > "$SN87_GUIDE_CWD_FILE"\' EXIT\n'


class GuideError(ValueError):
    """The guide file does not follow the format."""


@dataclass
class Item:
    kind: str  # "literal", "regex" or "gap"
    text: str
    pattern: re.Pattern | None = None

    def matches(self, line: str) -> bool:
        if self.kind == "literal":
            return line == self.text
        return self.kind == "regex" and self.pattern.fullmatch(line) is not None

    def display(self) -> str:
        return {"literal": self.text, "regex": "re: " + self.text, "gap": "..."}[self.kind]


@dataclass
class Step:
    id: str
    command: str
    line: int
    timeout: int = DEFAULT_TIMEOUT
    exit_codes: tuple[int, ...] = (0,)
    network: bool = False
    silent: bool = False
    ignore: bool = False
    requires_valkey: bool = False
    expect: list[Item] | None = None
    expect_line: int = 0


@dataclass
class Guide:
    path: Path
    steps: list[Step] = field(default_factory=list)
    display_blocks: int = 0


def _parse_info(info: str, line: int) -> tuple[str, dict[str, str], set[str]]:
    try:
        tokens = shlex.split(info)
    except ValueError as err:
        raise GuideError(f"line {line}: bad info string {info!r}: {err}") from None
    lang = tokens[0].lower() if tokens and "=" not in tokens[0] else ""
    if lang in ("step", "expect", "display"):
        lang = ""
    rest = tokens[1:] if tokens and tokens[0].lower() == lang else tokens
    keys: dict[str, str] = {}
    flags: set[str] = set()
    for token in rest:
        if "=" in token:
            key, value = token.split("=", 1)
            keys[key] = value
        else:
            flags.add(token)
    return lang, keys, flags


def parse_expect(body: list[str], line: int) -> list[Item]:
    items: list[Item] = []
    for offset, raw in enumerate(body):
        text = raw.rstrip()
        if text.strip() == "...":
            if not items or items[-1].kind != "gap":
                items.append(Item("gap", "..."))
        elif text.startswith("re:"):
            source = text[3:]
            source = source[1:] if source.startswith(" ") else source
            try:
                items.append(Item("regex", source, re.compile(source)))
            except re.error as err:
                raise GuideError(f"line {line + offset}: bad regex {source!r}: {err}") from None
        else:
            items.append(Item("literal", text))
    return items


def parse_guide(text: str, path: Path) -> Guide:
    """Parse a guide. Raises GuideError on the first format problem."""
    guide = Guide(path)
    lines = text.splitlines()
    index = 0
    open_step: Step | None = None  # the latest step still waiting for its expect block
    seen_ids: set[str] = set()
    while index < len(lines):
        match = FENCE.match(lines[index])
        if not match:
            index += 1
            continue
        fence, info, start = match.group("fence"), match.group("info"), index + 1
        prefix = match.group("indent")
        body: list[str] = []
        index += 1
        while index < len(lines):
            close = FENCE.match(lines[index])
            if close and close.group("fence")[0] == fence[0] and len(close.group("fence")) >= len(
                    fence) and not close.group("info").strip():
                break
            line = lines[index]
            body.append(line[len(prefix):] if line.startswith(prefix) else line.lstrip(" \t>"))
            index += 1
        else:
            raise GuideError(f"line {start}: code block opened here is never closed")
        index += 1
        lang, keys, flags = _parse_info(info, start)
        if "expect" in flags:
            if open_step is None:
                raise GuideError(f"line {start}: expect block without a step before it")
            unknown = (flags - {"expect"}) | set(keys)
            if unknown:
                raise GuideError(f"line {start}: expect block takes no attribute {sorted(unknown)}")
            open_step.expect = parse_expect(body, start + 1)
            open_step.expect_line = start
            open_step = None
            continue
        if "step" in flags:
            unknown = (flags - STEP_FLAGS) | (set(keys) - STEP_KEYS)
            if unknown:
                raise GuideError(f"line {start}: unknown step attribute {sorted(unknown)}")
            command = "\n".join(body).strip("\n")
            if not command.strip():
                raise GuideError(f"line {start}: empty step")
            step_id = keys.get("id") or f"step-{len(guide.steps) + 1}"
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", step_id) or step_id in seen_ids:
                raise GuideError(f"line {start}: step id {step_id!r} is invalid or repeated")
            seen_ids.add(step_id)
            try:
                timeout = int(keys.get("timeout", DEFAULT_TIMEOUT))
                codes = tuple(int(c) for c in keys.get("exit", "0").split(","))
            except ValueError:
                raise GuideError(f"line {start}: timeout and exit must be integers") from None
            if not 1 <= timeout <= MAX_TIMEOUT:
                raise GuideError(f"line {start}: timeout must be 1..{MAX_TIMEOUT} seconds")
            step = Step(step_id, command, start, timeout, codes, "network" in flags,
                        "silent" in flags, "ignore" in flags, "requires-valkey" in flags)
            if step.silent and step.ignore:
                raise GuideError(f"line {start}: silent and ignore exclude each other")
            if open_step is not None:
                _need_expect(open_step)
            guide.steps.append(step)
            open_step = step
            continue
        if "display" in flags:
            guide.display_blocks += 1
            continue
        first = next((b.strip() for b in body if b.strip()), "")
        if lang in SHELL_LANGS or (not lang and first.startswith("$ ")):
            raise GuideError(
                f"line {start}: shell block is neither a step nor marked display; "
                "every command in a guide must be run by the runner")
    for step in guide.steps:
        _need_expect(step)
    if not guide.steps and NO_STEPS_MARK not in text:
        raise GuideError("the guide has no steps; add some, or opt out with the line "
                         f"{NO_STEPS_MARK}")
    return guide


def _need_expect(step: Step) -> None:
    if step.expect is None and not (step.silent or step.ignore):
        raise GuideError(f"line {step.line}: step {step.id!r} needs an expect block, "
                         "or the flag silent (no output) or ignore (output not compared)")
    if step.expect is not None and (step.silent or step.ignore):
        raise GuideError(f"line {step.line}: step {step.id!r} has an expect block and "
                         "the flag silent or ignore")


# ---------------------------------------------------------------------------------------------
# Comparing output


def match_output(items: list[Item], actual: list[str]) -> bool:
    """Whether the actual lines match the expected items, with ``...`` as a wildcard."""
    memo: dict[tuple[int, int], bool] = {}

    def go(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(items):
            result = j == len(actual)
        elif items[i].kind == "gap":
            result = any(go(i + 1, k) for k in range(j, len(actual) + 1))
        else:
            result = j < len(actual) and items[i].matches(actual[j]) and go(i + 1, j + 1)
        memo[key] = result
        return result

    return go(0, 0)


def output_diff(items: list[Item], actual: list[str]) -> str:
    """A unified diff from the best-effort alignment of the expected items to the output."""
    view: list[str] = []
    position = 0
    after_gap = False
    for item in items:
        if item.kind == "gap":
            after_gap = True
            continue
        found = next((k for k in range(position, len(actual)) if item.matches(actual[k])), None)
        if found is None:
            view.append(item.display())
            continue
        if after_gap:
            view.extend(actual[position:found])
        view.append(actual[found])
        position = found + 1
        after_gap = False
    if after_gap:
        view.extend(actual[position:])
    diff = difflib.unified_diff(view, actual, "expected", "actual", lineterm="", n=2)
    return "\n".join(diff)


def normalise(raw: bytes, home: Path, tmp: Path) -> list[str]:
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    text = ANSI.sub("", text)
    for real, label in ((home, "~"), (tmp, "<TMP>")):
        for variant in {str(real), str(real.resolve())}:
            text = text.replace(variant, label)
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


# ---------------------------------------------------------------------------------------------
# Running


def snapshot_files(source: Path) -> list[str]:
    """Relative paths of the tree to copy: git's tracked and unignored files, else a walk."""
    if (source / ".git").exists():
        out = subprocess.run(["git", "-C", str(source), "ls-files", "-co", "--exclude-standard",
                              "-z"], capture_output=True, check=True).stdout
        names = [n for n in out.decode("utf-8").split("\0") if n]
        return [n for n in names if (source / n).exists() or (source / n).is_symlink()]
    found = []
    for base, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        found += [str((Path(base) / f).relative_to(source)) for f in sorted(files)]
    return found


def make_origin(source: Path, origin: Path) -> None:
    """Copy the tree under test into ``origin`` and commit it there."""
    for name in snapshot_files(source):
        src, dst = source / name, origin / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
        else:
            shutil.copy2(src, dst)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(origin.parent),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    ident = ["-c", "user.name=guide", "-c", "user.email=guide@users.noreply.github.com",
             "-c", "commit.gpgsign=false"]
    for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                 [*ident, "commit", "-q", "-m", "tree under test"]):
        subprocess.run(["git", "-C", str(origin), *args], env=env, check=True,
                       capture_output=True)


def _uv_dir(kind: str) -> str | None:
    try:
        out = subprocess.run(["uv", kind, "dir"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def step_env(home: Path, tmp: Path, origin: Path, online: bool, uv_dirs: dict[str, str],
             valkey_url: str | None = None) -> dict:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "TMPDIR": str(tmp / "tmp"),
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONUTF8": "1",
        "LC_ALL": "C",
        "UV_NO_PROGRESS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": str(len(REMOTE_URLS)),
        "SN87_GUIDE_CWD_FILE": str(tmp / "state" / "cwd"),
    }
    for number, url in enumerate(REMOTE_URLS):
        # file:// makes git use its transport, not the local-clone shortcut that hard-links or
        # copies the object files out of the origin
        env[f"GIT_CONFIG_KEY_{number}"] = f"url.{origin.as_uri()}.insteadOf"
        env[f"GIT_CONFIG_VALUE_{number}"] = url
    # The clone's uv sync must pick the interpreter whose wheels are in the warm cache, not
    # whatever other Python the machine has (a runner can carry a newer system Python).
    env["UV_PYTHON"] = getattr(sys, "_base_executable", None) or sys.executable
    if uv_dirs.get("cache"):
        env["UV_CACHE_DIR"] = uv_dirs["cache"]
    if uv_dirs.get("python"):
        env["UV_PYTHON_INSTALL_DIR"] = uv_dirs["python"]
    if online:
        for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "HTTPS_PROXY",
                     "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy"):
            if name in os.environ:
                env[name] = os.environ[name]
    else:
        env.update({"UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never",
                    "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
                    "ALL_PROXY": "http://127.0.0.1:9",
                    # Loopback stays reachable: a step may talk to a server it started itself.
                    "NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1"})
    if valkey_url:
        env[STORE_URL_ENV] = valkey_url
    return env


def _ping_unix(path: Path) -> bool:
    """RESP PING over a Unix socket: True when the server answers PONG."""
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect(str(path))
            sock.sendall(b"PING\r\n")
            return sock.recv(16).startswith(b"+PONG")
        except OSError:
            return False


@contextlib.contextmanager
def private_valkey():
    """Start a private replay store on a Unix socket and yield its URL; yield None when no
    ``valkey-server`` or ``redis-server`` is on PATH (or it does not start). The server does not
    persist anything and is stopped, and its directory removed, when the block ends."""
    binary = next((found for name in VALKEY_BINARIES if (found := shutil.which(name))), None)
    if binary is None:
        yield None
        return
    # A short path: Unix socket paths are limited to about 100 bytes.
    directory = Path(tempfile.mkdtemp(prefix="sn87-gv-", dir="/tmp")).resolve()
    sock = directory / "store.sock"
    process = subprocess.Popen(
        [binary, "--port", "0", "--unixsocket", str(sock), "--unixsocketperm", "700",
         "--save", "", "--appendonly", "no", "--dir", str(directory)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            if _ping_unix(sock):
                yield "unix://" + str(sock)
                break
            time.sleep(0.05)
        else:
            yield None
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if directory.name.startswith("sn87-gv-") and directory.parent == Path("/tmp").resolve():
            shutil.rmtree(directory, ignore_errors=True)


@dataclass
class Result:
    step: Step
    status: str  # PASS, FAIL, SKIP, TIMEOUT
    seconds: float = 0.0
    exit_code: int | None = None
    detail: str = ""


def run_step(step: Step, cwd: Path, env: dict, home: Path, tmp: Path) -> Result:
    script = CWD_TRAP + step.command + "\n"
    started = time.monotonic()
    proc = subprocess.Popen(["bash", "-e", "-o", "pipefail", "-c", script], cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    try:
        raw, _ = proc.communicate(timeout=step.timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        raw, _ = proc.communicate()
        lines = normalise(raw[-MAX_OUTPUT:], home, tmp)
        tail = "\n".join(lines[-15:])
        return Result(step, "TIMEOUT", time.monotonic() - started, None,
                      f"no exit within {step.timeout} s; last output:\n{tail}")
    seconds = time.monotonic() - started
    # A step may start a server in the background (with its output sent to a file). Whatever it
    # leaves behind in its process group is stopped now, so no step outlives its block.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    lines = normalise(raw[:MAX_OUTPUT], home, tmp)
    problems = []
    if proc.returncode not in step.exit_codes:
        problems.append(f"exit code {proc.returncode}, expected "
                        f"{' or '.join(str(c) for c in step.exit_codes)}; last output:\n" +
                        "\n".join(lines[-15:]))
    if step.silent and lines:
        problems.append("expected no output, got:\n" + "\n".join(lines[-15:]))
    elif step.expect is not None and not match_output(step.expect, lines):
        problems.append("output drifted from the expect block:\n" +
                        (output_diff(step.expect, lines) or "(no line differs; check line order)"))
    return Result(step, "FAIL" if problems else "PASS", seconds, proc.returncode,
                  "\n".join(problems))


def run_guide(guide: Guide, source: Path, network: bool, keep: bool = False,
              out=None) -> list[Result]:
    """Run every step of the guide in a fresh temporary directory."""
    out = out or sys.stdout
    uv_dirs = {"cache": _uv_dir("cache"), "python": _uv_dir("python")}
    runnable = [s for s in guide.steps if network or not s.network]
    wants_store = any(s.requires_valkey for s in runnable)
    with private_valkey() if wants_store else contextlib.nullcontext() as valkey_url:
        return _run_steps(guide, source, runnable, valkey_url, keep, out, uv_dirs)


def _run_steps(guide: Guide, source: Path, runnable: list[Step], valkey_url: str | None,
               keep: bool, out, uv_dirs: dict[str, str | None]) -> list[Result]:
    results: list[Result] = []
    parent = Path(tempfile.gettempdir())
    tmp = Path(tempfile.mkdtemp(prefix="sn87-guide-", dir=parent)).resolve()
    try:
        home, origin = tmp / "home", tmp / "origin"
        for sub in (home, tmp / "tmp", tmp / "state", origin):
            sub.mkdir()
        if runnable:
            make_origin(source, origin)
        cwd = home
        for step in guide.steps:
            if step not in runnable:
                result = Result(step, "SKIP", detail="needs the network; run with --network")
            elif step.requires_valkey and valkey_url is None:
                reason = ("needs a replay store: put valkey-server or redis-server on PATH "
                          "(the step gets it as " + STORE_URL_ENV + ")")
                strict = bool(os.environ.get(REQUIRE_STORE_ENV))
                result = Result(step, "FAIL" if strict else "SKIP",
                                detail=reason + (f" ({REQUIRE_STORE_ENV} is set)" if strict
                                                 else ""))
            else:
                env = step_env(home, tmp, origin, online=step.network, uv_dirs=uv_dirs,
                               valkey_url=valkey_url if step.requires_valkey else None)
                result = run_step(step, cwd, env, home, tmp)
                moved = tmp / "state" / "cwd"
                if moved.exists():
                    candidate = Path(moved.read_text(encoding="utf-8").strip() or str(cwd))
                    if candidate.is_dir():
                        cwd = candidate
            results.append(result)
            _report(guide, result, out)
    finally:
        if keep:
            print(f"kept temporary directory {tmp}", file=out)
        else:
            _discard(tmp, parent)
    return results


def _discard(tmp: Path, parent: Path) -> None:
    """Remove the temporary directory this run created, and nothing else."""
    if tmp.parent == parent.resolve() and tmp.name.startswith("sn87-guide-"):
        shutil.rmtree(tmp, ignore_errors=True)


def _report(guide: Guide, result: Result, out) -> None:
    step = result.step
    label = f"{result.status:7} {guide.path.name}:{step.line} {step.id}"
    if result.status in ("PASS", "FAIL", "TIMEOUT"):
        label += f" ({result.seconds:.1f} s)"
    print(label, file=out)
    if result.status in ("FAIL", "TIMEOUT", "SKIP") and result.detail:
        if result.status != "SKIP":
            print("  command:", file=out)
            for line in step.command.splitlines():
                print(f"    {line}", file=out)
        for line in result.detail.splitlines():
            print(f"  {line}", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("guides", nargs="+", type=Path)
    parser.add_argument("--network", action="store_true",
                        help="also run the steps marked network (they read the public test node)")
    parser.add_argument("--list", action="store_true", help="parse and lint only; run nothing")
    parser.add_argument("--source", type=Path, default=ROOT,
                        help="tree to copy for the run (default: the tree this script is in)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args(argv)
    guides = []
    for path in args.guides:
        try:
            guides.append(parse_guide(path.read_text(encoding="utf-8"), path))
        except (OSError, GuideError) as err:
            print(f"{path}: {err}", file=sys.stderr)
            return 2
    failed = 0
    skipped = 0
    for guide in guides:
        if args.list:
            print(f"{guide.path}: {len(guide.steps)} steps, "
                  f"{sum(s.network for s in guide.steps)} marked network, "
                  f"{guide.display_blocks} display blocks")
            continue
        print(f"== {guide.path}")
        results = run_guide(guide, args.source.resolve(), args.network, args.keep)
        failed += sum(r.status in ("FAIL", "TIMEOUT") for r in results)
        skipped += sum(r.status == "SKIP" for r in results)
        passed = sum(r.status == "PASS" for r in results)
        print(f"-- {guide.path.name}: {passed} passed, "
              f"{sum(r.status in ('FAIL', 'TIMEOUT') for r in results)} failed, "
              f"{sum(r.status == 'SKIP' for r in results)} skipped")
    if args.list:
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
