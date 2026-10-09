# Guide format and runner

A guide is one markdown file under `docs/guides/`. The text is for the reader. The fenced
blocks are also instructions to `scripts/run_guide.py`, which runs every command in a temporary
clone and compares the output with the output the guide shows. A guide whose commands or output
drift fails the build, so the guide the reader sees is the guide that was tested.

```bash display
uv run python scripts/run_guide.py docs/guides/*.md            # steps not marked network
uv run python scripts/run_guide.py --network docs/guides/*.md  # also the network steps
uv run python scripts/run_guide.py --list docs/guides/*.md     # parse and lint, run nothing
```

## Blocks

A command is a fenced block whose info string contains the word `step`:

````markdown
```bash step id=install timeout=900 exit=0,3 network
uv sync --locked --extra transport
```
````

| Attribute | Meaning |
| --- | --- |
| `id=NAME` | Name shown in the report. Letters, digits, `.`, `_`, `-`; unique in the file. Default `step-N`. |
| `timeout=N` | Seconds before the step is killed and reported as TIMEOUT. Default 300, at most 1800. |
| `exit=A,B` | Accepted exit codes. Default `0`. |
| `network` | The step reads the network. It runs only with `--network`; otherwise it is reported SKIP. |
| `silent` | The step must print nothing. |
| `ignore` | The output is not compared (the exit code still is). |
| `requires-valkey` | The step needs a replay store. The runner starts a private `valkey-server` or `redis-server` from PATH on a Unix socket for the run and gives the step its address in `SN87_VALKEY_URL`. With none on PATH the step is SKIP, or FAIL when `SN87_GUIDE_REQUIRE_VALKEY` is set (CI sets it). |
| `display` | On a block with no `step`: the block is shown to the reader and never run. |

The block after a step that carries `expect` in its info string is the expected output. Each line
is one of:

- a literal line, compared exactly (trailing spaces ignored);
- `re: PATTERN`, a regular expression that must match the whole line;
- `...`, any number of lines, including none.

Without `...` the output must match line for line, and extra lines are drift. A step needs an
`expect` block, or the flag `silent` or `ignore`. A shell block (`bash`, `sh`, `shell`, `zsh`,
`shell-session`, `console`, `fish`, `terminal`), and a block with no language whose first line
starts with `$ `, that is neither a step nor marked `display` is an error, wherever it sits (also
in lists and block quotes): every command a reader is asked to run is run. A guide with no
steps is an error too, unless it carries the line `<!-- guide: no-steps -->`.

Output is standard output and standard error together, with colour codes removed. The scratch
home directory prints as `~`.

## Where a step runs

- The runner copies the tree it belongs to (tracked files and untracked files that git does not
  ignore) into a temporary directory and commits the copy there. It maps the public repository
  URL to that copy, so the guide's literal `git clone https://github.com/...` clones the tree
  under test. It does not fetch the repository from the network.
- `HOME` and `TMPDIR` point inside the temporary directory, which starts as the working
  directory. The working directory carries over from one step to the next, so `cd` works as in a
  terminal. The environment holds `PATH` and a few locale and uv settings; tokens and keys of the
  caller are not passed on.
- A step without `network` is run without network access intended: it gets `UV_OFFLINE=1` and a
  proxy that refuses connections, so uv and well-behaved clients work from the local package cache, using the Python that runs the runner (`UV_PYTHON`). The package install step therefore needs a warm uv cache
  (CI runs `uv sync` first). The two uv cache directories are the only place outside the
  temporary directory that a tool may touch.
- A step may start a server in the background, if it sends the server's output to a file and
  stops it before the block ends. Whatever a step leaves running in its process group is killed
  when the step ends. Offline steps can reach `127.0.0.1`, `localhost` and `::1`; every other
  address goes to the dead proxy.
- The runner writes only inside its temporary directory and removes it at the end (`--keep`
  leaves it). The one exception is the private replay store of a `requires-valkey` step, whose
  socket lives in a short directory under `/tmp` (socket paths are limited in length); the runner
  stops the server and removes that directory at the end.

This is hygiene, not a sandbox. A guide is code its author wrote, like a CI script, and runs with
the privileges of whoever runs it. Do not run a guide you did not review.

## Generated figures

A guide does not copy run counts, run ids or block numbers by hand. Blocks that depend on the
attestation file sit between `<!-- BEGIN STATUS:NAME -->` and `<!-- END STATUS:NAME -->`
comments and are produced by `scripts/render_status.py` (`--write` rewrites them, `--check`
fails when they drift; a test runs the check). The version a reader is testing comes from
`git rev-parse` in a step, not from text.

## CI

`.github/workflows/ci.yml` runs the steps not marked `network` on Linux and on macOS as the jobs `guides` and
`guides-macos`. Both build the pinned Valkey server first and set `SN87_GUIDE_REQUIRE_VALKEY`, so
the `requires-valkey` steps run there and a missing server fails instead of skipping. The `network` steps run in a separate job, `guides-network`, that is not a required
check, so that an unreachable test node cannot block a merge.
