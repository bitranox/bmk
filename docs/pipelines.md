# Pipelines and stages

How a bmk command is built from stages, and how to change one.


Arguments after the target name are forwarded automatically (e.g. `make push fix login bug`).
Flags must go through `ARGS` (`make test ARGS="--verbose"`), since a bare `--verbose` would be
parsed by `make` itself.
Global options: `--traceback`, `--profile NAME`, `--set SECTION.KEY=VALUE`.

### Commit messages: use `MSG="..."`

`make push fix login bug` is fine for a plain one-line message. For anything else, use `MSG`:

```bash
make push MSG="fix(cli): subject line

Body with (parens), a ; and a literal $HOME - all of it safe."
```

`MSG` reaches bmk through the environment (`BMK_COMMIT_MESSAGE`), so the message is never
re-parsed and arrives byte for byte, newlines included. `git commit` turns the first line into
the subject and the rest into the body.

Do not pass a message in `ARGS="..."`. `ARGS` is expanded into the make recipe and handed to
`bash`, which parses your prose as code: `fix(cli): x` is a syntax error, `a; b` runs `b`, and a
backtick or `$(...)` executes. A newline in `ARGS` is rejected with an error, because make would
otherwise commit a truncated subject and then run the remainder as a command.

Every built-in command runs in cross-OS Python, so bmk works natively on Windows with no shell or PowerShell dependency. 
You still need a `make` implementation installed (e.g. [GnuWin32 Make](https://gnuwin32.sourceforge.net/packages/make.htm) or `choco install make`) to use the Makefile entry point.

- **Staged execution** - stages are grouped by order number. Stages run sequentially (fail-fast); stages sharing an order run in parallel.

  Example: `bmk test` executes the bundled test pipeline:

| Stage | Execution    | Scripts                                                                                                          |
|-------|--------------|------------------------------------------------------------------------------------------------------------------|
| 010   | sequential   | `update_deps`                                                                                                    |
| 020   | sequential   | `ruff_format_apply`                                                                                              |
| 030   | sequential   | `ruff_fix_apply`                                                                                                 |
| 040   | **parallel** | `ruff_format_check`, `ruff_lint`, `pyright`, `bandit`, `pip_audit`, `lint_imports`, `psscriptanalyzer`, `pytest` |
| 060   | sequential   | `shellcheck`                                                                                                     |

- **JSON-by-default output**  -  in JSON mode (the default), the stage runner captures all tool output and only displays it when a stage fails. On success, it emits a single JSON summary line (`{"result":"pass","stages":N,"scripts":N}`). Dependency checking runs silently, Makefile version updates are auto-accepted, and pytest uses `--tb=short -q --no-header`. Use `--human` on `test`/`testintegration` commands for full verbose output, or set `BMK_OUTPUT_FORMAT=text`. Note: `make test --human` does not work because Make intercepts `--` flags  -  use `make test-human` or `make th` instead.
- **Dependency isolation**  -  bmk and your project never share a dependency tree. bmk is installed once per machine, in uv's own tool dir, holding bmk's toolchain and nothing of yours. Your dependencies live in the project's own `.venv`, which bmk provisions and syncs from your `pyproject.toml`, and that is the environment your tests, pyright and pip-audit all run against. Because bmk's env contains none of your packages, one project's dependencies can never resolve against another's - or against bmk's. bmk is re-resolved on every `make`, so a new release is picked up automatically; both directories are disposable and gitignored.
- **Project venv, synced before every gate**  -  bmk creates the project's venv if absent and syncs it to `pyproject.toml` before any command that touches the Python environment. Installs and gates target that venv only  -  never bmk's own, never the venv active in your shell  -  so no project can install its dependencies into a shared environment it does not own. The sync removes packages the manifest dropped and re-resolves the rest, so a drifted venv cannot make pip-audit report CVEs the project does not actually resolve. Set `UV_PROJECT_ENVIRONMENT` to use a different path (e.g. `.venv-win` when one checkout is shared between operating systems), or `BMK_NO_VENV_SYNC=1` to skip provisioning. Packages installed into the venv by hand do not survive a sync. `clean` does not remove the venv  -  delete it by hand when you want it gone.
- **The venv stays out of git**  -  bmk gitignores the venv it creates (respecting any rule you already have) and, if git is tracking a venv, drops it from the index while leaving the files on disk. A tracked venv would otherwise show thousands of modified files after every sync.
- **The venv stays out of the type-check**  -  pyright's `exclude` REPLACES its defaults (`**/node_modules`, `**/__pycache__`, `**/.*`) rather than extending them, so a project that excludes anything of its own loses the rule that kept dot-directories out - and would then type-check bmk's venvs, thousands of files, in strict mode. bmk appends the venv names to `[tool.pyright].exclude` when they are missing, and leaves the config alone when there is no `exclude` key (the defaults already cover it) or an `include` list narrows the scope.
- **Built-in commands**  -  `test`, `build`, `clean`, `run`, `push`, `release`, `bump`, `coverage`, and more.
- **Custom commands**  -  `bmk custom <name>` runs a user-defined pipeline defined via a TOML overlay.
- **Per-project overrides** - define pipelines under `[tool.bmk.pipelines]` in `pyproject.toml` (or `bmk_makescripts/stages.toml`) to add, remove, or replace stages.
- **Layered configuration** with lib_layered_config (defaults -> app -> host -> user -> .env -> env).
- **Rich CLI output** styled with rich-click and structured logging via lib_log_rich.
- **Private repository dependencies**  -  PEP 440 direct references (`pkg @ git+https://...`) in `[project.dependencies]` are automatically skipped during PyPI version checking. Authentication is handled by global git config URL rewriting.
- **Email notifications**  -  send plain-text or HTML emails with attachments via btx-lib-mail.
- **Exit-code helpers** powered by lib_cli_exit_tools for clean POSIX exit semantics.


### Python 3.10+ Baseline

- The project targets **Python 3.10 and newer**.
- bmk declares its whole toolchain (pytest, ruff, pyright, bandit, ...) as **runtime**
  dependencies, by design - it ships no `[dev]` extra, because those tools ARE the product.
  See `docs/pyproject-reference.md` and the grouped rationale in `pyproject.toml`. Floors are
  kept at current stable releases; consult `pyproject.toml` for the authoritative values
  rather than repeating them here, where they go stale.
- CI workflows exercise GitHub's rolling runner images (`ubuntu-latest`,
  `macos-latest`, `windows-latest`) and cover CPython 3.10 through 3.14
  alongside the latest available 3.x release provided by Actions.

---

