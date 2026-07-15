# bmk CLI reference

Every command, option and exit code. The `make` targets are thin wrappers over these;
see [make-targets.md](make-targets.md) for the mapping.


The CLI leverages [rich-click](https://github.com/ewels/rich-click) so help output, validation errors, and prompts render with Rich styling while keeping the familiar Click ergonomics. All commands accept `-h` / `--help`.

Entry points: `bmk`, `mk`, `python -m bmk`.

### Global Options

These options go **before** the subcommand name:

| Option                           | Type                | Default | Description                                                         |
|----------------------------------|---------------------|---------|---------------------------------------------------------------------|
| `--version`                      | flag                | -       | Print version and exit                                              |
| `--traceback` / `--no-traceback` | flag                | `False` | Show full Python traceback on errors                                |
| `--profile NAME`                 | string              | `None`  | Load configuration from a named profile (e.g. `production`, `test`) |
| `--set SECTION.KEY=VALUE`        | string (repeatable) | -       | Override a configuration setting; can be given multiple times       |
| `-h`, `--help`                   | flag                | -       | Show help and exit                                                  |

```bash
bmk --version
bmk --traceback fail
bmk --profile production config
bmk --set lib_log_rich.console_level=DEBUG --set email.timeout=30 config
```

Profile names: alphanumeric, hyphens, underscores; max 64 characters; must start with a letter or digit. Windows reserved names (CON, PRN, ...) are rejected.

---

### test

Run the project test suite via the stage runner. All extra arguments are forwarded to the pipeline's stages.

|                  |                                                                                                       |
|------------------|-------------------------------------------------------------------------------------------------------|
| **Aliases**      | `t`                                                                                                   |
| **Options**      | `--human`  -  use human-readable text output instead of JSON                                          |
| **Arguments**    | `[ARGS]...`  -  forwarded to the pipeline's stages (unlimited, unprocessed)                           |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=test`, `BMK_OUTPUT_FORMAT`, `BMK_PACKAGE_NAME` (if configured) |
| **Exit codes**   | `0` success, or the first failing stage's exit code                                                   |

Tool output defaults to **JSON** (machine-readable). JSON mode is designed for LLM-driven
workflows where minimizing output tokens and context window consumption matters. The
stage runner captures all tool output and only shows it when a stage fails. On success,
a single JSON summary line is emitted: `{"result":"pass","stages":N,"scripts":N}`.
Dependency checking runs silently, Makefile version updates are auto-accepted, and
pytest uses `--tb=short -q --no-header` for concise failure output. Use `--human` for
full verbose output. The `BMK_OUTPUT_FORMAT` environment variable (`json` or `text`)
can also control output format; `--human` takes precedence over the env var.

**Note:** `make test --human` does not work because Make intercepts `--` flags.
Use `make test-human` (alias `make th`) instead.

Pipeline resolution: the built-in `test` pipeline, with a `[tool.bmk.pipelines.test]` overlay applied if the project defines one.

```bash
bmk test
bmk t
bmk test --human
bmk test --verbose -k test_login
BMK_OUTPUT_FORMAT=text bmk test
```

---

### testintegration

Run integration tests only (tests marked `@pytest.mark.integration`) - the long-running / external
lane. The quick `make test` runs everything except `integration` (unit + `local_only`); see
[DEVELOPMENT.md "Test Markers"](DEVELOPMENT.md#test-markers-and-what-each-command-runs) for how the
`local_only` / `integration` / `os_*` markers and `[tool.scripts.test].exclude-markers` fit together.

|                  |                                                                               |
|------------------|-------------------------------------------------------------------------------|
| **Aliases**      | `testi`, `ti`                                                                 |
| **Options**      | `--human`  -  use human-readable text output instead of JSON                  |
| **Arguments**    | `[ARGS]...`  -  forwarded to the pipeline's stages                            |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=test_integration`, `BMK_OUTPUT_FORMAT` |
| **Exit codes**   | `0` success, or the first failing stage's exit code                           |

Tool output defaults to **JSON**. In JSON mode, output is captured and only shown on failure. Use `--human` for full verbose output. See [test](#test) for details on output format control.

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
| **Arguments**    | `[ARGS]...`  -  forwarded to the project CLI           |
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

|                  |                                                              |
|------------------|--------------------------------------------------------------|
| **Aliases**      | `c`                                                          |
| **Arguments**    | `[MESSAGE]...`  -  commit message parts (joined with spaces) |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=commit`               |
| **Exit codes**   | `0` success, `2` script not found, or script exit code       |

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
| **Arguments**    | `[MESSAGE]...`  -  commit message (default: `chores`)                                                                          |
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
| **Arguments**    | `[ARGS]...`  -  forwarded to the pipeline's stages     |
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

**Git-sourced dependencies** (private repos): use PEP 440 direct references in
`[project.dependencies]`:

```toml
"my_private_lib @ git+https://github.com/MyOrg/my_private_lib.git",
```

These are automatically skipped during PyPI version comparison. Authentication is handled
by global git config URL rewriting:

```bash
git config --global url."https://<token>@github.com/MyOrg/".insteadOf "https://github.com/MyOrg/"
```

In JSON mode (`BMK_OUTPUT_FORMAT=json`, the default), dependency checking and updating
runs silently -- no per-dependency output, no report, no summary. Dependencies are still
checked and updated, just without console output. In text mode (`--human` or
`BMK_OUTPUT_FORMAT=text`), the full dependency report is displayed.

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

If no token is found, the upload is **skipped gracefully**  -  a bright red warning is
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

Run a user-defined pipeline by name. Custom pipelines are defined declaratively under `[tool.bmk.pipelines.<name>]` in `pyproject.toml` or in `bmk_makescripts/stages.toml`. If no pipeline is defined for the name, a clear error is printed.

|                  |                                                                                                               |
|------------------|---------------------------------------------------------------------------------------------------------------|
| **Arguments**    | `COMMAND_NAME` (required)  -  the command prefix to match, `[ARGS]...`  -  forwarded to the pipeline's stages |
| **Env vars set** | `BMK_PROJECT_DIR`, `BMK_COMMAND_PREFIX=<COMMAND_NAME>`, `BMK_PACKAGE_NAME` (if configured)                    |
| **Exit codes**   | `0` success, `2` no pipeline defined for the name, or the first failing stage's exit code                     |

Define the pipeline under `[tool.bmk.pipelines.<name>]` in `pyproject.toml` or `bmk_makescripts/stages.toml`. Each stage has a `name`, an `order`, and an `argv` list; stages run in order (equal orders run in parallel).

```bash
bmk custom deploy                  # runs the 'deploy' pipeline
bmk custom deploy --verbose        # forward --verbose to the stages
bmk custom migrate --dry-run       # any overlay-defined pipeline works
bmk custom nonexistent             # -> error: not found
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
| `--target`                           | choice: `app`, `host`, `user` (repeatable, required) | -       | Target layer(s) to deploy to                            |
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
| `--destination` | directory path (required) | -       | Directory to write example files |
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
| `--subject`                                                            | string (required)   | -           | Email subject line                                  |
| `--body`                                                               | string              | `""`        | Plain-text email body                               |
| `--body-html`                                                          | string              | `""`        | HTML email body (sent as multipart with plain text) |
| `--from`                                                               | string              | from config | Override sender address                             |
| `--attachment`                                                         | path (repeatable)   | -           | File to attach                                      |
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
| `2`       | Attachment file not found            |
| `22`      | Invalid argument (bad address, etc.) |
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
| `--subject`                                                            | string (required)   | -           | Notification subject line            |
| `--message`                                                            | string (required)   | -           | Notification message (plain text)    |
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

### ship

Push, wait for CI, release, wait for the release CI. The whole cut, gated on CI actually
going green rather than on hope.

```bash
bmk ship                                     # or: make ship / make sh
bmk ship --ci-workflow CI --release-workflow Release
```

| Option               | Description                             |
|----------------------|-----------------------------------------|
| `--ci-workflow`      | Workflow name to gate on after the push |
| `--release-workflow` | Workflow name to gate on after the tag  |

`ship` takes a commit message like `push` does. Give it via `MSG="..."` from make, not
`ARGS=`, since `ship` also takes the options above.

Alias: `sh`.

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
| `1`   | GENERAL_ERROR     | Unspecified failure                             |
| `2`   | FILE_NOT_FOUND    | Script or file not found (errno ENOENT)         |
| `13`  | PERMISSION_DENIED | Insufficient permissions (errno EACCES)         |
| `22`  | INVALID_ARGUMENT  | Bad input value (errno EINVAL)                  |
| `69`  | SMTP_FAILURE      | Email delivery failed (sysexits EX_UNAVAILABLE) |
| `78`  | CONFIG_ERROR      | Configuration error (sysexits EX_CONFIG)        |
| `110` | TIMEOUT           | Operation timed out (ETIMEDOUT)                 |
| `130` | SIGNAL_INT        | Interrupted by SIGINT (Ctrl+C)                  |
| `141` | BROKEN_PIPE       | Broken pipe (SIGPIPE)                           |
| `143` | SIGNAL_TERM       | Terminated by SIGTERM                           |

#### Exit Code Behaviour

**Signal handling:** `lib_cli_exit_tools` installs signal handlers at CLI startup
that translate SIGINT and SIGTERM into structured exceptions with correct POSIX exit
codes (128 + signal number). Ctrl+C produces exit code 130; `kill -TERM` produces 143.

**Subprocess signal propagation:** When a subprocess is killed by a signal, Python
reports its return code as a negative value (e.g., `-2` for SIGINT). bmk normalises
these to the POSIX `128+N` convention before propagating, so `bmk test` exits 130
(not -2) when the test script is interrupted.

**Stage exit codes:** The stage runner propagates the actual exit code from the first
failing stage. If a stage exits 42, `bmk test` exits 42 (not a generic 1). SIGINT/SIGTERM
handlers terminate running child processes during parallel execution and exit with the
correct signal code (130 for SIGINT, 143 for SIGTERM).

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

