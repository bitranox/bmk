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

| Variable                 | Default  | Effect                                                                           |
|--------------------------|----------|----------------------------------------------------------------------------------|
| `BMK_OUTPUT_FORMAT`      | `json`   | `json` or `text`. JSON suppresses tool output on success. `--human` forces text. |
| `UV_PROJECT_ENVIRONMENT` | `.venv`  | Project venv path, absolute or relative to the project.                          |
| `BMK_NO_VENV_SYNC`       | unset    | `1` skips creating/syncing the project venv; use the environment as-is.          |
| `BMK_COMMIT_MESSAGE`     | unset    | Commit message for `commit` / `push`. `MSG="..."` sets this for you.             |
| `BMK_GIT_REMOTE`         | `origin` | Remote that `push` targets.                                                      |
| `BMK_GIT_BRANCH`         | current  | Branch that `push` targets.                                                      |
| `CODECOV_TOKEN`          | unset    | Token for Codecov upload; also read from `.env`.                                 |
| `DEVELOPMENT_MODE`       | unset    | `1` re-raises unexpected exceptions in email commands with full tracebacks.      |

Configuration settings additionally accept `BMK___<SECTION>__<KEY>` environment overrides and
`.env` entries - see [docs/pyproject-reference.md](docs/pyproject-reference.md) and
`src/bmk/adapters/config/`.

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

1. Find what actually forces the vulnerable version (`uv pip compile --extra dev pyproject.toml`).
   A CVE on a transitive package usually means another dependency CAPS it below the fix.
2. Remove or disable the capper if there is one - that fixes it with no exclusion. Comment the line
   out with the reason and the re-enable condition rather than deleting it.
3. Only if no capper exists and no fixed release does, add the id to `[tool.pip-audit].ignore-vulns`
   with an inline note. Note the tables are different vocabularies: `ignore-vulns` takes
   PYSEC/GHSA/CVE ids, `[tool.bandit].skips` takes bandit check ids (`B###`). A PYSEC id in
   `[tool.bandit].skips` is silently inert.

bmk itself declares its whole toolchain as runtime dependencies and ships no `[dev]` extra, so a
floor for bmk goes in `[project.dependencies]`. See the grouped rationale in `pyproject.toml`.

### CI & Publishing

GitHub Actions workflows:

- `.github/workflows/default_cicd_public.yml` - lint, type-check, test across the OS/Python matrix,
  and build artifacts.
- `.github/workflows/default_release_public.yml` - on tags `v*.*.*`, builds artifacts and publishes
  to PyPI.
- `.github/workflows/codeql.yml` - CodeQL analysis.

These files are managed by an external template. Do not edit them here; change them in the
`default_cicd_public` template and redistribute.

Publishing uses hybrid auth: the release workflow uses the `PYPI_API_TOKEN` secret when it is set,
and otherwise publishes via an OIDC Trusted Publisher (the publish job has `id-token: write` and
runs in the `pypi` environment). A project works on a token and migrates to OIDC with no workflow
change; if PyPI reports a Trusted Publisher is configured but the upload still used a token, the
secret is still present and must be deleted.

To publish a release:

1. `make bump-patch` (or `-minor` / `-major`) to update `pyproject.toml` and `CHANGELOG.md`.
   A non-final version is finalized rather than stepped past (`1.2.3rc1` patch-bumps to
   `1.2.3`); see `docs/pyproject-reference.md` for the full table.
2. `make release` to tag `v` + the project version, push, and create the GitHub release.
3. Or `make ship` to push, wait for CI, release, and wait for the release workflow - CI-gated end to
   end.

### Local Codecov uploads

- `make test` generates `coverage.xml` (the name comes from `[tool.scripts.test]
  .coverage-report-file`).
- `make codecov` (aliases `coverage`, `cov`) uploads it.
- For private repos, set `CODECOV_TOKEN` (see `.env.example`) or export it in your shell. Public
  repos typically need no token.
