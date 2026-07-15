# Contributing Guide

Thanks for helping improve **bmk**. The sections below summarise the day-to-day workflow, highlight the repository automation, and list the checks that must pass before a change is merged.

## 1. Workflow Overview

1. Fork and branch -- use short, imperative branch names (`feature/cli-extension`, `fix/codecov-token`).
2. Make focused commits -- keep unrelated refactors out of the same change.
3. Run `make test` locally before pushing (see the automation note below).
4. Update documentation and changelog entries that are affected by the change.
5. Open a pull request referencing any relevant issues.

## 2. Commits & Pushes

- Commit messages should be imperative (`Add rich handler`, `Fix CLI exit codes`).
- The test harness (`make test`) runs the full lint/type/test pipeline but leaves the repository untouched; create commits yourself before pushing or uploading coverage artifacts.
- `make push` always performs a commit before pushing. It prompts for a message when run interactively, honours `MSG="..."` (or the `BMK_COMMIT_MESSAGE` environment variable) when provided, and creates an empty commit if nothing is staged.
- **Pass a commit message with `MSG="..."`, not `ARGS="..."`.** `ARGS` is expanded into the recipe and re-parsed by bash, so punctuation is treated as code: `fix(cli): x` is a syntax error, `a; b` runs `b`, and a backtick or `$(...)` executes. A newline in `ARGS` is rejected outright, because make would otherwise commit a truncated subject and run the rest as a command. `MSG` is passed through the environment, so any message survives intact, newlines included:

  ```bash
  make push MSG="fix(cli): subject line

  Body with (parens), a ; and a literal $HOME - all safe."
  ```

  Bare trailing words (`make push fix login bug`) remain fine for a simple one-line message.

## 3. Coding Standards

- Apply the repository's Clean Architecture / SOLID rules (see `CLAUDE.md` and the system prompts listed there).
- Prefer small, single-purpose modules and functions; avoid mixing orthogonal concerns.
- Free functions and modules use `snake_case`; classes are `PascalCase`.
- Keep runtime dependencies minimal. Use the standard library where practical.

## 4. Tests & Tooling

- `make test` runs Ruff (lint + format check), Pyright, and Pytest with coverage. Tool output defaults to JSON mode, where the stage runner captures all output and only displays it when a stage fails -- on success, a single JSON summary is emitted. Dependencies are checked silently, Makefile version updates are auto-accepted, and pytest uses concise flags (`--tb=short -q --no-header`). For full verbose output, use `make test-human` (alias `make th`) or set `BMK_OUTPUT_FORMAT=text`. Note: `make test --human` does not work because Make intercepts `--` flags. Coverage is `on` by default; override with `COVERAGE=off` if you explicitly need a no-coverage run.
- The harness auto-installs dev tools with `pip install -e .` when Ruff, Pyright, or Pytest are missing. Skip this by exporting `SKIP_BOOTSTRAP=1`.
- Codecov uploads require a commit (provided by the automatic commit described above). For private repositories set `CODECOV_TOKEN` in your environment or `.env`.
- Tests follow a narrative style: prefer names like `test_when_<condition>_<outcome>()`, keep each case laser-focused, and mark tests with the provided markers. OS scope: `os_agnostic`, `os_windows`, `os_macos`, `os_posix`, `os_linux` (label only - pair each with its own `skipif(sys.platform ...)`). Run scope: `local_only` for a test needing a local resource CI lacks (run by `make test` locally, excluded from CI via `-m "not local_only"`) and `integration` for a long-running/external test (excluded from `make test`, run via `make testintegration`). See DEVELOPMENT.md "Test Markers" for the full model.
- Whenever you add a CLI behaviour or change metadata fallbacks, update the relevant story in `tests/test_cli.py` or `tests/test_metadata.py` so the specification remains complete.

## 5. Documentation Checklist

Before opening a PR, confirm the following:

- [ ] `make test` passes locally (and you removed the auto-created Codecov commit if you do not want to keep it).
- [ ] Relevant documentation (`README.md`, `DEVELOPMENT.md`, `docs/systemdesign/*`) is updated.
- [ ] No generated artefacts or virtual environments are committed.
- [ ] Version bumps, when required, touch **only** `pyproject.toml` and `CHANGELOG.md`.

## 6. Security & Configuration

- Never commit secrets. Tokens (Codecov, PyPI) belong in `.env` (ignored by git) or CI secrets.
- Sanitise any payloads you emit via logging once richer logging features ship.

Happy hacking!
