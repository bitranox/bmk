# Development

## Make Targets

| Target            | Description                                                                                |
|-------------------|--------------------------------------------------------------------------------------------|
| `help`            | Show help                                                                                  |
| `install`         | Install package editable                                                                   |
| `dev`             | Install package with dev extras                                                            |
| `test`            | Lint, type-check, run tests with coverage, upload to Codecov                               |
| `test-human`      | Run test suite with human-readable output (alias: `th`)                                    |
| `testintegration-human` | Run integration tests with human-readable output (alias: `tih`)                      |
| `run`             | Run module CLI (requires dev install or src on PYTHONPATH)                                 |
| `version-current` | Print current version from pyproject.toml                                                  |
| `bump`            | Bump version (updates pyproject.toml and CHANGELOG.md)                                     |
| `bump-patch`      | Bump patch version (X.Y.Z -> X.Y.(Z+1))                                                    |
| `bump-minor`      | Bump minor version (X.Y.Z -> X.(Y+1).0)                                                    |
| `bump-major`      | Bump major version ((X+1).0.0)                                                             |
| `clean`           | Remove caches, build artifacts, and coverage                                               |
| `push`            | Run tests, prompt for/accept a commit message, create (allow-empty) commit, push to remote |
| `build`           | Build wheel/sdist artifacts via `python -m build`                                          |
| `coverage`        | Generate coverage reports                                                                  |
| `test-slow`       | Run slow integration tests (SMTP, external resources)                                      |
| `dependencies`    | Check and list project dependencies                                                        |
| `dependencies-update` | Update dependencies to latest versions                                                |
| `menu`            | Interactive TUI to run targets and edit parameters (requires dev dep: textual)             |

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
  - `REMOTE=<name>` (default: `origin`) -- git remote to push to
  - `COMMIT_MESSAGE="..."` -- optional commit message used by the automation; if unset, the target prompts (or uses the default `chore: update` when non-interactive).

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

## Running Integration Tests

Some tests require external resources (SMTP servers, databases) and are excluded from the default test run. These are marked with `@pytest.mark.local_only`.

### Quick Reference

| Command | What it runs |
|---------|--------------|
| `make test` | All tests EXCEPT `local_only` (default for CI) |
| `make test-slow` | ONLY `local_only` integration tests |
| `pytest tests/` | ALL tests (no marker filter) |

### Email Integration Tests

To run email tests that actually send messages:

1. **Create a `.env` file** in the project root with your SMTP settings:

```bash
# .env (copy from .env.example)
EMAIL__SMTP_HOSTS=smtp.example.com:587
EMAIL__FROM_ADDRESS=sender@example.com
EMAIL__RECIPIENTS=recipient@example.com
EMAIL__SMTP_USER=your_username
EMAIL__SMTP_PASSWORD=your_password
```

2. **Run the integration tests**:

```bash
make test-slow
```

3. **Or run specific email tests**:

```bash
pytest tests/test_cli_email_smtp.py -v
```

### Adding New Integration Tests

Mark tests that require external resources:

```python
@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_real_external_service(...):
    """Integration test requiring external service."""
    ...
```

These tests will be skipped in CI but run with `make test-slow`.

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

- `make push` runs the full test suite (`python -m scripts.test`), checks pip and dependency versions, prompts for a commit message (or reads `COMMIT_MESSAGE="..."`), and always pushes, creating an empty commit when there are no staged changes. The Textual menu (`make menu -> push`) shows the same behaviour via an input field.

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
- If the target project has a valid `.venv/` directory (with `pyvenv.cfg`), bmk sets `VIRTUAL_ENV` to point at it
- Broken venvs (stale NFS mounts, missing `pyvenv.cfg`) are detected and ignored
- If no valid `.venv/` exists, bmk unsets `VIRTUAL_ENV` so tools fall back to their own discovery
  (e.g., pyright reads `[tool.pyright]` from the project's `pyproject.toml`)

**Requirement:** The target project must have its dependencies installed in `.venv/`
(the standard convention for uv-managed projects). Run `uv sync` or `pip install -e .`
in the target project before running `bmk test`.

### Private Repository Dependencies

Projects can depend on packages from private Git repositories using PEP 440 direct references
in `[project.dependencies]`:

```toml
[project]
dependencies = [
    "my_private_lib @ git+https://github.com/MyOrg/my_private_lib.git",
]
```

bmk automatically skips these during PyPI dependency checking — direct URL references
are not on PyPI and need no version comparison.

Authentication is handled by global git config URL rewriting, not by bmk.
To scope access to a single organisation:

```bash
git config --global url."https://<token>@github.com/MyOrg/".insteadOf "https://github.com/MyOrg/"
```

This keeps credentials out of project files and `.env` — git handles auth transparently.

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
