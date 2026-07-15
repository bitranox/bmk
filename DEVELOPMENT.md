# Development

## Make Targets

| Target                  | Description                                                                                |
|-------------------------|--------------------------------------------------------------------------------------------|
| `help`                  | Show help                                                                                  |
| `install`               | Install package editable                                                                   |
| `dev`                   | Install package with dev extras                                                            |
| `test`                  | Lint, type-check, run tests with coverage, upload to Codecov                               |
| `test-human`            | Run test suite with human-readable output (alias: `th`)                                    |
| `testintegration-human` | Run integration tests with human-readable output (alias: `tih`)                            |
| `run`                   | Run module CLI (requires dev install or src on PYTHONPATH)                                 |
| `version-current`       | Print current version from pyproject.toml                                                  |
| `bump`                  | Bump version (updates pyproject.toml and CHANGELOG.md)                                     |
| `bump-patch`            | Bump patch version (X.Y.Z -> X.Y.(Z+1))                                                    |
| `bump-minor`            | Bump minor version (X.Y.Z -> X.(Y+1).0)                                                    |
| `bump-major`            | Bump major version ((X+1).0.0)                                                             |
| `clean`                 | Remove caches, build artifacts, and coverage                                               |
| `push`                  | Run tests, prompt for/accept a commit message, create (allow-empty) commit, push to remote |
| `build`                 | Build wheel/sdist artifacts via `python -m build`                                          |
| `coverage`              | Generate coverage reports                                                                  |
| `test-slow`             | Run slow integration tests (SMTP, external resources)                                      |
| `dependencies`          | Check and list project dependencies                                                        |
| `dependencies-update`   | Update dependencies to latest versions                                                     |
| `menu`                  | Interactive TUI to run targets and edit parameters (requires dev dep: textual)             |

### Target Parameters (env vars)

- **Global**
  - `PY` (default: `python3`) -- interpreter used to run scripts
  - `PIP` (default: `pip`) -- pip executable used by bootstrap/install

- **install**
  - No specific parameters (respects `PY`, `PIP`).

- **dev**
  - No specific parameters (respects `PY`, `PIP`).

- **test**
  - `COVERAGE=on|auto|off` (default: `on`) -- controls pytest coverage run and Codecov upload
  - `SKIP_BOOTSTRAP=1` -- skip auto-install of dev tools if missing
  - `TEST_VERBOSE=1` -- echo each command executed by the test harness
  - `BMK_OUTPUT_FORMAT=json|text` (default: `json`) -- output format; JSON mode suppresses tool output on success, auto-accepts Makefile updates, runs dependencies silently, and uses concise pytest flags; `--human` flag overrides to `text` for full verbose output
  - `UV_PROJECT_ENVIRONMENT` (default: `.venv`) -- project venv path, absolute or relative to the project; set it when one checkout is used from more than one OS, since a single venv cannot serve both
  - `BMK_NO_VENV_SYNC=1` -- skip creating and syncing the project venv; use the environment as-is
  - Also respects `CODECOV_TOKEN` when uploading to Codecov

- **run**
  - No parameters via `make` (always shows `--help`). For custom args: `python scripts/run_cli.py -- <args>`.

- **version-current**
  - No parameters

- **bump**
  - `VERSION=X.Y.Z` -- explicit target version
  - `PART=major|minor|patch` -- semantic part to bump (default if `VERSION` not set: `patch`)

- **bump-patch** / **bump-minor** / **bump-major**
  - No parameters; shorthand for `make bump PART=...`

- **clean**
  - No parameters

- **push**
  - `BMK_GIT_REMOTE=<name>` (default: `origin`) -- git remote to push to
  - `BMK_GIT_BRANCH=<name>` (default: the current branch) -- branch to push
  - `MSG="..."` -- commit message; the safe channel, passed through the environment, so any
    punctuation and newlines survive. Equivalent to setting `BMK_COMMIT_MESSAGE` yourself.
  - Resolution order is: trailing words / `ARGS` -> `BMK_COMMIT_MESSAGE` -> interactive prompt
    -> `chores` when non-interactive.
  - Do NOT put a message in `ARGS="..."`: it is re-parsed by bash, so `(`, `;`, `` ` `` and `$`
    break or execute, and a newline is rejected by a guard in the Makefile.

- **build**
  - No parameters via `make`. Advanced: call the script directly, e.g. `python scripts/build.py --no-conda --no-nix`.

- **release**
  - `REMOTE=<name>` (default: `origin`) -- git remote to push to
  - Advanced (via script): `python scripts/release.py --retries 5 --retry-wait 3.0`

## Interactive Menu (Textual)

`make menu` launches a Textual-powered TUI to browse targets, edit parameters, and run them with live output.

Install dev extras if you haven't:

```bash
pip install -e .
```

Run the menu:

```bash
make menu
```

### Target Details

- `test`: single entry point for local CI -- runs ruff lint + format check, pyright, pytest (including doctests) with coverage (enabled by default), and uploads coverage to Codecov if configured (reads `.env`). Tool output defaults to JSON mode, which suppresses all tool output when stages pass (only failures produce output). Dependency checking runs silently, Makefile version updates are auto-accepted, and pytest uses `--tb=short -q --no-header` with coverage report display suppressed. Use `bmk test --human` or `BMK_OUTPUT_FORMAT=text` for full verbose output showing all tool output, prompts, and reports.
  - Auto-bootstrap: `make test` will try to install dev tools (`pip install -e .`) if `ruff`/`pyright`/`pytest` are missing. Set `SKIP_BOOTSTRAP=1` to skip this behavior.
- `build`: creates wheel/sdist artifacts.
- `version-current`: prints current version from `pyproject.toml`.
- `bump`: updates `pyproject.toml` version and inserts a new section in `CHANGELOG.md`. Use `VERSION=X.Y.Z make bump` or `make bump-minor`/`bump-major`/`bump-patch`.
- Additional scripts (`pipx-*`, `uv-*`, `which-cmd`, `verify-install`) provide install/run diagnostics.

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
make test                 # ruff + pyright + pytest + coverage (JSON mode, default)
make test-human           # same but with full verbose output (alias: make th)
SKIP_BOOTSTRAP=1 make test  # skip auto-install of dev deps
COVERAGE=off make test       # disable coverage locally
COVERAGE=on make test        # force coverage and generate coverage.xml/codecov.xml
```

**Note:** `make test --human` does not work because Make intercepts `--` flags.
Use `make test-human` or `make th` instead.

**Automation notes**

- `make push` runs the full test suite, checks pip and dependency versions, prompts for a commit message (or takes `MSG="..."`, i.e. the `BMK_COMMIT_MESSAGE` environment variable), and always pushes, creating an empty commit when there are no staged changes. The Textual menu (`make menu -> push`) shows the same behaviour via an input field.

### Versioning & Metadata

- Single source of truth for package metadata is `pyproject.toml` (`[project]`).
- The library reads its own metadata from static constants (see `src/bmk/__init__conf__.py`).
- Do not duplicate the version in code; bump only `pyproject.toml` and update `CHANGELOG.md`.
- Console script name is discovered from entry points; defaults to `bmk`.

### Virtual Environment Isolation (uvx)

When bmk is invoked via `uvx`, it runs in an ephemeral virtual environment that contains
bmk's own dependencies (ruff, pyright, pytest, etc.) but not the target project's dependencies.
This causes tools like pyright and pip-audit to fail if they resolve packages against bmk's venv
instead of the project's.

bmk handles this automatically:
- Before any pipeline that touches the Python environment, bmk creates the project's venv if it is
  missing and syncs it to `pyproject.toml`, then points `VIRTUAL_ENV` at it
- Broken venvs (stale NFS mounts, missing `pyvenv.cfg`) are detected and ignored
- If no valid venv exists (provisioning skipped or failed), bmk unsets `VIRTUAL_ENV` so tools fall
  back to their own discovery (e.g., pyright reads `[tool.pyright]` from the project's
  `pyproject.toml`) and pins pip-audit at bmk's own interpreter

The venv path comes from `UV_PROJECT_ENVIRONMENT` (absolute, or relative to the project;
default `.venv`); `BMK_NO_VENV_SYNC=1` skips provisioning. Because the sync is exact and upgrading,
packages installed into the venv by hand do not survive it. See `CLAUDE.md` for why both flags are
needed and how the ordering interacts with the frozen `StageContext`.

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

- `make test` invokes `pip-audit` to check for known vulnerabilities. If pip-audit reports vulnerabilities, address them by pinning fixed versions in `[project.optional-dependencies.dev]`.

### CI & Publishing

GitHub Actions workflows are included:

- `.github/workflows/ci.yml` -- lint/type/test, build wheel/sdist, and verify pipx and uv installs (CI-only; no local install required).
- `.github/workflows/release.yml` -- on tags `v*.*.*`, builds artifacts and publishes to PyPI when `PYPI_API_TOKEN` secret is set.

To publish a release:
1. Bump `pyproject.toml` version and update `CHANGELOG.md`.
2. Tag the commit (`git tag v0.1.1 && git push --tags`).
3. Ensure `PYPI_API_TOKEN` secret is configured in the repo.
4. Release workflow uploads wheel/sdist to PyPI.

### Local Codecov uploads

- `make test` (with coverage enabled) generates `coverage.xml` and `codecov.xml`, then attempts to upload via the Codecov CLI or the bash uploader.
- For private repos, set `CODECOV_TOKEN` (see `.env.example`) or export it in your shell.
- For public repos, a token is typically not required.
- Because Codecov requires a revision, the test harness commits (allow-empty) immediately before uploading. Remove or amend that commit after the run if you do not intend to keep it.
