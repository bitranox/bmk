# Changelog

All notable changes to this project will be documented in this file following
the [Keep a Changelog](https://keepachangelog.com/) format.


## [Unreleased]

## [3.7.1] 2026-07-15 15:19:16

### Fixed
- **`make test` works again in projects with platform-specific dependencies.** The dependency
  sync rebuilt every requirement from its parsed parts as `name>=version`, which DROPPED the
  PEP 508 environment marker. A dependency declared for one platform was then demanded on
  every platform - and could not possibly install: `pywin32>=312; sys_platform == 'win32'`
  became a bare `pywin32>=312`, which on Linux dies with "no wheels with a matching platform
  tag (e.g. manylinux_2_43_x86_64)" and takes the whole run down at the `update_deps` stage.
  The package is correctly absent off-platform, so it always reads as NOT INSTALLED and is
  queued for install on every single run. Any cross-platform project hits this; found in
  pwshpy, which declares pywin32/wmi for win32 and jeepney/systemd for linux.

  `_marker_of()` now preserves the marker and appends it AFTER the version, so uv receives a
  valid requirement and evaluates the marker itself, skipping the package cleanly
  off-platform (verified against real uv: the marked form exits 0 on Linux, the bare form
  fails to resolve). Order matters: `pkg>=1; sys_platform == 'win32'` is a requirement,
  `pkg; sys_platform == 'win32'>=1` is not. This is the same bug class as the extras handling
  beside it, already fixed once for `pyright[nodejs]`: a spec rebuilt from the bare name is
  not the spec you declared.
- **bmk's own Makefile no longer discards commit messages.** It is hand-authored rather than
  generated from the bundled template, so 3.7.0's commit-message hardening never reached it:
  `make push MSG="..."` here silently ignored `MSG` and committed the non-interactive default
  `chores`, throwing the message away (it did exactly that to `909aa14`). It now carries the
  same `MSG` export, `"$(ARGS)"` quoting and newline guard, and
  `tests/test_makefile_template_integrity.py` asserts the two files agree on those
  invariants, so the drift cannot recur silently.

## [3.7.0] 2026-07-15 14:34:47

### Added
- **`make push MSG="..."` / `make commit MSG="..."` - a commit-message channel that cannot be
  mangled.** `MSG` is exported into the environment as `BMK_COMMIT_MESSAGE` rather than placed on
  a shell command line, so the message is never word-split or re-parsed and arrives byte for byte:
  punctuation, quotes, `$`, backticks, and **newlines**. A multi-line `MSG` becomes a real commit
  subject plus body, which was previously impossible from `make` at all.

  ```
  make push MSG="fix(cli): subject line

  Body with (parens), a ; and a literal $HOME - all safe."
  ```

  It is `$(value MSG)`, not `$(MSG)`, on purpose: make expands the latter before exporting, which
  silently turns a literal `$HOME` in a message into `OME`.

### Fixed
- **A commit message is no longer parsed as shell code.** `commit` and `push` now pass
  `"$(ARGS)"` quoted. make expands `$(ARGS)` into the recipe and hands the RESULT to bash, which
  applied its full grammar to prose that was never escaped for it: `fix(cli): x` died with
  `syntax error near unexpected token '('`, `a; b` ran `b` as a command, `*` globbed against the
  repo, and a backtick or `$(...)` **executed**. Quoting costs nothing here because both commands
  take only a message (`nargs=-1`) and bmk re-joins the args with spaces, so a single quoted word
  round-trips unchanged and an empty `ARGS` still falls through to `BMK_COMMIT_MESSAGE` or the
  prompt. Flag-taking targets (`test`, `run`, `custom`, ...) deliberately keep `$(ARGS)` unquoted,
  since quoting would collapse `--human -k foo` into one argv element. `ship` also stays unquoted:
  unlike commit/push it takes options as well as a message, so it uses `MSG=` instead.
- **A newline in `ARGS` is now refused instead of silently truncating the commit.** This is the one
  case quoting cannot fix: make expands `ARGS` into the recipe TEXT, so a newline becomes a recipe
  LINE BREAK. make then ran line 1 - committing and pushing a truncated subject - and line 2 as a
  separate shell command. The error surfaced only afterwards, once the wrong message was already
  public. A `$(error)` now fires at parse time, before anything is staged, and names `MSG=` as the
  fix. This had already shipped bad commit messages more than once.
- The template's own usage header advertised `make test --verbose` as the way to forward flags. It
  never worked: make parses a bare `--verbose` as one of its OWN options and exits with "unknown
  option". Corrected to `make test ARGS="--verbose"`.
- Documentation named a `COMMIT_MESSAGE` environment variable (`CONTRIBUTING.md`,
  `DEVELOPMENT.md`) that the code has never read - it reads `BMK_COMMIT_MESSAGE`, so anyone
  following the docs got a commit message of `chores`. `DEVELOPMENT.md` also documented `REMOTE=`,
  where the code reads `BMK_GIT_REMOTE`, and gave `chore: update` as the non-interactive default,
  where the code uses `chores`.

## [3.6.1] 2026-07-15 14:00:30

### Fixed
- **bmk is installable again: its `build` floor no longer points at a yanked release.** PyPI yanked
  `build` 1.5.1 (upstream shipped unintended breaking changes and plans to re-release them as a new
  major version). A yanked release is invisible to a range resolve and nothing newer exists, so
  bmk's `build>=1.5.1` floor had zero candidates and `uv tool install "bmk>=3.6.0"` failed outright
  with "your requirements are unsatisfiable". Because the Makefile installs bmk together with the
  project's dependencies before every target, this bricked `make` entirely - no test, no lint, no
  build - in every repo on bmk 3.6.0, without a single line changing in those repos.

  The floor is now `build>=1.5.0`, the newest release upstream still stands behind. This is a
  toolchain floor and not a CVE floor, so nothing is given up. The pin carries an inline comment
  explaining why it must not be raised back to 1.5.1 by a routine dependency sweep; only a real
  1.5.2+ release should move it.

## [3.6.0] 2026-07-14 20:28:03

### Fixed
- **bmk keeps its own venvs out of the project's pyright run, so a type-check cannot spin
  forever.** pyright's `exclude` REPLACES its built-in defaults (`**/node_modules`,
  `**/__pycache__`, `**/.*`) rather than extending them, so any project listing an exclude of its
  own - `exclude = ["scripts/menu.py"]`, the bitranox template's default - silently loses `**/.*`,
  the only rule keeping dot-directories out. That was harmless until 3.2.0 began provisioning
  `.venv` and 3.4.0 put bmk in `.venv-bmk`: pyright then walked thousands of site-packages files in
  strict mode and never returned. Measured, not theoretical - one such run spun for **6h20m at 78%
  CPU** and produced nothing, with no error saying why, and 21 repos were affected.
  `ensure_venv_typecheck_excluded` now appends the venv directories bmk creates to
  `[tool.pyright].exclude`, mirroring `ensure_venv_ignored`. On a real repo this took pyright from
  *never finishing* to **15s** (6260 files analyzed -> 35).

  It deliberately touches nothing when the project has no `exclude` key (pyright's `**/.*` default
  already covers the venvs, and writing a list would REPLACE those defaults - causing the very bug)
  or when an `include` list already narrows the scope. Existing coverage in any spelling
  (`**/.*`, `.venv`, `**/.venv/**`, `.venv/`) is recognised, so the list cannot grow on repeat runs.

## [3.5.0] 2026-07-14 18:40:00

### Fixed
- **The template installs `bmk>=$(BMK_MIN)` instead of a bare `bmk`, so bmk can no longer be
  silently downgraded.** bmk and the project's dependencies resolve TOGETHER, so a project
  dependency that caps something bmk requires does not fail - uv backtracks BMK to an older
  release that fits, with no error. Real and measured: `codecov-cli` caps `click<8.3.0` while bmk
  requires `click>=8.4.2` (CVE-2026-7246), so an unpinned `bmk` resolved to **3.1.7** and those
  repos never received another bmk update. The floor turns that into an unsatisfiable-requirements
  error naming the offending package. It is inert otherwise: with no capper, `bmk>=X` still
  resolves to the newest release. `_sync_initconf.py` keeps `BMK_MIN` equal to the package
  version, and a test asserts it, so the floor cannot lag a release.

## [3.4.0] 2026-07-14 18:05:00

### Changed
- **bmk now lives in a per-project tool env (`.venv-bmk`) instead of one machine-wide env.**
  The env carries the project's own dependencies, so a single shared env could never serve two
  projects: whichever ran `make` last won, and the other silently got the wrong dependency tree.
  Measured, not theoretical - a project depending on `six` and one depending on `chardet` were
  shown to overwrite each other. Per-project means "is the env correct" is a question about one
  repo alone. The Makefile invokes `./.venv-bmk/bin/bmk` directly rather than a bare `bmk` from
  PATH, so no machine-wide install can shadow it. uv writes a `.gitignore` inside the env, and
  bmk also declares `.venv-bmk` in the project's `.gitignore` and untracks it if git ever held
  it. `.venv-bmk` is disposable - delete it and the next `make` rebuilds it.
- **The project is installed editable** (`--with-editable ".[dev]"`; `--editable ./` in bmk's own
  development Makefile, where bmk IS the project). The project's code in the env is then the
  working tree rather than a snapshot. A non-editable install happened to work only because tools
  run with `cwd=<project>`, whose source shadows the snapshot on `sys.path` - an accident of
  import order that would serve stale code to anything running from another directory. As a side
  effect, editing bmk's own source is live immediately.

## [3.3.1] 2026-07-14 16:20:00

### Fixed
- `_ensure_bmk` (the target that runs before EVERY make invocation) could silently leave the
  tool env wrong, in two ways that compounded. Its fallback chain dropped the project's
  `[dev]` extra, producing an env without the test dependencies - `make test` then died with a
  ModuleNotFoundError (`hypothesis`, `starlette.testclient`) far from the cause. And the last
  fallback omitted `--reinstall`, which makes `uv tool install` NO-OP when the tool is already
  present, so the env could stay pinned at an old bmk version indefinitely, running old
  pipeline code against new sources while still reporting pass. `2>/dev/null` hid both.
  Now both attempts are identical and complete (`--reinstall` + `.[dev]`, unsuppressed), with
  one retry for the transient `__pycache__` removal race ("Directory not empty", os error 39);
  if both fail, make fails loudly, because a degraded env is not a safe state to continue from.
  The old `.[dev]` -> `.` fallback existed for a failure that cannot occur: a project without a
  `[dev]` extra does not fail, uv warns and installs the base deps.
- The same defect in bmk's own development `Makefile`, where it had pinned the local tool env
  at 3.1.7 while the source was at 3.3.0.

### Added
- `tests/test_makefile_template_integrity.py` guards the bundled template: its header matches
  `[project].version` (so a release cannot ship a template labelled with the wrong version),
  and `_ensure_bmk` cannot regress to suppressing errors, dropping `[dev]`, omitting
  `--reinstall`, or losing its retry.

### Changed
- The Makefile-regeneration tests plant a distinctive stale-body marker instead of the string
  `"old"`, which is a substring of ordinary English and made the assertion fail whenever the
  template's own prose used the word.

## [3.3.0] 2026-07-14 14:45:00

### Added
- bmk keeps the venv it creates out of git. After provisioning it drops the venv from the index
  if git tracks it (`git rm --cached`, so the files stay on disk) and appends the venv names to
  `.gitignore` when nothing already ignores them - the managed venv's own name plus `.venv` and
  `.venv-win`, so a checkout used from two operating systems does not leave the other's venv as
  untracked noise. A tracked venv is not cosmetic: the sync rewrites its contents on every run,
  so git would report thousands of modified files each time and a commit would sweep them in.
  `git check-ignore` decides what is already covered, so an existing rule (including a wildcard,
  a nested `.gitignore`, or a global excludesFile) is respected rather than duplicated. The
  untrack always prints, even in JSON mode, because it stages deletions and `push` commits
  automatically. Skipped outside a git work tree, and never fatal.

### Fixed
- `clean` no longer removes the project venv. Since 3.2.0 bmk provisions and syncs that venv,
  and `push` cleans at order 30 right after `test`, so cleaning it deleted the venv bmk had
  just built and forced a full re-resolve on the next command - gigabytes of re-download per
  push on a project with a heavy dependency tree, and pointless besides, since the sync already
  removes whatever the manifest no longer asks for. Removed from the built-in fallback patterns
  and from bmk's own `[tool.clean].patterns`. The warning bmk prints for a project with no
  `[tool.clean]` section is generated from those fallback patterns, so it no longer suggests
  adding the venv either. A project that lists a venv in its own `[tool.clean].patterns` keeps
  the old behaviour; remove it there to opt in. Delete a venv by hand when you want it gone.

## [3.2.0] 2026-07-14 13:58:00

### Added
- bmk now provisions and syncs the target project's own venv before running any
  pipeline that reads or writes the Python environment (`test`, `cov`,
  `test_integration`, `push`, `deps`, `deps_update`, `bld`). An existing venv is
  updated in place. The sync both removes packages the manifest no longer asks for
  and re-resolves the ones it does, so a venv that has drifted from
  `pyproject.toml` - including a stale unconstrained transitive sitting on a
  vulnerable release - is brought back into line rather than silently believed.
- `UV_PROJECT_ENVIRONMENT` selects the venv path (absolute, or relative to the
  project; default `.venv`), so a tree shared between operating systems can keep a
  separate venv per OS (e.g. `.venv-win`) instead of rebuilding one over the other.
- `BMK_NO_VENV_SYNC=1` skips provisioning entirely.

### Fixed
- `deps update` installed into whatever interpreter launched bmk instead of the
  project's venv. bmk's helpers run in-process, so on a machine where bmk was
  started from a shared editor venv, every project's dependencies were installed
  into that shared environment - a project with a large dependency tree could add
  gigabytes to an environment it did not own. Installs now target the project venv
  via `uv pip install --python`, and a project with no venv skips the install
  rather than falling back to the ambient interpreter.
- A stale project venv made the gates report on packages the project does not
  actually resolve: pip-audit reported CVEs from packages left behind in the venv,
  while the project's real dependency resolution was masked. The venv is now synced
  to `pyproject.toml` before the gates read it.
- `deps update` rewrote `pyproject.toml` by regular-expression substitution on the
  file's raw text, which could not distinguish a dependency from the same
  characters in a comment. Updates now edit the parsed document, so comments,
  formatting and unrelated entries survive.
- `deps update` reported success even when the install failed. The install's exit
  code is now propagated.
- `deps update` dropped extras when installing (`pyright[nodejs]` was installed as
  `pyright`), so an extra's dependencies were silently missing.
- `deps update` could pass `--break-system-packages` and install into a system
  interpreter. Removed: with an explicit venv target there is nothing to override.
- `bmk codecov` failed the run when `codecov-cli` was not installed but a
  `CODECOV_TOKEN` was configured, turning `make test` red for a missing optional
  uploader that says nothing about the code under test. A missing uploader is now
  skipped with a warning, the same way a missing token already was; only a real
  upload attempt that fails is still an error.

## [3.1.7] 2026-07-10 10:52:43

### Fixed
- `make test` now provisions bmk's tool venv with the project's `[dev]` extra
  (`uv tool install ... --with ".[dev]"`, falling back to base deps when a project
  has no `[dev]` extra), so test-only dependencies the tests import - fakes,
  test-support libraries, property-test helpers - are present in the interpreter
  bmk runs pytest with. Previously only base deps were installed, so a hermetic
  test importing a `[dev]`-only package failed locally even though CI (which
  installs `[dev]`) passed.

## [3.1.6] 2026-07-10 09:53:04

### Fixed
- PowerShell (`.ps1`) and shell (`.sh`) linting now skip any `.venv`-prefixed
  directory, not just `.venv` - so a dual-OS layout that keeps a separate Windows
  virtualenv (`.venv-win`) or Linux one (`.venv-linux`) no longer trips the linter
  on vendored scripts bundled inside it (e.g. `Activate.ps1`, `npm.ps1`).

## [3.1.5] 2026-07-06 17:03:41

### Fixed
- **Tool stages failed on Windows (and any host without a global ruff/pytest on `PATH`)**
  with `FileNotFoundError` / `WinError 2` at the first tool stage (e.g. `ruff_format_apply`).
  `uv tool install ... --with .` installs bmk's toolchain (ruff/pytest/pyright/bandit/
  pip-audit/lint-imports) into bmk's own venv but exposes only the `bmk`/`mk` entry points,
  so the tools' bin dir is not on `PATH`, and tool stages spawn those tools by bare name.
  On Windows `CreateProcess` resolves the executable against the *parent* process `PATH`,
  not the child `env`, so pointing the child env's `PATH` at the tools was not enough.
  `run_argv` now resolves `argv[0]` to an absolute path via `shutil.which` against the child
  `PATH` before spawning, and `build_context` prepends bmk's own venv bin dir
  (`Path(sys.executable).parent`) to that `PATH`. Bare-name tool stages now resolve on every
  OS and are pinned to bmk's own toolchain rather than whatever ruff/pytest sits first on
  `PATH`. No-op on Linux/macOS, where the child env `PATH` was already honored. This was the
  first run of bmk on Windows, on a project living on a shared network (UNC-backed) mount;
  the `uv tool install --from ./` build from that mount itself worked fine (uv used the
  drive-letter `file:///V:/...` form, not an extended `\\?\UNC\...` path), so no install or
  Makefile change was needed.

### Added
- `actions._resolve_executable`: resolves a bare-name `argv[0]` against the child `PATH`
  (honouring `PATHEXT` on Windows, so `ruff` finds `ruff.exe`) before `subprocess.Popen`,
  and leaves an unresolvable tool unchanged so the original `FileNotFoundError` still surfaces.
- `context._prepend_tool_bin_to_path`: puts bmk's own venv bin dir first on the child `PATH`,
  giving `shutil.which` a place to find the toolchain and letting grandchild processes see it.

## [3.1.4] 2026-07-03 11:41:32

### Fixed
- **`.venv`-vs-clean race in `make push`.** `push` built via the `bld` pipeline (which
  cleans first) in the same parallel batch as `test`; that clean rmtree'd the project
  `.venv` and tool caches while the concurrent test tools were pinned to them
  (`VIRTUAL_ENV` for pyright, `PIPAPI_PYTHON_LOCATION` for pip-audit). pip-audit crashed
  with `FileNotFoundError`; pyright and cache deletions were latent flakiness. `push` now
  builds via a direct `python -m build` and runs its only `clean` at order 30, strictly
  after `test`, so every pin stays valid through the build+test window - fixing the whole
  class of clean-vs-test races, not just `.venv`.

### Added
- `actions.PipAuditAction` and `context.resolve_audit_python`: the `pip_audit` stage now
  re-resolves its interpreter when it runs (the pinned `.venv` if it still exists, else
  bmk's own interpreter) and, if pip-audit fails because the interpreter vanished mid-run
  (a concurrent clean in a custom overlay pipeline), retries once against bmk's own
  interpreter. Robust to a removed `.venv` regardless of pipeline structure. Adds a
  `local_only` integration test that drives the removed-`.venv` path end to end.

### Changed
- `actions.ToolActionWithSetup` (added in 3.1.3) replaced by `PipAuditAction`, which folds
  in the pip bootstrap plus the interpreter re-resolution and self-heal retry.

## [3.1.3] 2026-07-03 10:29:05

### Fixed
- `pip_audit` stage no longer fails with `No module named pip` when the audited
  interpreter is a uv-created `.venv` (uv venvs ship no pip). The stage now bootstraps a
  current pip into the pinned interpreter (`PIPAPI_PYTHON_LOCATION`) via
  `uv pip install --python <target> --upgrade pip` before auditing, using uv (a bmk
  prerequisite) so it installs the latest pip directly instead of ensurepip's bundled
  pip 25.2 (which is itself flagged). This also inoculates CI's tool venv against the
  same pip CVE.

### Added
- `tools.ensure_audit_pip_argv` (the pip-bootstrap argv builder) and
  `actions.ToolActionWithSetup` (runs a best-effort setup argv, then the main tool argv,
  into one capture-on-failure sink; the main tool's exit code decides the stage).

### Changed
- CI: bump `actions/cache` to v6.
- `[tool.pip-audit].ignore-vulns` emptied: both audit targets (project `.venv` and bmk's
  tool venv) are clean, and the new pip auto-upgrade removes the former pip-CVE ignores'
  reason to exist.

## [3.1.2] 2026-07-03 01:31:51

### Added
- Ship the `devops-bmk` Claude Code skill as a single-plugin marketplace: added
  `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and
  `skills/devops-bmk/SKILL.md` so bmk can be installed as a plugin from any project.
- `ai-transparency.md` and `ai-stance.md` documenting how AI tooling is used in this
  project, linked from the README.

### Changed
- `.gitignore` no longer ignores `.claude/` or `prompts.md`.

## [3.1.1] 2026-07-02 17:27:40

### Changed
- The `ship` command now parses `gh` workflow-run JSON with `orjson` instead of the stdlib
  `json`, matching the modern-library convention used across the rest of the codebase. Added
  tests covering the run-lookup helper (`_find_run_id`), which previously had none.

## [3.1.0] 2026-07-02 17:15:59

### Added
- `bmk ensure` (and `make ensure`): installs the external tools bmk needs on the host, best-effort
  and per-OS. It reuses the existing prerequisite detector and, for each missing tool, runs a
  platform-appropriate installer: the linters (shellcheck/shfmt/bashate) via pip, git via the
  system package manager (apt-get/dnf/pacman/zypper on Linux, brew on macOS, winget on Windows),
  pwsh via brew/winget, and PSScriptAnalyzer via `Install-Module`. Tools with no installer on the
  current platform (pwsh on Linux, winget itself) are reported with a hint instead of failing.
  `--dry-run` previews the install commands; `--strict` exits non-zero if any tool is still missing.

## [3.0.1] 2026-07-02 16:08:51

### Fixed
- Coverage runner reads its settings from the correct config table. `CoverageConfig`
  loaded a flat `[tool.scripts]` table with underscore keys, but the project convention
  (shared by the rest of the pipeline via `_toml_config`) is the nested `[tool.scripts.test]`
  table with hyphenated keys (`pytest-verbosity`, `coverage-report-file`, `src-path`,
  `exclude-markers`). Every configured value silently fell back to its default (e.g. pytest
  verbosity stayed `-v` instead of a configured `-vv`). Now reads the correct table and keys;
  defaults are unchanged.

## [3.0.0] 2026-07-02 15:17:39

### Changed
- **Stage runner rewritten in Python (cross-OS).** The make pipelines (clean, deps, deps-update,
  test, cov, testintegration, bump, commit, build, push, release, run) are now executed by a single
  in-process Python stage runner instead of paired `.sh`/`.ps1` scripts. Batches run in stage order,
  stages within a batch run in parallel via a thread pool, and the pipeline is fail-fast. The same
  code path runs on Linux, macOS, and Windows, so behaviour no longer diverges between the bash and
  PowerShell variants.
- **Downstream pipeline overrides are now TOML overlays.** A project customises a pipeline through
  `[tool.bmk.pipelines.<prefix>]` in its `pyproject.toml` (or a `bmk_makescripts/stages.toml`),
  validated by Pydantic. This replaces the old per-script shell override mechanism.
- Output-format handling is now a typed `ToolOutputFormat` enum end to end; the JSON-by-default
  capture-on-failure behaviour is unchanged.

### Removed
- **All `.sh`/`.ps1` stage scripts and the shell-based override mechanism.** Projects that dropped
  custom `*.sh` stage overrides into `bmk_makescripts/` must migrate them to the TOML overlay form
  above. This is the breaking change behind the major version bump.

### Fixed
- The project's `src/` is placed on `PYTHONPATH` for pipeline children, so `lint-imports` and
  integration pytest can import the package when bmk runs from its own tool venv.
- pip-audit is pinned to the correct interpreter when the project has no `.venv` (the
  `uv tool install --with .` layout, including bmk auditing itself): `PIPAPI_PYTHON_LOCATION`
  now points at bmk's own interpreter, whose tool venv holds bmk plus the project's dependency
  tree. Previously the bare `pip-audit` call could resolve to an unrelated `pip-audit` earlier on
  PATH (e.g. an editor's venv) and report vulnerabilities for the wrong environment.

## [2.9.6] 2026-06-30 22:15:59

### Fixed
- pip-audit now audits the target project's `.venv`, not whatever venv happens to be active in the
  caller's shell. `execute_script` already set `VIRTUAL_ENV` to the project venv, but pip-audit resolves
  the pip it audits via `sys.executable`/PATH (it ignores `VIRTUAL_ENV`), so a developer with an editor
  venv active (e.g. PyCharm) got a vulnerability report for the wrong environment - and a blocking
  `make push` failure unrelated to the project. We now also set `PIPAPI_PYTHON_LOCATION` to the project
  venv's interpreter (the override pip-audit documents), Windows-aware, and clear it when there is no
  project venv. (+2 test assertions.)

## [2.9.5] 2026-06-14

### Added
- `bmk ship` command (alias `sh`, `make ship`/`make sh`): the full CI-gated release - runs `push`, waits for the push-triggered CI workflow to pass, runs `release`, then waits for the release workflow to pass; aborts if any CI run fails. Matches the run to the just-pushed HEAD commit and gates via the GitHub CLI (`gh`); falls back to push-only with a clear message if `gh` is unavailable. `--ci-workflow` / `--release-workflow` override the workflow names.

### Changed
- Added a `typed_click.py` facade wrapping rich-click's `option` / `version_option` / `argument` decorators behind explicit, fully-known signatures, keeping the CLI strict-clean under pyright 1.1.410 (`reportUnknownMemberType`) without disabling the rule (ignore isolated to the facade).
- Bumped internal dependency floors: `lib_cli_exit_tools>=2.3.2`, `lib_log_rich>=6.3.5`, `lib_layered_config>=5.5.2`, `btx_lib_mail>=1.3.2`.

## [2.9.4] 2026-06-01 16:54:25

### Removed
- **pip-audit suppression `GHSA-4gg8-gxpx-9rph` dropped**: the `uv` entry-point path-traversal advisory is now resolved at the source - the build environment's `uv` is upgraded to 0.11.15 (the fixed release), so the suppression is no longer needed and the vulnerability is fixed rather than ignored

## [2.9.3] 2026-06-01 16:33:48

### Changed
- **Replaced `httpx` with `httpx2`**: the dependency-checker makescript (`makescripts/_dependencies.py`) now imports `httpx2`, the Pydantic-maintained successor to httpx (drop-in API, `import httpx2`). `pyproject.toml` now requires `httpx2>=2.3.0` instead of `httpx>=0.28.1`
- **pip-audit CVE exclusion list refreshed**:
  - added `GHSA-4gg8-gxpx-9rph` - uv 0.11.7 malicious-wheel entry-point path traversal (fix 0.11.15); environment-only tool runner, not a project dependency
  - restored `CVE-2026-3219` and `CVE-2026-6357` - pip, environment-only build tool (env-volatile across shared installs)
  - removed `CVE-2026-44431` and `CVE-2026-44432` - urllib3 entries no longer flagged now that the pinned urllib3 (`>=2.7.0`) is the fixed version
  - retained `PYSEC-2022-42969` (py) and `CVE-2026-44405` (paramiko) - still flagged upstream with no fix released

## [2.9.2] 2026-05-16 23:40:54

### Changed
- **pip-audit CVE exclusion list refreshed**: removed 17 stale entries that pip-audit no longer flags (pip, setuptools, wheel, cryptography, pillow, pygments, authlib, lxml, python-multipart, uv, rpyc); list is now down to four current entries

### Fixed
- **`check_pwsh` hardened against broken pwsh installs**: the PSScriptAnalyzer adapter now verifies `pwsh` can actually launch (running `pwsh -NoProfile -NonInteractive -Command "exit 0"`) instead of trusting `shutil.which`; this avoids spurious failures on Linux hosts where snap-installed `pwsh` aborts with `snap-confine has elevated permissions` errors - affected hosts now skip PowerShell linting cleanly
- **PowerShell makescripts pytest suite skips correctly when `pwsh` is non-functional**: same launch probe applied to `tests/test_makescripts_ps1.py` so a broken local `pwsh` no longer turns the test suite red
- **pip-audit CVE exclusions added** for three newly flagged environment-level vulnerabilities:
  - `CVE-2026-44405` - paramiko 4.0.0 SHA-1 acceptance in `rsakey.py` (no upstream fix yet)
  - `CVE-2026-44431` - urllib3 cross-origin sensitive-header leak via low-level `ProxyManager` redirects (fix 2.7.0; project already pins urllib3>=2.7.0)
  - `CVE-2026-44432` - urllib3 Brotli/`drain_conn` over-decompression DoS (fix 2.7.0; project already pins urllib3>=2.7.0)

## [2.9.1] 2026-04-24

### Changed
- **CI/CD workflow updates**: refreshed GitHub Actions matrix, bumped `codecov/codecov-action` to v6, and updated `actions/download-artifact` to a newer version
- **pip-audit CI step**: demoted to a warning instead of failing the build to reduce noise from environment-level CVEs that do not affect bmk

### Fixed
- **pip-audit CVE exclusions**: added six new transitive/environment-level CVEs to `[tool.pip-audit].ignore-vulns`:
  - `GHSA-jj8c-mmj3-mmgv` - authlib 1.6.9 OAuth CSRF in cached state
  - `CVE-2026-39892` - cryptography 46.0.6 buffer overflow on non-contiguous buffers
  - `CVE-2026-41066` - lxml 6.0.2 XXE local file access in default config
  - `CVE-2026-40192` - pillow 12.0.0 FITS decompression bomb DoS
  - `CVE-2026-40347` - python-multipart 0.0.22 DoS on crafted multipart
  - `GHSA-pjjw-68hj-v9mw` - uv 0.9.11 wheel RECORD path traversal on uninstall

## [2.9.0] 2026-02-27

### Changed
- **Makefile switched from `uvx` to persistent `uv tool install`**: the deployed Makefile template now runs `uv tool install --reinstall bmk --with .` before every target, installing bmk and the current project's dependencies into a persistent venv at `~/.local/share/uv/tools/bmk/`; tools like pyright, pytest and pip-audit resolve the full dependency tree without `PYTHONPATH` hacks or a local `.venv` - works on network shares without symlink support
- **Makefile uses absolute path** (`$(HOME)/.local/bin/bmk`) to prevent active virtualenvs from shadowing the uv tool binary
- **Root dev Makefile** uses `--from ./` to install bmk from local source for development

### Removed
- **`PYTHONPATH` export hack** from Makefile - no longer needed with persistent tool venv
- **`uvx bmk@latest`** invocation pattern - replaced by `uv tool install` approach

### Fixed
- **ruff minimum version**: bumped `>=0.15.2` to `>=0.15.4`

## [2.8.2] 2026-02-25 14:57:07

### Added
- **Makefile exports project venv site-packages via `PYTHONPATH`**: ensures bmk's isolated `uvx` Python can find project dependencies (e.g., private git repo packages) by exporting the active venv's `site.getsitepackages()[0]`

### Fixed
- **pip-audit CVE exclusion**: added `CVE-2026-25990` (pillow 12.0.0) to `[tool.pip-audit].ignore-vulns` - environment-level package, not a project dependency

## [2.8.1] 2026-02-25 14:42:58

### Fixed
- **Codecov upload failed for repos using git credential URL rewriting**: `_get_repo_metadata_from_git()` returned `token@github.com` as the host when the git remote URL contained embedded authentication (`https://token@github.com/owner/repo.git`); now strips everything before `@` in the host component

## [2.8.0] 2026-02-25

### Changed
- **Private repo dependencies simplified**: Removed token injection (`GH_PRIVATE_REPOS__` convention); dependencies now use PEP 440 direct references (`pkg @ git+https://...`) with authentication handled by global git config URL rewriting
- **Dependency floors updated**: `bandit >=1.9.3 → >=1.9.4`, `lib_layered_config >=5.4.1 → >=5.5.0`

### Removed
- **`install_git_dependencies()`**: Removed from `_dependencies.py` along with `_find_dotenv_upward()` and `_get_git_source_names()` - no longer needed with git config URL rewriting
- **`UvSourceEntry` dataclass**: Removed from `_toml_config.py` - was only used by the removed git dependency installer

## [2.7.1] 2026-02-24

### Changed
- **Token convention renamed**: `.env` keys for private repo tokens changed from `<NAME>_GHTOKEN` to `GH_PRIVATE_REPOS__<UPPER_PACKAGE_NAME>` for consistency with dotenv section conventions

## [2.7.0] 2026-02-24

### Added
- **Private repository dependencies**: `install_git_dependencies()` auto-installs packages from `[tool.uv.sources]` git URLs before PyPI dependency checking; per-library GitHub tokens read from `.env` (`GH_PRIVATE_REPOS__<UPPER_PACKAGE_NAME>=ghp_xxx`); git-sourced packages excluded from PyPI version comparison
- **`UvSourceEntry` model**: new dataclass in `_toml_config.py` for parsing `[tool.uv.sources]` entries

### Changed
- **Documentation**: README, DEVELOPMENT, and CONTRIBUTING updated for v2.6.0 features (private repos, `make test-human`, JSON success summary, NFS venv resilience)
- **Stage table corrected**: removed stale `test_900_clean` entry, moved `psscriptanalyzer` to stage 040

## [2.6.0] 2026-02-24

### Added
- **`make test-human` / `make th`**: dedicated Makefile target for human-readable test output - avoids the `make test --human` issue where Make intercepts `--` flags
- **`make testintegration-human` / `make tih`**: same for integration tests
- **JSON mode success summary**: stagerunner emits `{"result":"pass","stages":N,"scripts":N}` on success so JSON consumers always receive at least one output line
- **LLM-friendly log messages**: test and push commands now log "this will take some minutes" to prevent LLM agents from assuming the process has hung

### Fixed
- **Broken `.venv` detection on NFS**: `execute_script()` now validates `.venv/pyvenv.cfg` exists before setting `VIRTUAL_ENV` - stale NFS mounts or corrupt venvs are ignored instead of causing tool failures

## [2.5.1] 2026-02-24

### Fixed
- **Dependency updater corrupted specs with upper bounds**: `_build_updated_spec` injected display annotations (e.g. `(max <1.3, absolute: 1.3.0)`) into dependency strings and overwrote upper-bound constraints (`<1.3`) with the latest version - specs like `>=1.1.0,<1.3; python_version<'3.10'` were mangled into invalid version strings
- **Upper-bound constraints now preserved during dependency updates**: only lower-bound operators (`>=`, `==`, `~=`, `>`) are updated; `<`, `<=`, and `!=` constraints are left untouched

## [2.5.0] 2026-02-24

### Added
- **JSON mode output suppression**: stagerunner captures all tool output in JSON mode and only displays it when a stage fails - a fully passing run produces zero tool output, designed for LLM-driven workflows to minimize context window consumption
- **Makefile auto-update in JSON mode**: `check_makefile_update()` auto-accepts Makefile version updates without prompting when `BMK_OUTPUT_FORMAT` is not `text`
- **JSON mode auto-accept for dependency updates**: `_dependencies.py` runs silently in JSON mode - no report, no per-dependency output, no summary
- **Pytest concise mode**: in JSON mode, pytest runs with `--tb=short -q --no-header` and coverage report display is suppressed

## [2.4.0] 2026-02-24 11:20:14

### Added
- **JSON-by-default output**: `bmk test` and `bmk testintegration` now emit JSON output from tools (ruff, pyright, bandit, pip-audit, shellcheck, PSScriptAnalyzer) for machine-readable consumption
- **`--human` flag**: use `bmk test --human` or `bmk testintegration --human` to restore traditional text output
- **`BMK_OUTPUT_FORMAT` environment variable**: set to `json` (default) or `text` to control tool output format; `--human` flag takes precedence
- **Virtual environment isolation for uvx**: `execute_script()` now sets `VIRTUAL_ENV` to the target project's `.venv/` (if present) or unsets it, ensuring pyright, pip-audit, and other tools resolve packages from the correct environment

### Changed
- **Stage scripts read `BMK_OUTPUT_FORMAT`**: all `.sh` and `.ps1` stage scripts now read the environment variable and pass tool-specific JSON flags accordingly
- **Python helpers accept `--output-format`**: `_shellcheck.py`, `_psscriptanalyzer.py`, and `_coverage.py` accept a new `--output-format` CLI argument
- **Dependency floors updated**: `hatchling >=1.28.0 → >=1.29.0`, `hypothesis >=6.151.6 → >=6.151.9`, `lib_layered_config >=5.4.0 → >=5.4.1`, `ruff >=0.15.1 → >=0.15.2`, `textual >=7.5.0 → >=8.0.0`

### Fixed
- **CI/CD runner configuration**: fixed runner setup in GitHub Actions workflow
- **Bandit configuration**: bandit now reads settings from `pyproject.toml`
- **Clean list**: added `.venv` to clean targets; removed `.idea` directory from repository

## [2.3.3] 2026-02-13 20:23:26

### Removed
- **test_900_clean stage**: removed `test_900_clean.sh` and `test_900_clean.ps1` from the test pipeline to preserve coverage data for post-test analysis and reporting

### Changed
- **Dependency floors updated**: `lib_cli_exit_tools >=2.2.4 → >=2.3.0`, `lib_log_rich >=6.3.1 → >=6.3.3`

## [2.3.2] 2026-02-13 18:14:14

### Fixed
- **Makefile alias targets firing as prerequisites during argument forwarding**: `make push coverage test` no longer executes the real `codecov` target - alias targets (`coverage cov:`, `t:`, `bld:`, `cln cl:`, `c:`, `psh p:`, `rel r:`, `deps d:`, `testi ti:`) now use standalone recipes instead of prerequisite chains, allowing the trailing-argument no-op override block to properly suppress them; GNU Make accumulates prerequisites across rules (never overridden), but recipes follow "last rule wins"

## [2.3.1] 2026-02-13 17:59:34

### Added
- **Comprehensive makescript test coverage**: added 146 new tests across four makescript modules, raising overall project coverage from 83% to 95%
  - `test_makescripts_dependencies.py` (79 tests): version parsing, PyPI queries, dependency extraction (optional deps, build system, poetry, pdm, uv, dependency-groups), reporting, pyproject.toml updating, pip sync
  - `test_makescripts_coverage.py` (93 tests): CoverageConfig loading, file pruning, report artifacts, env building, test execution, dotenv search, codecov token discovery, git resolution, upload workflow
  - `test_makescripts_run.py` (+9 tests): `run_cli()` invocation - command construction, exit code propagation, empty project name error, default `--help`, local dependency `--with` flags
  - `test_makescripts_psscriptanalyzer.py` and `test_makescripts_shellcheck.py`: full behavioural coverage for config reading, tool detection, file discovery, and orchestration

### Changed
- **Coverage threshold raised from 70% to 80%** in `[tool.coverage.report].fail_under` to lock in test coverage gains
- **Prerequisite checker refactored**: extracted `_append_psscriptanalyzer_check()` helper to DRY the PSScriptAnalyzer module check shared between `_posix_tools()` and `_windows_tools()`
- **CI metadata extraction uses rtoml**: replaced `tomllib`/`tomli` with `rtoml` in `.github/actions/extract-metadata` and pip-audit step; removed the `Install tomli (Python < 3.11)` step
- **CI installs bash 4+ on macOS**: new step installs modern bash via Homebrew for stagerunner array feature compatibility
- **CI installs `[dev]` extras**: `uv pip install -e .` changed to `uv pip install -e .[dev]`
- **CI uses `pytest` directly**: replaced `python -m pytest` with `pytest` in test step
- **CI sets `UV_BREAK_SYSTEM_PACKAGES=1`**: allows uv to install into system Python environments without error

### Fixed
- **pip-audit CVE exclusion**: added `CVE-2026-26007` (cryptography 46.0.3) to `[tool.pip-audit].ignore-vulns`
- **pyright strict error in test file**: added `reportUnknownVariableType=false` pragma to `test_makescripts_dependencies.py` for dynamically-typed `_toml_config` imports

## [2.3.0] 2026-02-13 14:01:44

### Added
- **PSScriptAnalyzer lint stage** (`test_040_psscriptanalyzer`): new makescript that lints all `.ps1` files via PSScriptAnalyzer, with excluded rules driven by `[tool.psscriptanalyzer]` in `pyproject.toml`; auto-installs the PowerShell module if absent
- **Shell lint stage** (`test_060_shellcheck`): new makescript that runs shellcheck, shfmt, and bashate against all `.sh` files, with bashate settings driven by `[tool.bashate]` in `pyproject.toml`; Windows `.ps1` variant skips gracefully
- **Prerequisite checking on `bmk install`**: after Makefile deployment, prints a diagnostic summary showing which external tools (git, pwsh, shellcheck, shfmt, bashate, PSScriptAnalyzer) are found or missing, with platform-appropriate install hints (apt on Linux, brew on macOS, winget on Windows); report is informational only and always displays even when Makefile deployment is skipped
- **New runtime dependencies**: `shellcheck-py`, `shfmt-py`, `bashate`, `hatchling` (build system, added to runtime deps by design)
- **TOML config models**: `PSScriptAnalyzerConfig` and `BashateConfig` dataclasses in `_toml_config.py` for reading `[tool.psscriptanalyzer]` and `[tool.bashate]` sections

### Changed
- **Test clean stage renumbered**: `test_050_clean` → `test_900_clean` to make room for new lint stages (PSScriptAnalyzer at 040, shellcheck at 060)
- **PowerShell scripts require pwsh 7+**: added `#Requires -Version 7.0` to stagerunner and key makescripts; replaced PS 5.1 compat workarounds (`[char]0x1B`, `if/else` ternaries) with native pwsh 7 syntax (`` `e ``, `??`, `?:`)
- **Script executor uses `pwsh`**: `_shared.py` now invokes `.ps1` scripts via `pwsh -NoProfile -NonInteractive` instead of `powershell -ExecutionPolicy Bypass`
- **PowerShell naming conventions**: renamed `Explain-ExitCode` to `Write-ExitCodeError` (approved verb), `Get-UniqueStages` to `Get-UniqueStage` (singular); replaced `Write-Host` with `Write-Output` where appropriate
- **Commit script quoting fix**: `commit_010_commit.sh` now properly quotes `$sensitive_files` in `printf` to prevent word splitting
- **Clean warning built dynamically**: `_clean.py` replaces static `_MISSING_SECTION_WARNING` string with `_build_missing_section_warning()` generated from `_FALLBACK_PATTERNS`

### Removed
- **`hello` command and `behaviors.py` domain module**: removed `cli_hello`, `build_greeting()`, and `CANONICAL_GREETING` - template scaffolding no longer needed

## [2.2.2] 2026-02-13 11:02:42

### Changed
- **`make clean` warns on missing `[tool.clean]` config**: prints a warning with example `[tool.clean].patterns` section to stderr when `pyproject.toml` exists but has no clean patterns configured
- **Makefile update no longer aborts the command**: accepting a Makefile version update now continues running the original subcommand instead of exiting

## [2.2.1] 2026-02-13 10:35:26

### Fixed
- **`make dev` now installs `[dev]` extras**: changed `uv pip install -e "."` to `uv pip install -e ".[dev]"` so customers with a `[dev]` optional-dependencies group get those extras installed

## [2.2.0] 2026-02-11 22:09:03

### Changed
- **Extracted inline Python to standalone scripts**: moved inline `python -c` code from stagerunners and `test_040_pip_audit` into `_derive_package_name.py` and `_extract_pip_audit_ignores.py`, eliminating the temp-file write-execute-delete pattern that triggered Windows Defender false positives
- **Makefile local-dev invocation**: replaced `uvx --reinstall` (no longer supported) with `uv cache prune --quiet && uvx --refresh`

### Fixed
- **Windows Defender false positive**: the stagerunner's temp-file pattern (write Python to `.py`, execute, delete) was flagged as a malicious "script dropper"; standalone `.py` scripts eliminate the trigger entirely

## [2.1.0] 2026-02-11 21:13:49

### Added
- **Shared Python resolver for makescripts**: new `_resolve_python.ps1` and `_resolve_python.sh` helpers that all makescripts source to find the correct Python interpreter
- **`BMK_PYTHON_CMD` propagation**: the Python CLI passes `sys.executable` via `BMK_PYTHON_CMD` environment variable; all shell and PowerShell makescripts now honour it, ensuring the uvx-managed interpreter is used instead of whatever `python`/`python3` is in PATH

### Fixed
- **Windows Python detection across all PS1 makescripts**: replaced hardcoded `python3` with resolved `$BMK_PYTHON_CMD` in all 15 PowerShell stage scripts; the resolver skips the Windows Store alias stub (exit code 9009) by filtering out `Microsoft\WindowsApps` paths via `Get-Command -All`
- **Bash makescripts use resolved Python**: replaced hardcoded `python3` with `"$BMK_PYTHON_CMD"` in all 15 bash stage scripts for consistency with the PowerShell side
- **PowerShell ANSI color codes**: replaced `` `e `` escape (PowerShell 7+ only) with `[char]0x1B` for Windows PowerShell 5.1 compatibility
- **PowerShell `python -c` multiline string failure**: `test_040_pip_audit.ps1` now writes inline Python code to a temp file (same approach as stagerunner) instead of passing via `-c`
- **Stagerunner `Invoke-SingleScript` output leaking into return value**: captured stdout via `2>&1` and replayed via `Write-Host` to prevent PowerShell from including script output in the function's return value
- **Stagerunner parallel job error handling**: wrapped `Start-Job` script blocks in `try/catch` to prevent `$ErrorActionPreference = "Stop"` in child scripts from turning stderr into terminating errors in PS 5.1

## [2.0.16] 2026-02-11 19:36:31

### Fixed
- **Stagerunner Python command detection**: both `_btx_stagerunner.ps1` and `_btx_stagerunner.sh` now detect the available Python command (`python` / `python3`) instead of hardcoding `python3`, fixing failures on Windows where only `python` exists

## [2.0.15] 2026-02-11 19:03:25

### Fixed
- **Coverage threshold reverted to 70%**: Windows CI has lower coverage due to platform-specific code paths; `fail_under` set back to 70 for cross-platform compatibility

## [2.0.14] 2026-02-11 18:57:25

### Changed
- **Shared script infrastructure moved to `_shared.py`**: extracted `execute_script`, `get_script_name`, `normalize_returncode`, and `resolve_script_path` from `test_cmd.py` into `_shared.py`; all 12 command modules now import from the shared module
- **Renamed `test_cmd.py` to `testsuite_cmd.py`**: avoids confusion with test files; file now contains only `cli_test` and `cli_t` click commands
- **Eliminated `execute_custom_script` duplication**: `custom_cmd.py` now reuses `execute_script` from `_shared.py` instead of maintaining a near-identical copy
- **Coverage threshold raised**: `fail_under` increased from 70% to 73% to better guard against regressions

### Fixed
- **`install_cmd.py` missing structured logging context**: added `lib_log_rich.runtime.bind(job_id="cli-install")` for consistency with all other CLI commands
- **`build_cmd.py` phantom alias in docstring**: removed reference to nonexistent `cli_b` short alias (that alias belongs to the bump command)
- **`install_cmd.py` leaking private function in `__all__`**: removed `_extract_version` from public exports

## [2.0.13] 2026-02-11 13:15:15

### Fixed
- **Warning scanner false positives**: exclude summary lines containing `N warnings` (e.g. pyright's `0 errors, 0 warnings, 0 informations`) from stagerunner warning output in both bash and PowerShell

## [2.0.12] 2026-02-11 12:54:51

### Fixed
- **Makefile argument forwarding**: trailing words matching real target names (e.g. `make push codecov fix`) no longer execute those targets as separate commands; replaced `$(eval)` no-ops (overridden by later target definitions) with a regular rule block at end of Makefile using GNU Make's "last rule wins" behavior

## [2.0.11] 2026-02-11 12:47:59

### Changed
- **Codecov token warning color**: changed from bright red (`\033[91m`) to yellow (`\033[33m`) to match stagerunner warning styling

## [2.0.10] 2026-02-11 12:41:22

### Fixed
- **Missing codecov token not surfaced by warning scanner**: `_coverage.py` message changed from `[codecov] CODECOV_TOKEN not found` to `[codecov] warning: CODECOV_TOKEN not found` so the stagerunner warning scanner picks it up

## [2.0.9] 2026-02-11 12:28:32

### Added
- **Show warnings from passing parallel stagerunner jobs**: output from successful parallel scripts is scanned for lines containing "warning" (case-insensitive) and displayed in yellow after the pass/fail summary
- New `[bmk].show_warnings` config option (default `true`) to control warning display; set `BMK_SHOW_WARNINGS=0` or `show_warnings = false` in config to suppress
- `print_warnings_from_passed()` in bash stagerunner and `Show-WarningsFromPassed` in PowerShell stagerunner

### Fixed
- **PowerShell stagerunner exit code display bug**: failed-job output header showed raw output instead of exit code (`$failedOutput[$scriptName]` → `$exitCodes[$scriptName]`)

## [2.0.8] 2026-02-11 12:23:30

### Changed
- **Root Makefile switched to local dev source**: `BMK` variable now uses `uvx --refresh --from /path bmk` instead of `uvx bmk@latest`, and sentinel line removed to prevent `bmk install` from overwriting local changes

## [2.0.7] 2026-02-11 01:43:23

## [2.0.6] 2026-02-11 01:28:04

### Added
- **Auto-sync bundled Makefile version from `pyproject.toml`**: `_sync_initconf.py` now also patches the `# BMK MAKEFILE X.Y.Z` sentinel on line 1 of `src/<pkg>/makefile/Makefile`, keeping it in sync alongside `__init__conf__.py` after version bumps

## [2.0.5] 2026-02-11 00:39:28

### Changed
- **Stage delegator scripts show delegation flow**: replaced generic announcements with `delegator → target pipeline` messages (e.g. `push_040_commit → commit pipeline`) so pipeline nesting is visible in output

## [2.0.4] 2026-02-10 23:12:40

### Fixed
- **Duplicate log messages in stage delegator scripts**: removed redundant printf/Write-Host from 8 delegator scripts (.sh + .ps1 pairs) whose inner pipelines already print their own announcements (e.g. `test_050_clean.sh` → `clean_010_clean.sh`, `push_020_build.sh` → `bld_020_build.sh`, `push_040_commit.sh` → `commit_010_commit.sh`)

## [2.0.3] 2026-02-10 22:56:06

### Added
- **Auto-sync `__init__conf__.py` version from `pyproject.toml`**: new `_sync_initconf.py` makescript patches the `version` line after every bump and before every commit, preventing version mismatch test failures
- Stage scripts `bump_{patch,minor,major}_020_sync_initconf.{sh,ps1}` run sync immediately after version bumps
- Stage script `commit_005_sync_initconf.{sh,ps1}` runs sync as a safety net before every commit

### Fixed
- **Makefile recipe override warning**: `make push test parameters` no longer warns about overriding the `test` target recipe - extra arguments that collide with existing target names are now skipped in the no-op eval

## [2.0.2] 2026-02-10 22:35:34

### Fixed
- **Stagerunner parallel output**: announce tasks upfront (`▶ running N tasks in parallel: ...`) and print all results together after completion instead of trickling one-by-one in arbitrary order
- **Makescript Python scripts reject unknown arguments**: changed `parse_args()` to `parse_known_args()` in all 5 makescript entry points so forwarded pipeline arguments (e.g. commit messages from `bmk push`) no longer cause errors
- **pip-audit false positives**: added `CVE-2025-8869` (pip) and `PYSEC-2022-42969` (py) to ignore-vulns

## [2.0.1] - 2026-02-10

### Removed
- Unnecessary transitive CVE pins: `wheel`, `python-multipart`, `pynacl`, `virtualenv` (not in bmk's dependency tree)

## [2.0.0] - 2026-02-10

### Added
- **initial official release**

## [1.3.0] - 2026-02-01

### Added
- **File permission options for `config-deploy`**: `--permissions/--no-permissions`, `--dir-mode`, `--file-mode`
- **Configurable permission defaults** in `[lib_layered_config.default_permissions]` (app/host: 755/644, user: 700/600)
- **Octal string support** in config files (`"0o755"`, `"755"`, or decimal `493`)

### Changed
- `deploy_configuration()` accepts `set_permissions`, `dir_mode`, `file_mode` parameters
- CONFIG.md: comprehensive CLI options reference, `sudo -u` deployment examples

## [1.2.1] - 2026-02-01

### Changed
- **Profile validation** now delegates to `lib_layered_config.validate_profile_name()` with comprehensive security checks:
  - Maximum length enforcement (64 characters)
  - Empty string rejection
  - Windows reserved name rejection (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
  - Leading character validation (must start with alphanumeric)
  - Path traversal prevention (/, \, ..)
- `validate_profile()` now accepts optional `max_length` parameter for customization

### Added
- `40-layered-config.toml` in `defaultconfig.d/` documenting lib_layered_config integration settings
- Profile validation tests for length limits, empty strings, Windows reserved names, and leading character rules
- Profile name requirements documentation in CONFIG.md and README.md

### Removed
- Custom `_PROFILE_PATTERN` regex - replaced by lib_layered_config's built-in validation

## [1.2.0] - 2026-01-30

### Added
- **Attachment security settings** for email configuration (`[email.attachments]` section in `50-mail.toml`)
  - `allowed_extensions` / `blocked_extensions` - whitelist/blacklist file extensions
  - `allowed_directories` / `blocked_directories` - whitelist/blacklist attachment source directories
  - `max_size_bytes` - maximum attachment file size (default 25 MiB, 0 to disable)
  - `allow_symlinks` - whether symbolic links are permitted (default false)
  - `raise_on_security_violation` - raise or skip on violations (default true)
- New `EmailConfig` fields for attachment security with Pydantic validators
- `load_email_config_from_dict()` now flattens nested `[email.attachments]` section

### Changed
- Bumped `btx_lib_mail` dependency from `>=1.2.1` to `>=1.3.0` for attachment security features

## [1.1.2] - 2026-01-28

### Fixed
- Coverage SQLite "database is locked" errors on Python 3.14 free-threaded builds and network mounts (SMB/NFS)
- Removed bogus `COVERAGE_NO_SQL=1` environment variable from `scripts/test.py` (not a real coverage.py setting)
- CI workflow now sets `COVERAGE_FILE` to `runner.temp` so coverage always writes to local disk
- **Import-linter was a silent no-op** in `make test` / `make push` - `python -m importlinter.cli lint` silently exits 0 without checking; replaced with `lint-imports` (the working console entry point)
- CI/local parameter mismatches: ruff now targets `.` (not hardcoded `src tests notebooks`), pytest uses `python -m pytest` with `--cov=src/$PACKAGE_MODULE`, `--cov-fail-under=90`, and `-vv` matching local runs
- `scripts/test.py` bandit source path now reads `src-path` from `[tool.scripts.test]` instead of hardcoding `Path("src")`
- `scripts/test.py` module-level `_default_env` now rebuilt with configured `src_path` before running checks
- `run_slow_tests()` now reads pytest verbosity from `[tool.scripts.test].pytest-verbosity` instead of hardcoding `"-vv"`

### Changed
- **pyproject.toml as single source of truth**: CI workflow extracts all tool configuration (src-path, pytest-verbosity, coverage-report-file, fail_under, bandit skips) from `pyproject.toml` via metadata step - workflow is portable across projects without editing
- `scripts/test.py` removed module-level `PACKAGE_SRC` constant; bandit source path computed from `config.src_path` inside the functions that need it
- `make push` now accepts an unquoted message as trailing words (e.g. `make push fix typo in readme`); commit message format is `<version> - <message>`, defaulting to `<version> - chores` when no message is given
- Removed interactive commit-message prompt from `push.py` - message is either provided via CLI args / `COMMIT_MESSAGE` env var, or defaults to `"chores"`

### Added
- `pytest_configure` hook in `tests/conftest.py` that redirects coverage data to `tempfile.gettempdir()` and purges stale SQLite journal files before each run

## [1.1.1] - 2026-01-28

### Fixed
- CLAUDE.md: replaced stale package name `bitranox_template_cli_app_config_log_mail` with `bmk` throughout
- Brittle SMTP mock assertions in `test_cli.py` now use structured `call_args` attributes instead of `str()` coercion
- Stale docstring in `__init__conf__.py` claiming "adapters/platform layer" - corrected to "Package-level metadata module"
- Weak OR assertion in `test_cli.py` for SMTP host display - replaced with two independent assertions
- Removed stale `# type: ignore[reportUnknownVariableType]` from `sender.py` (`btx_lib_mail.ConfMail` now has proper type annotations)
- Late function-body imports in `adapters/cli/commands/config.py` moved to module-level for consistency

### Removed
- Dead code: unused `_format_value()` and `_format_source()` wrappers in `adapters/config/display.py`

### Added
- `__all__` to `__init__conf__.py` listing all public symbols
- `tests/test_enums.py` with parametrized tests for `OutputFormat` and `DeployTarget`
- Expanded `tests/test_behaviors.py` with return type, constant value, and constant-usage checks
- Python 3.14 classifier in `pyproject.toml`
- Codecov upload step in CI workflow (gated to `ubuntu-latest` + `3.13`)
- Edge-case tests for `parse_override`: bare `=value`, bare `=`, and CLI `--set ""` empty string
- Duplication-tracking comments for CI metadata extraction scripts

### Changed
- `tests/test_display.py` rewritten to test `_format_raw_value` and `_format_source_line` directly (replacing dead wrapper tests)

## [1.1.0] - 2026-01-27

### Changed
- Replaced `MockConfig` in-memory adapter with real `Config` objects in all tests (`config_factory` / `inject_config` fixtures)
- Replaced `MagicMock` Config objects in CLI email tests with real `Config` instances
- Unified test names to BDD-style `test_when_<condition>_<behavior>` pattern in `test_cli.py`
- Email integration tests now load configuration via `lib_layered_config` instead of dedicated `TEST_SMTP_SERVER` / `TEST_EMAIL_ADDRESS` environment variables

### Added
- Cache effectiveness tests for `get_config()` and `get_default_config_path()` LRU caches (`tests/test_cache_effectiveness.py`)
- Callable Protocol definitions in `application/ports.py` for all adapter functions, with static conformance assertions and `tests/test_ports.py`
- `ExitCode` IntEnum (`adapters/cli/exit_codes.py`) with POSIX-conventional exit codes for all CLI error paths
- `logdemo` and `config-generate-examples` CLI commands
- `--set SECTION.KEY=VALUE` repeatable CLI option for runtime configuration overrides (`adapters.config.overrides` module)
- Unit tests for config overrides and display module (sensitive key matching, redaction, nested rendering)

### Removed
- Dead code: `raise_intentional_failure()`, `noop_main()`, `cli_main()`, duplicate `cli_session` orchestration, catch-log-reraise in `send_email()`
- Replaced dead `ConfigPort`/`EmailPort` protocol classes with callable Protocol definitions

### Fixed
- POSIX-conventional exit codes across all CLI error paths (replacing hardcoded `SystemExit(1)`)
- Sensitive value redaction: word-boundary matching to avoid false positives, nested dict/list redaction, TOML sub-section rendering
- Email validation: reject bogus addresses (`@`, `user@`, `@domain`); IPv6 SMTP host support; credential construction
- Profile name validation against path traversal
- Security: list-based subprocess calls in scripts, sensitive env-var redaction in test output, stale CVE exclusion cleanup
- Documentation: wrong project name references, truncated CLI command names, stale import paths, wrong layer descriptions
- CI: `actions/download-artifact` version mismatch, stale `codecov.yml` ignore patterns
- Unified `__main__.py` and `adapters/cli/main.py` error handling via delegation

### Changed
- Precompile all regex patterns in `scripts/` as module-level constants for consistent compilation
- **LIBRARIES**: Replace custom redaction/validation with `lib_layered_config` redaction API and `btx_lib_mail` validators; bump both libraries
- **LIBRARIES**: Replace stdlib `json` with `orjson`; replace `urllib` with `httpx` in scripts
- **ARCHITECTURE**: Purified domain layer - `emit_greeting()` renamed to `build_greeting()` (returns `str`, no I/O); decoupled `display.py` from Click
- **DATA ARCHITECTURE**: Consolidated `EmailConfig` into single Pydantic `BaseModel` (eliminated dataclass conversion chain)

## [1.0.0] - 2026-01-15

### Added
- Slow integration test infrastructure (`make test-slow`, `@pytest.mark.slow` marker)
- `pydantic>=2.0.0` dependency for boundary validation
- `CLIContext` dataclass replacing untyped `ctx.obj` dict
- Pydantic models: `EmailSectionModel`, `LoggingConfigModel`
- `application/ports.py` with Protocol definitions; `composition/__init__.py` wiring layer

### Changed
- **BREAKING**: Full Clean Architecture refactoring into explicit layer directories (`domain/`, `application/`, `adapters/`, `composition/`)
- CLI restructured from monolithic `cli.py` into focused `cli/` package with single-responsibility modules
- Type hints modernized to Python 3.10+ style
- Removed backward compatibility re-exports; tests import from canonical module paths
- `import-linter` contracts enforce layer dependency direction
- `make test` excludes slow tests by default

## [0.2.5] - 2026-01-01

### Changed
- Bumped `lib_log_rich` to >=6.1.0 and `lib_layered_config` to >=5.2.0

## [0.2.4] - 2025-12-27

### Fixed
- Intermittent test failures on Windows when parsing JSON config output (switched to `result.stdout`)

## [0.2.3] - 2025-12-15

### Changed
- Lowered minimum Python version from 3.13 to 3.10; expanded CI matrix accordingly

## [0.2.2] - 2025-12-15

### Added
- Global `--profile` option for profile-specific configuration across all commands

### Changed
- **BREAKING**: Configuration loaded once in root CLI command and stored in Click context for subcommands
- Subcommand `--profile` options act as overrides that reload config when specified

## [0.2.0] - 2025-12-07

### Added
- `--profile` option for `config` and `config-deploy` commands
- `OutputFormat` and `DeployTarget` enums for type-safe CLI options
- LRU caching for `get_config()` (maxsize=4) and `get_default_config_path()`

### Fixed
- UTF-8 encoding issues in subprocess calls across different locales

## [0.1.0] - 2025-12-07

### Added
- Email sending via `btx-lib-mail` integration: `send-email` and `send-notification` CLI commands
- Email configuration support with `EmailConfig` dataclass and validation
- Real SMTP integration tests using `.env` configuration

## [0.0.1] - 2025-11-11
- Bootstrap
