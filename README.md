# bmk

<!-- Badges -->
[![CI](https://github.com/bitranox/bmk/actions/workflows/default_cicd_public.yml/badge.svg)](https://github.com/bitranox/bmk/actions/workflows/default_cicd_public.yml)
[![CodeQL](https://github.com/bitranox/bmk/actions/workflows/codeql.yml/badge.svg)](https://github.com/bitranox/bmk/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Open in Codespaces](https://img.shields.io/badge/Codespaces-Open-blue?logo=github&logoColor=white&style=flat-square)](https://codespaces.new/bitranox/bmk?quickstart=1)
[![PyPI](https://img.shields.io/pypi/v/bmk.svg)](https://pypi.org/project/bmk/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/bmk.svg)](https://pypi.org/project/bmk/)
[![Code Style: Ruff](https://img.shields.io/badge/Code%20Style-Ruff-46A3FF?logo=ruff&labelColor=000)](https://docs.astral.sh/ruff/)
[![codecov](https://codecov.io/gh/bitranox/bmk/graph/badge.svg?token=UFBaUDIgRk)](https://codecov.io/gh/bitranox/bmk)
[![Maintainability](https://qlty.sh/badges/041ba2c1-37d6-40bb-85a0-ec5a8a0aca0c/maintainability.svg)](https://qlty.sh/gh/bitranox/projects/bmk)
[![Known Vulnerabilities](https://snyk.io/test/github/bitranox/bmk/badge.svg)](https://snyk.io/test/github/bitranox/bmk)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)

`bmk` is a CLI task runner that orchestrates build, test, clean, and custom staged scripts with layered configuration. 
It uses a stagerunner that groups numbered shell scripts into stages — stages run sequentially (fail-fast), 
scripts sharing the same stage number run in parallel. Scripts run on Linux/macOS (Bash) and Windows (PowerShell). Supports per-project overrides and user-defined commands via `bmk custom <name>`.

Every project gets a thin `Makefile` that delegates to `uvx bmk@latest`, giving you a standard, expandable set of everyday development targets 
(`make test`, `make push`, `make bump-patch`, ...) without installing anything locally. 
Add project-specific targets or override existing ones — the Makefile is the single entry point for both interactive use and CI pipelines.

| Command                           | Options / Subcommands                                                        | Description                                          |
|-----------------------------------|------------------------------------------------------------------------------|------------------------------------------------------|
| `make test\|t`                    | `[--human]`                                                                  | Run test suite (lint, format, type-check, pytest)    |
| `make testintegration\|testi\|ti` | `[--human]`                                                                  | Run integration tests only (`pytest -m integration`) |
| `make codecov\|coverage\|cov`     |                                                                              | Upload coverage report to Codecov                    |
| `make build\|bld`                 |                                                                              | Build wheel and sdist artifacts                      |
| `make clean\|cln\|cl`             |                                                                              | Remove build artifacts and caches                    |
| `make run`                        |                                                                              | Run the project CLI via uvx                          |
| `make bump-patch`                 |                                                                              | Bump patch version X.Y.(Z+1)                         |
| `make bump-minor`                 |                                                                              | Bump minor version X.(Y+1).0                         |
| `make bump-major`                 |                                                                              | Bump major version (X+1).0.0                         |
| `make bump\|bmp\|b`               | subcommands: `[major\|ma]` `[minor\|m]` `[patch\|p]`                         | Bump patch version (default)                         |
| `make commit\|c`                  | `[MESSAGE...]`; env: `BMK_COMMIT_MESSAGE`                                    | Create a git commit with timestamped message         |
| `make push\|psh\|p`               | `[MESSAGE...]`; env: `BMK_GIT_REMOTE` (=origin), `BMK_GIT_BRANCH` (=current) | Run tests, commit, and push to remote                |
| `make release\|rel\|r`            |                                                                              | Tag vX.Y.Z, push, create GitHub release via `gh`     |
| `make dependencies\|deps\|d`      | `[--update\|-u]`; subcommands: `[update\|u]`                                 | Check and list project dependencies                  |
| `make dependencies-update`        |                                                                              | Update dependencies to latest versions               |
| `make config`                     | `[--format {human\|json}]` `[--section SECTION]`                             | Show current merged configuration                    |
| `make config-deploy`              | `[--target {app\|host\|user}]` `[--force]` `[--[no-]permissions]`            | Deploy configuration to system/user directories      |
| `make config-generate-examples`   | `[--destination PATH]` `[--force]`                                           | Generate example configuration files                 |
| `make send-email`                 | `[--subject]` `[--body\|--body-html]` `[--to]` `[--attachment]`              | Send an email via configured SMTP                    |
| `make send-notification`          | `[--subject]` `[--message]` `[--to]` `[--from]`                              | Send a plain-text notification email                 |
| `make custom`                     | `<name> [args...]`                                                           | Run user-defined scripts from override dir           |
| `bmk install`                     |                                                                              | Install or update the bmk Makefile in cwd            |
| `make info`                       |                                                                              | Print resolved package metadata                      |
| `make version-current`            |                                                                              | Print current version                                |
| `make dev`                        |                                                                              | Install package with dev extras (editable)           |
| `make install`                    |                                                                              | Editable install (no dev extras)                     |
| `make help`                       |                                                                              | Show available targets                               |

Arguments after the target name are forwarded automatically (e.g. `make push fix login bug`).
Global options: `--traceback`, `--profile NAME`, `--set SECTION.KEY=VALUE`.

On Windows, all makescripts have PowerShell (`.ps1`) counterparts, so the stagerunner and every built-in command work natively under `pwsh`. 
You still need a `make` implementation installed (e.g. [GnuWin32 Make](https://gnuwin32.sourceforge.net/packages/make.htm) or `choco install make`) to use the Makefile entry point.

- **Staged script execution** — scripts are grouped by stage number. Stages run sequentially (fail-fast); scripts sharing a stage number run in parallel.

  Example: `bmk test` executes the bundled test pipeline:

  | Stage | Execution    | Scripts                                                                                                                                                                          |
  |-------|--------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
  | 010   | sequential   | `test_010_update_deps.sh`                                                                                                                                                        |
  | 020   | sequential   | `test_020_ruff_format_apply.sh`                                                                                                                                                  |
  | 030   | sequential   | `test_030_ruff_fix_apply.sh`                                                                                                                                                     |
  | 040   | **parallel** | `test_040_ruff_format_check.sh`, `test_040_ruff_lint.sh`, `test_040_pyright.sh`, `test_040_bandit.sh`, `test_040_pip_audit.sh`, `test_040_lint_imports.sh`, `test_040_pytest.sh` |
  | 050   | sequential   | `test_050_psscriptanalyzer.sh`                                                                                                                                                   |
  | 060   | sequential   | `test_060_shellcheck.sh`                                                                                                                                                         |
  | 900   | sequential   | `test_900_clean.sh`                                                                                                                                                              |

- **JSON-by-default output** — tool output (ruff, pyright, bandit, pip-audit, shellcheck) defaults to JSON for machine-readable consumption. Use `--human` on `test`/`testintegration` commands for traditional text output, or set `BMK_OUTPUT_FORMAT=text`.
- **Virtual environment isolation** — when bmk runs via `uvx`, it automatically points tools like pyright and pip-audit at the target project's `.venv/` (if present) instead of bmk's own isolated venv. This ensures type stubs and dependencies are resolved correctly.
- **Built-in commands** — `test`, `build`, `clean`, `run`, `push`, `release`, `bump`, `coverage`, and more.
- **Custom commands** — `bmk custom <name>` runs user-defined scripts from the override directory (no bundled scripts required).
- **Per-project overrides** — drop scripts into `makescripts/` or configure `bmk.override_dir` to override or extend built-in behaviour.
- **Layered configuration** with lib_layered_config (defaults → app → host → user → .env → env).
- **Rich CLI output** styled with rich-click and structured logging via lib_log_rich.
- **Email notifications** — send plain-text or HTML emails with attachments via btx-lib-mail.
- **Exit-code helpers** powered by lib_cli_exit_tools for clean POSIX exit semantics.


### Python 3.10+ Baseline

- The project targets **Python 3.10 and newer**.
- Runtime dependencies require current stable releases (`rich-click>=1.9.6`
  and `lib_cli_exit_tools>=2.2.4`). Dev dependencies (pytest, ruff, pyright,
  bandit, etc.) specify minimum version constraints to ensure compatibility.
- CI workflows exercise GitHub's rolling runner images (`ubuntu-latest`,
  `macos-latest`, `windows-latest`) and cover CPython 3.10 through 3.14
  alongside the latest available 3.x release provided by Actions.

---

## Install - recommended via uv

[uv](https://docs.astral.sh/uv/) is an ultrafast Python package manager written in Rust (10-20x faster than pip/poetry).

### Install uv (if not already installed) 
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Install the makefile - no further installation needed

```bash
# in your project directory
uvx bmk@latest install
```

### Persistent install as CLI tool

```bash
# install the CLI tool (isolated environment, added to PATH)
uv tool install bmk

# upgrade to latest
uv tool upgrade bmk
```

### Install as project dependency

```bash
uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
uv pip install bmk
```

For alternative install paths (pip, pipx, source builds, etc.), see
[INSTALL.md](INSTALL.md). All supported methods register both the
`bmk` and `bmk` commands on your PATH.

---

## Configurationok, 

See [CONFIG.md](CONFIG.md) for detailed documentation on the layered configuration system, including precedence rules, profile support, and customization best practices.

---

## Quick Start

```bash
# Install
uv tool install bmk

# Verify
bmk --version

# Try it out
bmk hello
bmk info
bmk config
```

---

## CLI Reference

The CLI leverages [rich-click](https://github.com/ewels/rich-click) so help output, validation errors, and prompts render with Rich styling while keeping the familiar Click ergonomics. All commands accept `-h` / `--help`.

Entry points: `bmk`, `mk`, `python -m bmk`, `uvx bmk`.

### Global Options

These options go **before** the subcommand name:

| Option                           | Type                | Default | Description                                                         |
|----------------------------------|---------------------|---------|---------------------------------------------------------------------|
| `--version`                      | flag                | —       | Print version and exit                                              |
| `--traceback` / `--no-traceback` | flag                | `False` | Show full Python traceback on errors                                |
| `--profile NAME`                 | string              | `None`  | Load configuration from a named profile (e.g. `production`, `test`) |
| `--set SECTION.KEY=VALUE`        | string (repeatable) | —       | Override a configuration setting; can be given multiple times       |
| `-h`, `--help`                   | flag                | —       | Show help and exit                                                  |

```bash
bmk --version
bmk --traceback fail
bmk --profile production config
bmk --set lib_log_rich.console_level=DEBUG --set email.timeout=30 config
```

Profile names: alphanumeric, hyphens, underscores; max 64 characters; must start with a letter or digit. Windows reserved names (CON, PRN, ...) are rejected.

---

### test

Run the project test suite via the stagerunner. All extra arguments are forwarded to the underlying scripts.

|                  |                                                                                                                                              |
|------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| **Aliases**      | `t`                                                                                                                                          |
| **Options**      | `--human` — use human-readable text output instead of JSON                                                                                   |
| **Arguments**    | `[ARGS]...` — forwarded to scripts (unlimited, unprocessed)                                                                                  |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=test`, `BMK_OUTPUT_FORMAT`, `BMK_OVERRIDE_DIR` (if configured), `BMK_PACKAGE_NAME` (if configured)    |
| **Exit codes**   | `0` success, `2` script not found, or the script's own exit code                                                                             |

Tool output defaults to **JSON** (machine-readable). Use `--human` for traditional text output.
The `BMK_OUTPUT_FORMAT` environment variable (`json` or `text`) can also control output format;
`--human` takes precedence over the env var.

Script lookup order:
1. `<cwd>/bmk_makescripts/_btx_stagerunner.sh` (local override)
2. `<package>/makescripts/_btx_stagerunner.sh` (bundled)

```bash
bmk test
bmk t
bmk test --human
bmk test --verbose -k test_login
BMK_OUTPUT_FORMAT=text bmk test
```

---

### testintegration

Run integration tests only (tests marked `@pytest.mark.integration`).

|                  |                                                                          |
|------------------|--------------------------------------------------------------------------|
| **Aliases**      | `testi`, `ti`                                                            |
| **Options**      | `--human` — use human-readable text output instead of JSON               |
| **Arguments**    | `[ARGS]...` — forwarded to scripts                                       |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=test_integration`, `BMK_OUTPUT_FORMAT` |
| **Exit codes**   | `0` success, `2` script not found, or script exit code                   |

Tool output defaults to **JSON**. Use `--human` for text output. See [test](#test) for details on output format control.

```bash
bmk testintegration
bmk testi --human
bmk ti
```

---

### build

Build Python wheel and sdist artifacts.

|                  |                                                        |
|------------------|--------------------------------------------------------|
| **Aliases**      | `bld`                                                  |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=bld`            |
| **Exit codes**   | `0` success, `2` script not found, or script exit code |

```bash
bmk build
bmk bld
```

---

### clean

Remove build artifacts, caches, and temporary files. Patterns are read from `[tool.clean].patterns` in `pyproject.toml` or built-in defaults.

|                  |                                                        |
|------------------|--------------------------------------------------------|
| **Aliases**      | `cln`, `cl`                                            |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=clean`          |
| **Exit codes**   | `0` success, `2` script not found, or script exit code |

```bash
bmk clean
bmk cln
bmk cl
```

---

### run

Run the project CLI via uvx with automatic local dependency discovery. All arguments are forwarded to the project CLI.

|                  |                                                        |
|------------------|--------------------------------------------------------|
| **Arguments**    | `[ARGS]...` — forwarded to the project CLI             |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=run`            |
| **Exit codes**   | `0` success, `2` script not found, or script exit code |

```bash
bmk run --help
bmk run info
bmk run --version
```

---

### commit

Create a git commit with a timestamped message. The message format is `YYYY-MM-DD HH:MM:SS - <message>`. All positional words are joined into the message.

|                  |                                                            |
|------------------|------------------------------------------------------------|
| **Aliases**      | `c`                                                        |
| **Arguments**    | `[MESSAGE]...` — commit message parts (joined with spaces) |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=commit`             |
| **Exit codes**   | `0` success, `2` script not found, or script exit code     |

```bash
bmk commit fix login redirect bug
bmk c quick patch
```

---

### push

Run the test suite, commit any staged changes, and push to the remote.

|                  |                                                                                                                                |
|------------------|--------------------------------------------------------------------------------------------------------------------------------|
| **Aliases**      | `psh`, `p`                                                                                                                     |
| **Arguments**    | `[MESSAGE]...` — commit message (default: `chores`)                                                                            |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=push`, `BMK_GIT_REMOTE` (default: `origin`), `BMK_GIT_BRANCH` (default: current branch) |
| **Exit codes**   | `0` success, `2` script not found, or script exit code                                                                         |

```bash
bmk push update readme
bmk psh
bmk p
```

---

### bump

Bump the project version. This is a command group with subcommands for each version part.

|             |            |
|-------------|------------|
| **Aliases** | `bmp`, `b` |

#### Subcommands

| Subcommand | Alias | Description                  | `BMK_COMMAND_PREFIX` |
|------------|-------|------------------------------|----------------------|
| `major`    | `ma`  | Bump major version (X+1).0.0 | `bump_major`         |
| `minor`    | `m`   | Bump minor version X.(Y+1).0 | `bump_minor`         |
| `patch`    | `p`   | Bump patch version X.Y.(Z+1) | `bump_patch`         |

```bash
bmk bump patch
bmk bump minor
bmk bump major
bmk bmp p            # short form
bmk b m              # shortest form
```

---

### release

Create a versioned release with git tag and GitHub release.

|                  |                                                        |
|------------------|--------------------------------------------------------|
| **Aliases**      | `rel`, `r`                                             |
| **Arguments**    | `[ARGS]...` — forwarded to scripts                     |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=rel`            |
| **Exit codes**   | `0` success, `2` script not found, or script exit code |

```bash
bmk release
bmk rel
bmk r
```

---

### dependencies

Check and manage project dependencies. Without a subcommand, lists dependencies. The `-u` flag triggers an update.

|             |             |
|-------------|-------------|
| **Aliases** | `deps`, `d` |

| Option           | Type | Default | Description                  |
|------------------|------|---------|------------------------------|
| `-u`, `--update` | flag | `False` | Update outdated dependencies |

#### Subcommands

| Subcommand | Alias | Description                                     | `BMK_COMMAND_PREFIX` |
|------------|-------|-------------------------------------------------|----------------------|
| `update`   | `u`   | Update outdated dependencies to latest versions | `deps_update`        |

```bash
bmk dependencies          # list deps
bmk deps -u               # update deps
bmk d update              # explicit update subcommand
bmk deps u                # short form
```

---

### codecov

Upload the coverage report to Codecov.

The token is discovered by checking `CODECOV_TOKEN` in the environment first, then
searching for a `.env` file starting from the project directory and walking up to the
filesystem root.

If no token is found, the upload is **skipped gracefully** — a bright red warning is
printed to stderr and the command exits with code 0 (success). This means `make test`
will not fail in environments where no Codecov token is available.

|                  |                                                        |
|------------------|--------------------------------------------------------|
| **Aliases**      | `coverage`, `cov`                                      |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=cov`            |
| **Exit codes**   | `0` success, `2` script not found, or script exit code |

```bash
bmk codecov
bmk coverage
bmk cov
```

---

### custom

Run user-defined staged scripts from the override directory. Unlike built-in commands, `custom` has no bundled scripts — it only looks in the override directory. If no matching scripts are found, a clear error is printed.

|                  |                                                                                                                         |
|------------------|-------------------------------------------------------------------------------------------------------------------------|
| **Arguments**    | `COMMAND_NAME` (required) — the command prefix to match, `[ARGS]...` — forwarded to scripts                             |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=<COMMAND_NAME>`, `BMK_OVERRIDE_DIR` (forced), `BMK_PACKAGE_NAME` (if configured) |
| **Exit codes**   | `0` success, `2` override dir missing or no matching scripts, or script exit code                                       |

Override directory resolution:
1. `bmk.override_dir` from config (if set)
2. `<cwd>/makescripts` (default)

Scripts must follow the naming convention `<name>_<NNN>_<description>.sh` (e.g., `deploy_01_prepare.sh`, `deploy_02_upload.sh`). They are executed in sorted order via the stagerunner.

```bash
bmk custom deploy                  # runs deploy_*.sh from makescripts/
bmk custom deploy --verbose        # forward --verbose to all scripts
bmk custom migrate --dry-run       # any name works if scripts exist
bmk custom nonexistent             # → error: not found
```

---

### config

Display the current merged configuration from all sources.

|                          |                                                                         |
|--------------------------|-------------------------------------------------------------------------|
| **Pass-through profile** | Inherits `--profile` from global options; can be overridden per-command |

| Option           | Type                    | Default | Description                                                 |
|------------------|-------------------------|---------|-------------------------------------------------------------|
| `--format`       | choice: `human`, `json` | `human` | Output format                                               |
| `--section NAME` | string                  | `None`  | Show only a specific section (e.g. `lib_log_rich`, `email`) |
| `--profile NAME` | string                  | `None`  | Override profile from the root command                      |

```bash
bmk config
bmk config --format json
bmk config --section email
bmk config --profile production --format json
bmk --set lib_log_rich.console_level=DEBUG config
```

---

### config-deploy

Deploy default configuration templates to system or user directories.

| Option                               | Type                                                 | Default | Description                                             |
|--------------------------------------|------------------------------------------------------|---------|---------------------------------------------------------|
| `--target`                           | choice: `app`, `host`, `user` (repeatable, required) | —       | Target layer(s) to deploy to                            |
| `--force`                            | flag                                                 | `False` | Overwrite existing configuration files                  |
| `--profile NAME`                     | string                                               | `None`  | Override profile from the root command                  |
| `--permissions` / `--no-permissions` | flag                                                 | enabled | Set Unix permissions (app/host: 755/644, user: 700/600) |
| `--dir-mode`                         | octal string                                         | `None`  | Override directory mode (e.g. `750`, `0o750`)           |
| `--file-mode`                        | octal string                                         | `None`  | Override file mode (e.g. `640`, `0o640`)                |

Deploy targets (without profile):

| Target | Path                                    |
|--------|-----------------------------------------|
| `app`  | `/etc/xdg/{slug}/config.toml`           |
| `host` | `/etc/xdg/{slug}/hosts/{hostname}.toml` |
| `user` | `~/.config/{slug}/config.toml`          |

With `--profile production`, a `profile/production/` directory is inserted into each path.

```bash
bmk config-deploy --target app
bmk config-deploy --target user --target host
bmk config-deploy --target user --profile production --force
bmk config-deploy --target user --file-mode 640 --dir-mode 750
bmk config-deploy --target app --no-permissions
```

---

### config-generate-examples

Generate example configuration files in a target directory.

| Option          | Type                      | Default | Description                      |
|-----------------|---------------------------|---------|----------------------------------|
| `--destination` | directory path (required) | —       | Directory to write example files |
| `--force`       | flag                      | `False` | Overwrite existing files         |

```bash
bmk config-generate-examples --destination ./examples
bmk config-generate-examples --destination /tmp/bmk-examples --force
```

---

### logdemo

Run a logging demonstration to preview log output at various levels.

| Option    | Type   | Default   | Description              |
|-----------|--------|-----------|--------------------------|
| `--theme` | string | `classic` | Logging theme to preview |

```bash
bmk logdemo
bmk logdemo --theme modern
bmk --set lib_log_rich.console_level=DEBUG logdemo
```

---

### send-email

Send an email using configured SMTP settings. Supports plain text, HTML, multiple recipients, and file attachments.

| Option                                                                 | Type                | Default     | Description                                         |
|------------------------------------------------------------------------|---------------------|-------------|-----------------------------------------------------|
| `--to`                                                                 | string (repeatable) | from config | Recipient email address                             |
| `--subject`                                                            | string (required)   | —           | Email subject line                                  |
| `--body`                                                               | string              | `""`        | Plain-text email body                               |
| `--body-html`                                                          | string              | `""`        | HTML email body (sent as multipart with plain text) |
| `--from`                                                               | string              | from config | Override sender address                             |
| `--attachment`                                                         | path (repeatable)   | —           | File to attach                                      |
| `--smtp-host`                                                          | string (repeatable) | from config | Override SMTP host(s), format `host:port`           |
| `--smtp-username`                                                      | string              | from config | Override SMTP username                              |
| `--smtp-password`                                                      | string              | from config | Override SMTP password                              |
| `--use-starttls` / `--no-use-starttls`                                 | flag                | from config | Override STARTTLS setting                           |
| `--timeout`                                                            | float               | from config | Override socket timeout in seconds                  |
| `--raise-on-missing-attachments` / `--no-raise-on-missing-attachments` | flag                | from config | Error on missing attachment files                   |
| `--raise-on-invalid-recipient` / `--no-raise-on-invalid-recipient`     | flag                | from config | Error on invalid recipient addresses                |

| Exit code | Meaning                              |
|-----------|--------------------------------------|
| `0`       | Success                              |
| `22`      | Invalid argument (bad address, etc.) |
| `66`      | Attachment file not found            |
| `69`      | SMTP delivery failure                |
| `78`      | Configuration error (no SMTP hosts)  |

```bash
bmk send-email --to user@example.com --subject "Test" --body "Hello"
bmk send-email --to a@b.com --to c@d.com --subject "Report" \
    --body "See attached." --body-html "<h1>Report</h1>" \
    --attachment report.pdf --attachment data.csv
bmk send-email --smtp-host smtp.custom.com:465 --no-use-starttls \
    --to user@example.com --subject "Via custom SMTP" --body "Test"
```

---

### send-notification

Send a simple plain-text notification email.

| Option                                                                 | Type                | Default     | Description                          |
|------------------------------------------------------------------------|---------------------|-------------|--------------------------------------|
| `--to`                                                                 | string (repeatable) | from config | Recipient email address              |
| `--subject`                                                            | string (required)   | —           | Notification subject line            |
| `--message`                                                            | string (required)   | —           | Notification message (plain text)    |
| `--from`                                                               | string              | from config | Override sender address              |
| `--smtp-host`                                                          | string (repeatable) | from config | Override SMTP host(s)                |
| `--smtp-username`                                                      | string              | from config | Override SMTP username               |
| `--smtp-password`                                                      | string              | from config | Override SMTP password               |
| `--use-starttls` / `--no-use-starttls`                                 | flag                | from config | Override STARTTLS setting            |
| `--timeout`                                                            | float               | from config | Override socket timeout in seconds   |
| `--raise-on-missing-attachments` / `--no-raise-on-missing-attachments` | flag                | from config | Error on missing attachment files    |
| `--raise-on-invalid-recipient` / `--no-raise-on-invalid-recipient`     | flag                | from config | Error on invalid recipient addresses |

```bash
bmk send-notification --to ops@example.com --subject "Deploy OK" --message "All good"
bmk send-notification --to a@b.com --to c@d.com --subject "Alert" --message "Disk 90%"
```

---

### info

Print resolved package metadata (version, author, paths, Python version).

```bash
bmk info
```

---

### hello

Emit the canonical greeting message. Demonstrates the success path.

```bash
bmk hello
```

---

### fail

Trigger an intentional failure to test error handling. Combine with `--traceback` to see the full stack trace.

```bash
bmk fail
bmk --traceback fail
```

---

### Exit Codes

All commands use POSIX-conventional exit codes:

| Code  | Name              | Meaning                                         |
|-------|-------------------|-------------------------------------------------|
| `0`   | SUCCESS           | Command completed successfully                  |
| `1`   | GENERAL_ERROR     | Unspecified failure                              |
| `2`   | FILE_NOT_FOUND    | Script or file not found (errno ENOENT)          |
| `13`  | PERMISSION_DENIED | Insufficient permissions (errno EACCES)          |
| `22`  | INVALID_ARGUMENT  | Bad input value (errno EINVAL)                   |
| `69`  | SMTP_FAILURE      | Email delivery failed (sysexits EX_UNAVAILABLE)  |
| `78`  | CONFIG_ERROR      | Configuration error (sysexits EX_CONFIG)         |
| `110` | TIMEOUT           | Operation timed out (ETIMEDOUT)                  |
| `130` | SIGNAL_INT        | Interrupted by SIGINT (Ctrl+C)                   |
| `141` | BROKEN_PIPE       | Broken pipe (SIGPIPE)                            |
| `143` | SIGNAL_TERM       | Terminated by SIGTERM                            |

#### Exit Code Behaviour

**Signal handling:** `lib_cli_exit_tools` installs signal handlers at CLI startup
that translate SIGINT and SIGTERM into structured exceptions with correct POSIX exit
codes (128 + signal number). Ctrl+C produces exit code 130; `kill -TERM` produces 143.

**Subprocess signal propagation:** When a subprocess is killed by a signal, Python
reports its return code as a negative value (e.g., `-2` for SIGINT). bmk normalises
these to the POSIX `128+N` convention before propagating, so `bmk test` exits 130
(not -2) when the test script is interrupted.

**Stagerunner exit codes:** The bash stagerunner propagates the actual exit code from
the first failed script. If a script exits 42, `bmk test` exits 42 (not a generic 1).
Signal traps in the stagerunner ensure Ctrl+C during parallel execution kills background
jobs and exits with the correct signal code (130 for SIGINT, 143 for SIGTERM).

---

### Command Alias Quick Reference

| Full command          | Aliases           |
|-----------------------|-------------------|
| `test`                | `t`               |
| `testintegration`     | `testi`, `ti`     |
| `build`               | `bld`             |
| `clean`               | `cln`, `cl`       |
| `commit`              | `c`               |
| `push`                | `psh`, `p`        |
| `bump`                | `bmp`, `b`        |
| `bump major`          | `bump ma`         |
| `bump minor`          | `bump m`          |
| `bump patch`          | `bump p`          |
| `release`             | `rel`, `r`        |
| `dependencies`        | `deps`, `d`       |
| `dependencies update` | `deps u`          |
| `codecov`             | `coverage`, `cov` |

---

### Email Sending

The application includes email sending capabilities via [btx-lib-mail](https://pypi.org/project/btx-lib-mail/), supporting both simple notifications and rich HTML emails with attachments.

#### Email Configuration

Configure email settings via environment variables, `.env` file, or configuration files:

**Environment Variables:**

Environment variables use the format: `<PREFIX>___<SECTION>__<KEY>=value`
- Triple underscore (`___`) separates PREFIX from SECTION
- Double underscore (`__`) separates SECTION from KEY

```bash
export BMK___EMAIL__SMTP_HOSTS="smtp.gmail.com:587,smtp.backup.com:587"
export BMK___EMAIL__FROM_ADDRESS="alerts@myapp.com"
export BMK___EMAIL__SMTP_USERNAME="your-email@gmail.com"
export BMK___EMAIL__SMTP_PASSWORD="your-app-password"
export BMK___EMAIL__USE_STARTTLS="true"
export BMK___EMAIL__TIMEOUT="60.0"
```

**Configuration File**:
```toml
[email]
smtp_hosts = ["smtp.gmail.com:587", "smtp.backup.com:587"]  # Fallback to backup if primary fails
from_address = "alerts@myapp.com"
smtp_username = "myuser@gmail.com"
smtp_password = "secret_password"  # Consider using environment variables for sensitive data
use_starttls = true
timeout = 60.0
```

**`.env` File:**
```bash
# Email configuration for local testing
BMK___EMAIL__SMTP_HOSTS=smtp.gmail.com:587
BMK___EMAIL__FROM_ADDRESS=noreply@example.com
```

#### Gmail Configuration Example

For Gmail, create an [App Password](https://support.google.com/accounts/answer/185833) instead of using your account password:

```bash
BMK___EMAIL__SMTP_HOSTS=smtp.gmail.com:587
BMK___EMAIL__FROM_ADDRESS=your-email@gmail.com
BMK___EMAIL__SMTP_USERNAME=your-email@gmail.com
BMK___EMAIL__SMTP_PASSWORD=your-16-char-app-password
```

#### Send Simple Email

```bash
# Send basic email to one recipient
bmk send-email \
    --to recipient@example.com \
    --subject "Test Email" \
    --body "Hello from bitranox!"

# Send to multiple recipients
bmk send-email \
    --to user1@example.com \
    --to user2@example.com \
    --subject "Team Update" \
    --body "Please review the latest changes"
```

#### Send HTML Email with Attachments

```bash
bmk send-email \
    --to recipient@example.com \
    --subject "Monthly Report" \
    --body "Please find the monthly report attached." \
    --body-html "<h1>Monthly Report</h1><p>See attached PDF for details.</p>" \
    --attachment report.pdf \
    --attachment data.csv
```

#### Send Notifications

For simple plain-text notifications, use the convenience command:

```bash
# Single recipient
bmk send-notification \
    --to ops@example.com \
    --subject "Deployment Success" \
    --message "Application deployed successfully to production at $(date)"

# Multiple recipients
bmk send-notification \
    --to admin1@example.com \
    --to admin2@example.com \
    --subject "System Alert" \
    --message "Database backup completed successfully"
```

#### Programmatic Email Usage

```python
from bmk.adapters.email.sender import EmailConfig
from bmk.composition import send_email, send_notification

# Configure email
config = EmailConfig(
    smtp_hosts=["smtp.gmail.com:587"],
    from_address="alerts@myapp.com",
    smtp_username="myuser@gmail.com",
    smtp_password="app-password",
    timeout=60.0,
)

# Send simple email
send_email(
    config=config,
    recipients="recipient@example.com",
    subject="Test Email",
    body="Hello from Python!",
)

# Send email with HTML and attachments
from pathlib import Path
send_email(
    config=config,
    recipients=["user1@example.com", "user2@example.com"],
    subject="Report",
    body="See attached report",
    body_html="<h1>Report</h1><p>Details in attachment</p>",
    attachments=[Path("report.pdf")],
)

# Send notification
send_notification(
    config=config,
    recipients="ops@example.com",
    subject="Deployment Complete",
    message="Production deployment finished successfully",
)
```

#### Email Troubleshooting

**Connection Failures:**
- Verify SMTP hostname and port are correct
- Check firewall allows outbound connections on SMTP port
- Test connectivity: `telnet smtp.gmail.com 587`

**Authentication Errors:**
- For Gmail: Use App Password, not account password
- Ensure username/password are correct
- Check for 2FA requirements

**Emails Not Arriving:**
- Check recipient's spam folder
- Verify `from_address` is valid and not blacklisted
- Review SMTP server logs for delivery status

## Further Documentation

- [Install Guide](INSTALL.md)
- [Development Handbook](DEVELOPMENT.md)
- [Contributor Guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Module Reference](docs/systemdesign/module_reference.md)
- [License](LICENSE)
