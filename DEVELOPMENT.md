# Development

## Make Targets

Run `make help` for the authoritative list - it is generated from the Makefile itself, so it
cannot go stale. [docs/make-targets.md](docs/make-targets.md) documents each target and the
options it accepts; [docs/cli-reference.md](docs/cli-reference.md) covers the underlying `bmk`
commands.

The Makefile is a thin wrapper: each target calls the `bmk` command of the same name. Every stage
is cross-OS Python (`src/bmk/adapters/stagerunner/`), invoked as an argv list - there are no shell
or PowerShell stage scripts.

## Environment Variables

These are the variables you can set. Anything not listed here is not consulted as input.

| Variable                 | Default                   | Effect                                                                                                                                                                 |
|--------------------------|---------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `BMK_OUTPUT_FORMAT`      | `json`                    | `json` or `text`. JSON suppresses tool output on success. `--human` forces text.                                                                                       |
| `UV_PROJECT_ENVIRONMENT` | `.venv`                   | Project venv path, absolute or relative to the project.                                                                                                                |
| `BMK_NO_VENV_SYNC`       | unset                     | `1` skips creating/syncing the project venv; use the environment as-is.                                                                                                |
| `BMK_VENV_LOCK_TIMEOUT`  | `600`                     | Seconds to wait for another bmk that is provisioning the same venv. On timeout bmk changes nothing and says so on stderr.                                              |
| `BMK_VENV_LOCK_DIR`      | `~/.cache/bmk/venv-locks` | Where the venv lock files live. Deliberately outside every repository; override it in tests so they never touch the real one.                                          |
| `BMK_TOOL_LOCK`          | unset                     | `0` disables the lock guarding bmk's own shared tool environment. The guard is what stops another repo's `make` from rebuilding that environment under a running gate. |
| `BMK_COMMIT_MESSAGE`     | unset                     | Commit message for `commit` / `push`. `MSG="..."` sets this for you.                                                                                                   |
| `BMK_GIT_REMOTE`         | `origin`                  | Remote that `push` targets.                                                                                                                                            |
| `BMK_GIT_BRANCH`         | current                   | Branch that `push` targets.                                                                                                                                            |
| `CODECOV_TOKEN`          | unset                     | Token for Codecov upload; also read from `.env`.                                                                                                                       |
| `DEVELOPMENT_MODE`       | unset                     | `1` re-raises unexpected exceptions in email commands with full tracebacks.                                                                                            |

Configuration settings additionally accept `BMK___<SECTION>__<KEY>` environment overrides and
`.env` entries - see [docs/pyproject-reference.md](docs/pyproject-reference.md) and
`src/bmk/adapters/config/`.

`BMK_TOOL_LOCK_HELD` is also **set by** bmk - to its own pid, once it holds the shared
tool-environment lock - and inherited by every child, so a nested `make` skips the upgrade
instead of rebuilding the environment its parent is running out of. `BMK_TOOL_LOCK_PATH`
exists only so the test suite can point the guard at a throwaway lock file.

`BMK_PROJECT_DIR`, `BMK_PYTHON_CMD` and `BMK_COMMAND_PREFIX` are **set by** bmk into each stage's
child environment (`build_context()` in `stagerunner/context.py`), not read from yours - do not set them.
`UV_OFFLINE` is uv's own, and the Makefile no longer needs to special-case it: the install step
runs `uv tool upgrade bmk`, which takes no `--refresh` flag (uv rejects one) and answers
"Nothing to upgrade" cleanly when offline.

## Test Markers and What Each Command Runs

`make test` runs `pytest -m "not <exclude-markers>"`, where `exclude-markers` comes from
`[tool.scripts.test].exclude-markers` in `pyproject.toml` and **defaults to `integration`**. The
markers split tests across the local gate, the integration lane, and CI:

- **`local_only`** - needs a local resource the CI runners lack (a real service, device, or OS
  feature on your machine). `make test` **runs** these locally (guard each with a `skipif` so it
  skips when the resource is absent) and CI **excludes** them (`pytest -m "not local_only"`). The
  local-vs-CI difference is intentional; `make test` is not meant to be identical to CI.
- **`integration`** - long-running tests kept out of the quick `make test`; run them on demand with
  `make testintegration` (`-m integration`; aliases `testi`, `ti`).
- **`os_agnostic` / `os_windows` / `os_macos` / `os_posix` / `os_linux`** - label the target OS; the
  marker itself does not skip, so pair each with its own `skipif(sys.platform ...)`.

Raise `exclude-markers` only to skip MORE from `make test` (e.g. a project whose `local_only` tests
mutate the host and are unsafe on a real dev machine can tag them `mutating` and set
`exclude-markers = "mutating"`). Do not set it to "match CI" - that drops the local coverage
`local_only` exists to provide.

### Quick Reference

| Command                                | What it runs                                                                                    |
|----------------------------------------|-------------------------------------------------------------------------------------------------|
| `make test`                            | Everything EXCEPT `integration` (unit + `local_only`, which skip when their resource is absent) |
| `make testintegration` (`testi`, `ti`) | Only `@pytest.mark.integration` (long-running / external)                                       |
| `pytest -m "not local_only"`           | The CI gate                                                                                     |
| `pytest tests/`                        | ALL tests (no marker filter)                                                                    |

### Adding a test that needs a resource

Mark it `local_only` when it needs a *local* resource CI lacks (run by `make test` locally, excluded
from CI); mark it `integration` when it is long-running/external (run via `make testintegration`).
Pair an OS- or resource-specific test with a `skipif` so it skips cleanly when unavailable:

```python
@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_needs_a_local_resource(...):
    """Skipped in CI; runs in `make test` when the resource is available."""
    ...
```

### Email Integration Tests

The tests in `tests/test_mail.py` that actually send messages carry both `@pytest.mark.integration`
(so `make test` skips them and `make testintegration` runs them) and `@pytest.mark.local_only` (so CI
skips them). To run them:

1. **Create a `.env` file** in the project root with your SMTP settings:

```bash
# .env (copy from .env.example)
EMAIL__SMTP_HOSTS=["smtp.example.com:587"]
EMAIL__FROM_ADDRESS=sender@example.com
EMAIL__RECIPIENTS=["recipient@example.com"]
EMAIL__SMTP_USERNAME=your_username
EMAIL__SMTP_PASSWORD=your_password
```

   The integration tests read the `.env` found upward from the project. To send one mail by hand
   with another file, point `--env-file` at it:

```bash
bmk --env-file /path/to/my/.env send-notification --subject "Test" --message "Hello"
```

2. **Run the integration tests**:

```bash
make testintegration
```

3. **Or run the email tests directly**:

```bash
pytest tests/test_mail.py -m integration -v
```

A new test that needs an external service is marked the same way:

```python
@pytest.mark.local_only
@pytest.mark.integration
@pytest.mark.os_agnostic
def test_real_external_service(...):
    """Integration test requiring external service."""
    ...
```

### SMTP Test Seam

`send_email()` and `send_notification()` accept an optional `transport` argument, forwarded
to `btx_lib_mail`'s `Transport` port. Unit tests inject a double (`RecordingTransport` in
`tests/test_mail.py`) rather than patching `smtplib.SMTP`, and assert on delivery intent:
envelope sender, recipients, host failover order, credentials, and the composed payload.

Do not go back to monkeypatching `smtplib`. btx_lib_mail streams the message over the wire
protocol itself (MAIL/RCPT plus DATA or BDAT), so a `MagicMock` does not honour the contract
and breaks whenever the library changes delivery strategy.

The `SendEmail` / `SendNotification` ports in `application/ports.py` deliberately omit
`transport`: a delivery mechanism is an adapter concern, not something the application layer
should see. The adapter still satisfies the Protocol because an extra keyword parameter with
a default is structurally compatible. Do not add `transport` to the port.

## Development Workflow

```bash
make test                    # ruff + pyright + import-linter + bandit + pip-audit + pytest (JSON output)
make test-human              # the same run with full verbose output (alias: make th)
make testintegration         # only the integration lane (aliases: testi, ti)
BMK_NO_VENV_SYNC=1 make test # use the current environment; skip venv provisioning
```

**Note:** `make test --human` does not work, because make intercepts `--` flags. Use
`make test-human` or `make th`.

`make test` is the single local gate. Note it **writes to your working tree before checking it** -
the pipeline (`stagerunner/registry.py`) is ordered:

| Order | Stage                                                                                                                       | Mutates? |
|-------|-----------------------------------------------------------------------------------------------------------------------------|----------|
| 10    | `update_deps` (delegates to the `deps_update` pipeline)                                                                     | yes      |
| 20    | `ruff_format_apply`                                                                                                         | yes      |
| 30    | `ruff_fix_apply`                                                                                                            | yes      |
| 40    | `bandit`, `lint_imports`, `pip_audit`, `pyright`, `pytest`, `ruff_format_check`, `ruff_lint`, `psscriptanalyzer` (parallel) | no       |
| 60    | `shellcheck`                                                                                                                | no       |

So a `make test` run can leave your files reformatted and auto-fixed, and your `pyproject.toml`
dependency floors bumped, even when it passes. Stages sharing an order run in parallel; the run
fails fast between order batches.

In JSON mode - the default - a passing stage prints nothing and only failures produce output;
dependency checking runs silently and Makefile version updates are auto-accepted. Use `--human` /
`BMK_OUTPUT_FORMAT=text` for the full verbose stream.

**Automation notes**

- `make push` runs the full test suite, then commits and pushes, creating an empty commit when
  there are no staged changes.
- Pass a commit message with `MSG="..."` (equivalently `BMK_COMMIT_MESSAGE`), which travels through
  the environment so punctuation and newlines survive. Resolution order: trailing words / `ARGS` ->
  `BMK_COMMIT_MESSAGE` -> interactive prompt -> `chores` when non-interactive.
- Do NOT put a message in `ARGS="..."`: make expands `ARGS` into the recipe text and bash re-parses
  it, so `(`, `;`, `` ` `` and `$` break or execute. A newline in `ARGS` is rejected by a guard in
  the Makefile.

### Versioning & Metadata

- Single source of truth for the version is `pyproject.toml` (`[project].version`).
- Runtime metadata is served from static constants in `src/bmk/__init__conf__.py`; runtime code does
  not query packaging metadata. `helpers/_sync_initconf.py` keeps those constants in sync with
  `pyproject.toml` via the bump/push pipelines.
- Do not hand-edit the version in code; bump `pyproject.toml` and update `CHANGELOG.md`.
- The bundled Makefile template carries its own version on line 1 (`# BMK MAKEFILE X.Y.Z`), also
  synced by `_sync_initconf.py`.
- The console script name is the static `shell_command` constant in `__init__conf__.py`
  (`bmk`); `[project.scripts]` in `pyproject.toml` registers it together with `mk`.

### The project venv

bmk's own environment holds bmk's toolchain and nothing of the target project - see
[docs/adr/0002-bmk-env-holds-bmk-alone.md](docs/adr/0002-bmk-env-holds-bmk-alone.md). The project's
dependencies live in the project's own venv, which bmk provisions and every gate resolves:

- Before any pipeline that touches the Python environment, bmk creates the project's venv if it is
  missing and syncs it to `pyproject.toml`, then points `VIRTUAL_ENV` at it.
- pytest, pyright and pip-audit all resolve that same venv, so the tested, type-checked and audited
  environment are one and the same.
- Broken venvs (stale mounts, missing `pyvenv.cfg`) are detected and ignored.
- If no valid venv exists (provisioning skipped or failed), bmk unsets `VIRTUAL_ENV` so tools fall
  back to their own discovery and pins pip-audit at bmk's own interpreter.

The venv path comes from `UV_PROJECT_ENVIRONMENT` (absolute, or relative to the project; default
`.venv`); `BMK_NO_VENV_SYNC=1` skips provisioning. Because the sync is exact and upgrading, packages
installed into the venv by hand do not survive it. See `CLAUDE.md` for why both flags are needed and
how the ordering interacts with the frozen `StageContext`.

### Private Repository Dependencies

Projects can depend on packages from private Git repositories using PEP 440 direct references
in `[project.dependencies]`:

```toml
[project]
dependencies = [
    "my_private_lib @ git+https://github.com/MyOrg/my_private_lib.git",
]
```

bmk automatically skips these during PyPI dependency checking - direct URL references
are not on PyPI and need no version comparison.

Authentication is handled by global git config URL rewriting, not by bmk.
To scope access to a single organisation:

```bash
git config --global url."https://<token>@github.com/MyOrg/".insteadOf "https://github.com/MyOrg/"
```

This keeps credentials out of project files and `.env` - git handles auth transparently.

### Dependency Auditing

`make test` runs `pip-audit` against the project's venv. Fix a reported vulnerability at its root,
in this order:

1. Find what actually forces the vulnerable version (`uv pip compile pyproject.toml`, adding
   `--extra <name>` for each extra the project declares; bmk itself declares none).
   A CVE on a transitive package usually means another dependency CAPS it below the fix.
2. Remove or disable the capper if there is one - that fixes it with no exclusion. Comment the line
   out with the reason and the re-enable condition rather than deleting it.
3. Only if no capper exists and no fixed release does, add the id to `[tool.pip-audit].ignore-vulns`
   with an inline note. Note the tables are different vocabularies: `ignore-vulns` takes
   PYSEC/GHSA/CVE ids, `[tool.bandit].skips` takes bandit check ids (`B###`). A PYSEC id in
   `[tool.bandit].skips` is silently inert.

bmk itself declares its whole toolchain as runtime dependencies and ships no `[dev]` extra, so a
floor for bmk goes in `[project.dependencies]`. See the grouped rationale in `pyproject.toml`.

## CI & Publishing

The GitHub Actions workflows under `.github/workflows/` are distributed from the
`default_cicd_public` template; change them there, not in this repository.

- `default_cicd_public.yml` -- lint, type-check and test on Linux, macOS and Windows for every
  Python version listed in the `pyproject.toml` classifiers, verify the pipx and uv installs, run
  the notebooks, and build the wheel and sdist and check a clean wheel install.
- `default_release_public.yml` -- on a `v*` tag, builds the artifacts and publishes them to
  PyPI, with the `PYPI_API_TOKEN` secret when it is set and otherwise through a PyPI Trusted
  Publisher (OIDC; the publish job has `id-token: write` and runs in the `pypi` environment).
- `codeql.yml` -- CodeQL analysis.

A project works on a token and migrates to OIDC with no workflow change; if PyPI reports a Trusted
Publisher is configured but the upload still used a token, the secret is still present and must be
deleted.

To publish a release:

1. `make bump-patch` (or `bump-minor` / `bump-major`) to update `pyproject.toml` and `CHANGELOG.md`,
   then commit and push. A non-final version is finalized rather than stepped past (`1.2.3rc1`
   patch-bumps to `1.2.3`); see `docs/pyproject-reference.md` for the full table.
2. `make release` to tag `v` + the project version, push, and create the GitHub release; the tag
   starts `default_release_public.yml`.
3. Or `make ship` to push, wait for CI, release, and wait for the release workflow - CI-gated end to
   end.

## Codecov

- `make test` generates `coverage.xml` (the name comes from `[tool.scripts.test]
  .coverage-report-file`).
- `make codecov` (aliases `coverage`, `cov`) uploads it.
- For private repos, set `CODECOV_TOKEN` (see `.env.example`) or export it in your shell. Public
  repos typically need no token.
