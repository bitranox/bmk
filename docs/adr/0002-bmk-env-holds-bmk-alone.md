# ADR 0002: bmk's Environment Holds bmk Alone, and Is Shared

**Status:** Accepted (3.8.0)

## Context

From 2.9.0 to 3.7.x the deployed Makefile installed bmk **together with the target
project's dependencies** into one environment:

    uv tool install --reinstall "bmk>=$(BMK_MIN)" --with-editable ".[dev]"

`--with` makes uv resolve bmk and the project **as one dependency problem**. That was
adopted in 2.9.0 to remove a `PYTHONPATH` hack, and it was never revisited. Every release
since patched a consequence of it rather than the cause:

| Version | Symptom that was fixed                                                                             |
|---------|----------------------------------------------------------------------------------------------------|
| 3.1.7   | test-only deps missing from the env bmk ran pytest with                                            |
| 3.3.1   | the install silently degrading to an env without `[dev]`                                           |
| 3.4.0   | two projects overwriting each other's dependencies in one machine-wide env (`six`/`chardet`)       |
| 3.5.0   | `codecov-cli` capping `click<8.3.0` silently backtracked **bmk itself** to 3.1.7                   |
| 3.6.0   | pyright walking the co-resolved site-packages: 6h20m at 78% CPU, 21 repos                          |
| 3.6.1   | a **yanked** transitive floor (`build` 1.5.1) made bmk uninstallable, bricking `make` in ~46 repos |

Two further problems were never named anywhere:

1. **The tests ran in the wrong environment.** `python_cmd` was always `sys.executable`
   (bmk's own interpreter), so pytest ran in bmk's env, while pyright (`VIRTUAL_ENV`) and
   pip-audit (`PIPAPI_PYTHON_LOCATION`) inspected the project's `.venv`. Since 3.2.0 those
   are two independently resolved trees, and they differ in practice: the project venv
   receives every extra, bmk's env only ever received `[dev]`. A real bug hid in that gap -
   pwshpy's `[full]` extra is present in `.venv` and absent from bmk's env, so 16 .NET
   tests took a different branch depending on which env ran them, invisible to both
   `make test` and CI.
2. **A dependency cycle.** bmk depends on `lib_cli_exit_tools`, `lib_log_rich`,
   `lib_layered_config` and `btx_lib_mail`. All four are themselves bmk-managed repos, so
   their `make` co-resolved bmk *with the very library being developed*. bmk requires
   `lib_layered_config>=5.6.0` while the working copy is 5.6.0 - one floor bump above the
   dev version and that repo could not `make test` at all.

## Decision

**bmk's environment holds bmk and its toolchain. Nothing of the project.**

1. The common path is `uv tool upgrade bmk` - no `--with`. It is a plain upgrade rather than
   `uv tool install --reinstall --force "bmk>=$(BMK_MIN)"` precisely *because* the env is
   shared (point 3): an unconditional rebuild before every target deleted it out from under a
   bmk still running in another repo. The reinstall form remains as the repair path, taken when
   `python -m bmk_selfcheck` finds the env absent or partially written.
2. The tests run in the **project's** venv: `resolve_test_python` (mirroring the existing
   `resolve_audit_python`) resolves it at stage time, and `_coverage.py` takes it as
   `--python` instead of using `sys.executable`. It never falls back to bmk's interpreter -
   a silent fallback is the defect itself - so with no project venv it fails, naming the fix.
3. The env is therefore identical for every repo, so it is **shared**: uv's own tool dir,
   no `UV_TOOL_DIR` override, no `.venv-bmk` per project.
4. bmk's OWN development Makefile is the deliberate exception: it installs from local
   source (`--editable ./`), which must stay per-project, or every other repo on the
   machine would silently run bmk out of a working tree.

## Consequences

- **The whole class of co-resolution bugs is gone.** Nothing of the project can cap,
  backtrack, or break bmk's install. `BMK_MIN` is kept as inert insurance.
- **One environment, one truth.** pytest, pyright and pip-audit all resolve the project's
  `.venv`, so the suite and the audit describe the same environment.
- **The cycle is gone.** A bmk-dependency repo no longer resolves bmk against itself.
- **~300MB is no longer duplicated per repo** (mostly pyright's bundled Node): one shared
  env instead of ~46. `pyright[nodejs]` therefore stays - paid once, and it keeps bmk's
  toolchain hermetic with no system Node.
- **The project must declare its own test tooling** (`pytest`, `pytest-cov`) in `[dev]`.
  `ensure_project_venv` already syncs `.[dev]`, and the bitranox template declares them.
  A project that does not gets a clear failure rather than a silent pass in bmk's env.
- **Projects keep a stale `.venv-bmk`** until removed; it is gitignored and disposable.
