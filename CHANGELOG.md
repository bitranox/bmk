# Changelog

All notable changes to this project will be documented in this file following
the [Keep a Changelog](https://keepachangelog.com/) format.


## [Unreleased]

## [3.31.0] 2026-10-28 22:08:07

### Fixed

- - With pytest 9.2.0 and pytest-xdist 3.8.0 every `xdist_group` was silently ignored: xdist groups
  a test by renaming its node id, pytest 9.2.0 no longer reads that rename, so tests sharing a
  database or a port ran in parallel while every run stayed green (pytest-xdist issue #1386, fixed
  on xdist's master but in no release). bmk now asks the project's installed pytest and xdist
  whether the rename takes effect; when it does not, `make test` runs the suite in one process and
  prints one stderr line naming the cause (in JSON mode only when the stage fails), and test-all's
  cells run serially; a `-n` in the project's own addopts is overridden with `-n 0`. A pytest-xdist
  release with the fix, or `pytest<9.2` in the dev extra, brings the parallel run back by itself.

### Documentation

- `docs/pyproject-reference.md` and the devops-bmk skill said a conftest can put
  `xdist_group` on every test that uses a fixture, but a `pytest_collection_modifyitems` hook
  adds the mark too late unless it is `@pytest.hookimpl(tryfirst=True)`, and the tests then
  spread over every worker while the run stays green. Both now show the `tryfirst` hook and how
  to check a group: each grouped node id ends in `@<name>` and they all run on one worker.

## [3.30.0] 2026-10-27 09:24:21

### Changed

- `[tool.scripts.test] workers = 1` (and `BMK_TEST_WORKERS=1`) now runs the suite in one process
  even when the project's own `addopts` passes `-n`: bmk adds `-n 0`. Before, the project's `-n`
  still spread the tests over xdist workers that `coverage run` never measures, so the run failed
  its `fail_under` floor although every test passed. A venv with pytest-xdist but no pytest-cov,
  which bmk already ran serially, gets the same `-n 0`, and its hint ("tests run in one process")
  is now true. bmk asks the project's pytest what it loads on every run, serial ones included.
- `release` (`rel`, `r`) no longer rewrites an outdated Makefile before it runs. It refuses a
  working tree with uncommitted changes, so after a new bmk version every release refused,
  naming the Makefile change the same command had just made; the next other target updates it.

### Fixed

- A coverage floor failure in JSON mode (make test's default) printed only an exit line: the
  `coverage report` table naming the missing lines was discarded. It is now printed whenever the
  floor fails, in every mode, and a passing report stays silent in JSON mode.
- A floor failure was reported as `[coverage] Tests failed (exit 2)` although every test passed.
  It now reads `[coverage] Coverage is below fail_under = <N> (exit 2)`; `Tests failed` is printed
  only when pytest fails.
- `release` on a detached HEAD pushed a ref named `HEAD` and failed only after creating the tag.
  It now refuses first, naming the clean-worktree route.

## [3.29.0] 2026-10-26 23:11:44

### Added

- `make test` runs pytest across processes when the project's venv has pytest-xdist and
  pytest-cov: `pytest -n <workers> --dist loadgroup --cov=<source>`. bmk never installs xdist
  itself, so a project goes parallel only once it adds `pytest-xdist` to its dev extra; until
  then the suite runs in one process and the stage prints one line naming the package to add.
  Coverage, the `fail_under` floor and `coverage.xml` are unchanged (bmk's own suite measures the
  same lines and branches either way, in 20s instead of 85s). Tests sharing a database or a port
  keep running one at a time when they carry the same `@pytest.mark.xdist_group("<name>")`.
  bmk asks pytest itself whether the plugins load, so a run with plugin autoload off or
  `-p no:xdist` in `addopts` stays serial without a hint, and a `-n` or `--dist` the project
  already passes in `addopts` is left alone. The floor is still checked once, by the
  `coverage report` step, never by pytest-cov.
- `[tool.scripts.test] workers` (`"auto"` by default, or a count; `1` is serial) and the
  `BMK_TEST_WORKERS` override for one run. A bad value is refused with one line and exit 2.
- `make test-all` passes the same setting to each version cell, split between the cells running
  at once so the matrix never starts more pytest workers than there are CPUs.

### Changed

- The pyright runs for several `[tool.ci].os` platforms run at the same time instead of one after
  another. Each run's output is still printed whole and in the order the runs are listed. When
  `PYRIGHT_PYTHON_FORCE_VERSION` or `PYRIGHT_PYTHON_USE_BUNDLED_PYRIGHT` is set, pyright may
  install itself from npm into one unlocked cache, so the first run goes alone and the rest
  start together after it.
- shellcheck (with shfmt and bashate) joins the other read-only checks in the parallel batch of
  `make test` instead of running alone after it.
- bmk's own dependencies include `pytest-xdist`, so its suite runs in parallel.
- bmk requires `lib_log_rich>=8.0.1` and `setuptools>=84.2.0`; the setuptools release is now older
  than the cooldown, so its dated `[tool.uv]` pin is gone.

## [3.28.1] 2026-10-26 20:58:34

### Fixed

- `logdemo` refuses a `LOG_*` variable lib_log_rich refuses (`LOG_CONSOLE_LEVEL=bogus`) with exit 78
  and lib_log_rich's own line, as `config` does. The demo reads the variables itself, so its
  `ValueError` reached `main()` and exited with the OS errno (22 on POSIX, 87 on Windows).
- `make help` names each target again in a project that has `.bmk-cooldown.mk`. The Makefile
  `-include`s that file, so its help grep read two files and prefixed every match with
  `Makefile:`, which the listing then showed as every target's name. The help grep now prints
  no file names (`grep -hE`), in the template and in bmk's own dev Makefile.

## [3.28.0] 2026-10-26 17:59:59

### Added

- `make test-all` tests free-threaded builds the way CI does. Each minor in
  `[tool.ci] free-threaded = ["3.15"]` gets a second cell on its free-threaded build (`3.15t`,
  venv `.venv-3.15t`), right after the regular one. bmk used to ignore the key, so a project's
  `test-all` ran 3.10 to 3.15 while its CI also ran 3.15t. An entry the CI template refuses is
  refused here before anything is installed (exit 2): it must be an `"X.Y"` string, and that
  version must be a declared `Programming Language :: Python :: X.Y` classifier. A missing
  `Free Threading :: <level>` classifier draws a warning. Installing the free-threaded build, the
  check that it is current, and the rebuild of a `.venv-3.15t` that holds the GIL build all go by
  the build: a current 3.15t no longer reads as "needs install" on every run.

### Fixed

- `make test` now reports an import block that a NEW file made unsorted, as CI does. The
  `ruff_fix_apply` and `ruff_lint` stages run `ruff check --no-cache`. ruff caches each file's
  verdict by that file's own bytes, but isort's verdict also depends on which modules are
  first-party. Adding a root `conftest.py` makes `import conftest` first-party, and the cached run
  kept passing files that CI's fresh `ruff check .` failed with I001. The `ruff format` stages keep
  the cache. Measured cost: 39 ms for 286 files.
- The test suite no longer reads the app and host configuration layers of the machine it runs on.
  An autouse fixture points lib_layered_config's three app-root variables (`LIB_LAYERED_CONFIG_ETC`,
  `_MAC_APP_ROOT`, `_PROGRAMDATA`) at an empty directory under `tmp_path`, so a system-wide deploy
  (for example a `/etc/xdg/<slug>/config.d/99-*.toml`) can no longer fail tests locally while CI stays
  green. The subprocess tests in `test_logging_dotenv_isolation.py` dropped every
  `LIB_LAYERED_CONFIG*` variable and so read the real system layers; they now keep the redirect.
- `logdemo` works with lib_log_rich 7.0, which takes a `ConsoleTheme` member rather than a string
  (it failed with `AttributeError: 'str' object has no attribute 'value'`). `--theme` offers
  lib_log_rich's own theme list, so an unknown name is a usage error (exit 2) instead of the
  library's `ValueError` reaching `main()`, whose exit code was the OS errno (22 on POSIX, 87 on
  Windows).
- The test suite no longer reads the developer's own user configuration layer. `user_layer_in_tmp_path`
  is now autouse and points the user layer (`XDG_CONFIG_HOME`, `LIB_LAYERED_CONFIG_MAC_HOME_ROOT`,
  `_APPDATA`, `_LOCALAPPDATA`) at an empty directory under `tmp_path`; `HOME` is no longer redirected,
  because git and uv read it.
- The doctests under `src/` no longer run against the machine's configuration layers: a fixture in
  `tests/conftest.py` never reaches them. The two layer redirects now live in a rootdir `conftest.py`,
  their variable lists in `tests/layer_roots.py`; pyproject sets `testpaths` to include `src` and
  `tests` (which keeps the root `conftest.py` out of doctest collection), adds `tests` to `pythonpath`
  and pyright's `extraPaths`, and gives pyright an execution environment rooted at `tests/`. A test
  checks that every doctest collected from `src/` gets both redirects.

## [3.27.1] 2026-10-25 22:24:01

### Changed

- Internal only, no change in behaviour: `src` and `tests` carry no inline `type: ignore` or
  `pyright: ignore` left. Each one is replaced by a real annotation or a typed test fake.

## [3.27.0] 2026-10-25 21:18:58

### Changed

- A refusal now exits with the same code on every OS. A malformed `[tool.bmk.pipelines]` overlay,
  a `bmk_makescripts/stages.toml` whose `pipelines` is not a table, and a `pyproject.toml` or
  `stages.toml` that is not valid TOML or not UTF-8 exit **78** (configuration error) with one
  `Error:` line naming the file. They used to exit 22 on Linux and macOS and 87 on Windows, with
  the exception's text. `--traceback` still shows the traceback.
- `make test-all` with a worker count below 1 (`BMK_TEST_ALL_WORKERS` or
  `[tool.scripts.test-all].workers`) refuses before installing any Python, exit 2, without the
  stray `SystemExit: 2` line.
- The `devops-bmk` skill covers release cascades, the codecov upload in a repo with no remote,
  dependency floors that `make test` raises, and the `plugin.json` bump.

### Fixed

- The cooldown floor pins settle when the pins cycle. A forward pin that stopped reaching the
  requirement which asked for it made the passes repeat the same states until bmk gave up with
  "floor pins did not settle within 50 passes" and wrote no pin, leaving a release with only some
  of its files visible to `uv lock`. bmk now ends such a cycle on the strictest pin each package
  held in it, keeping a looser one only where the stricter would still expose a partly visible
  release.
- A passing JSON-mode run is quiet again: the HTTP client's per-request INFO lines
  (`HTTP Request: GET https://pypi.org/...`, one per PyPI document) no longer reach the console.
  Its warnings and errors still do.
- A `Makefile` that is not UTF-8 no longer aborts every command: the version check treats it as
  not bmk's, and `bmk install` refuses to replace it.
- An empty interactive commit message is refused with one `Error:` line instead of a traceback.

## [3.26.0] 2026-10-24 23:15:15

### Fixed

- The cooldown floor pins now also judge the requirements of a package that needs no pin itself.
  With `tool>=1.0` (no pin needed) requiring `gadget>=1.0`, a `gadget` release whose files straddle
  the cooldown went unjudged and `uv lock` could lock it with only some of its files visible; bmk
  now walks every package at the default cutoff and pins `gadget` too.

### Changed

- The dependency check reads all PyPI documents over one keep-alive connection pool and caches
  the per-file "installs on this Python" answer, which the settle passes asked hundreds of
  thousands of times. Together they pay for most of the wider walk above: on bmk's own
  `pyproject.toml` the pin check takes 11-13 s (159 PyPI documents), against 6-6.5 s before the walk
  (37 documents) and about 31 s for the walk without them.

## [3.25.3] 2026-10-24 21:00:26

### Changed

- The `devops-bmk` skill says every `make test-all` cell runs pyright once per OS in
  `[tool.ci].os`, as `make test` does, and that pytest runs on the host OS only. It also
  explains how a `pythonPlatform` pinned in the pyright config and a
  `pyrightconfig.<platform>.json` change those runs. It now names `make codecov`,
  `config-generate-examples`, `send-notification`, the short aliases (`b`/`bmp`, `cl`/`cln`,
  `p`/`psh`, `coverage`/`cov`) and `bmk.print_info()`.

## [3.25.2] 2026-10-24 18:52:21

### Changed

- The `devops-bmk` skill says an old bmk right after a release is usually the tool-lock skip
  (another bmk, a hung one included, holds the shared lock, so every `make` skips the upgrade until
  it exits), names the `make push` commit subject and where its message comes from on an
  already-committed tree, and says to gate the bumped commit, not the tree before the bump, since
  nothing in bmk raises a SKILL.md's `uvx` floors.

### Fixed

- In JSON mode, `deps --update`'s notices now appear in the stage's own report instead of
  printing past it: another bmk holding the project's `uv lock`, uv refusing `--refresh-package`,
  `[tool.uv] left as it is`, `floor pins left as they are`, a pin kept that no floor demands, and
  a rewritten spec refused as invalid.
- A failing stage command (`build`, `test`, `push`, `bump`, `release`, ...) and `install` beside
  a Makefile bmk does not manage no longer end with `SystemExit: N` on stderr after the real
  error. Exit codes are unchanged.
- `docs/email.md`: a list of SMTP hosts in an environment variable is a JSON array (a
  comma-separated string is refused), a `.env` line takes `EMAIL__...` without the `BMK___`
  prefix, and the Python example uses the `EmailConfig` fields `smtphosts` and `smtp_timeout`.

## [3.25.1] 2026-10-24 18:27:49

### Changed

- The `devops-bmk` skill and `docs/pyproject-reference.md` describe the venv's Python as the patch
  uv builds it on: its latest patch only under uv's default `python-preference`. They said "latest
  patch" unconditionally, which is wrong under `UV_PYTHON_PREFERENCE=system`.

## [3.25.0] 2026-10-24 15:21:52

### Fixed

- **The project venv is no longer rebuilt on every run when uv builds it on a different
  interpreter than the newest one installed.** bmk compared the venv with the newest installed
  patch, but uv picks by its `python-preference` and PATH order. With
  `UV_PYTHON_PREFERENCE=system` (or `python-preference` in `uv.toml` / `[tool.uv]`) and a distro
  Python older than uv's own, every run printed `[venv] python 3.14.4 -> 3.14.8: rebuilding
  .venv` and uv rebuilt it on 3.14.4 again; a free-threaded build with a higher patch did the
  same. bmk now asks uv which interpreter `uv venv` would use
  (`uv python find --system --show-version`) and rebuilds only when that differs.
- **A wheel-only release counts as installable on a Python only if it ships a wheel for it.** A
  release with no Requires-Python was taken as installable everywhere; pywin32 310 (wheels for
  cp38 to cp313 only, no sdist) was judged installable on 3.14, so floors were raised onto a
  release that cannot install there. Wheels are now judged by their tags (cpXY, abi3 from its
  floor, py3), sdists by Requires-Python as before. A floor can now be reported as unsatisfiable
  where it used to be raised.
- **`[tool.poetry]` dependencies keep their conditions and sources.** `markers`, `python` and
  `platform` were dropped, so `pywin32 = { version = "^306", markers = "sys_platform == 'win32'" }`
  was installed on Linux (and failed) and `tomli = { version = "^2", python = "<3.11" }` was
  demanded on 3.12. They now carry the marker, and `platform` is read as Poetry reads it
  (`linux || darwin`, `!=win32`). A `git`, `path` or `url` dependency, or one from a
  named non-PyPI `source`, is no longer looked up on PyPI under its bare name. The list form
  (several constraint tables) gives one requirement per table, extras are kept, a bare version is
  an exact pin (`2.13.0` was read as part of the package name), and `~=` is kept as PEP 440's
  operator.
- **A malformed pipeline overlay is refused with one line per problem.** The message carried
  pydantic's full report (input values, documentation links) cut at 500 characters; it is now
  `invalid [tool.bmk.pipelines.<name>] overlay:` followed by `  <location>: <reason>` lines, and
  an overlay from `bmk_makescripts/stages.toml` names that file and its `[pipelines.<name>]` table.
  Exit code unchanged (22; 87 on Windows).
- **`bmk_makescripts/stages.toml` wins whenever it names a pipeline.** An empty
  `[pipelines.<name>]` table there fell through to the `pyproject.toml` overlay, and a section that
  is not a table (an `[[pipelines.<name>]]` typo) was ignored silently while also hiding the
  `pyproject.toml` overlay. An empty table now means "no overlay", and a non-table section, or a
  `pipelines` key that is not a table in either file, is refused with `must be a table`.

### Changed

- The `--output-format` option of the coverage, shellcheck and PSScriptAnalyzer helpers lists
  `{text,json}` in its help and "invalid choice" text (was `{json,text}`); both values work as
  before.
- `bmk.adapters.stagerunner.venv.latest_installed_patch` is replaced by `patch_uv_builds_on`.
- `btx_lib_mail` floor raised to 4.6.0.
- `docs/pyproject-reference.md` and the `devops-bmk` skill describe the venv interpreter choice,
  overlay precedence and refusals, and the Poetry conditions above.

## [3.24.1] 2026-10-24 13:41:02

### Fixed

- **`bmk test` and `bmk custom` stop with exit 78 on a refused `[bmk.supply_chain]` value.** They
  read the section themselves and did not catch its error, so a cooldown such as `"14 Days"`
  crashed them with exit 1, while every other pipeline command stopped with CONFIG_ERROR (78)
  and one line naming the key. All pipeline commands now read `[bmk]` in one place.
- **`[bmk].show_warnings` applies to every pipeline command.** Only `test` and `custom` passed it
  on; every other command ran with warnings shown whatever was configured.
- **The dependency report prints a row's status as `[outdated]` on every Python.** On 3.11 and
  later it printed `[DependencyStatus.OUTDATED]`: a str-mixin enum interpolated into an f-string
  renders its name there, its value only on 3.10.
- A pyproject.toml with a wrong-shaped table (`tool = 3`, a list `project.scripts`, a string
  `[tool.coverage.run]`, a scalar `[tool.hatch].build`) reads as "not configured" instead of
  crashing a stage with AttributeError or TypeError. A non-array `[tool.pip-audit].ignore-vulns`
  gives no ignore flags (a string used to give one flag per character, a table one per key), and
  a non-array wheel `packages` falls through to the scripts and name rules instead of taking a
  string's first character as the package name. A scalar `[tool]` or `[tool.pyright]` no longer
  crashes the venv step that keeps the venv out of pyright; the file is left alone.
- A `.claude-plugin/plugin.json` that is valid JSON but not an object is reported ("cannot read
  plugin.json: not a JSON object") by the version sync and skipped by the release gate, instead
  of crashing both. A PyPI answer that is JSON but not an object reads as "package unavailable".

### Changed

- An invalid `fail_under` or `source` in `[tool.scripts.test]` is refused even when
  `[tool.coverage.report]` / `[tool.coverage.run]` supplies a valid value; the valid one used to
  mask it. Coverage-config validation errors name the nested key (for example
  `tool.coverage.report.fail_under`).
- A `[bmk].show_warnings` value that is not a boolean is refused with exit 78 instead of being
  used by its truthiness.
- Internal: every pyproject.toml, uv.lock, PyPI, `uv pip list`, pyrightconfig.json and
  plugin.json read is parsed into a typed model at the point it enters, bump kinds, tool names
  and pipeline results are enums end to end, and the `adapters.email.sender` re-export module is
  gone (import from `bmk.adapters.email`).

### Security

- filelock is floored at 4.2.1 for GHSA-2g95-wg33-c5x2 on Python 3.11 and later. The fixed
  release needs Python 3.11, so on 3.10 bmk keeps filelock 4.1.x; bmk uses only `FileLock`, not the
  affected `SoftFileLock` / `MarkerSoftFileLock` / `SoftFileLease`. 4.2.1 is younger than bmk's
  cooldown, so `[tool.uv]` pins it, as for certifi.

## [3.24.0] 2026-10-24 00:03:08

### Changed

- `make test-all` type-checks every OS your CI runs on, in every Python cell, with the same runs as
  `make test`'s pyright stage. A type error that shows only on one OS under one older Python,
  which neither gate saw before, now fails the cell that has it, and the failure names the run.
  Without `[tool.ci].os` a cell checks the host only, as before. Measured on bmk itself: 4.6-8.9 s
  per extra pyright run.
- The `devops-bmk` skill says how an outdated (or newer) Makefile is handled per output mode and
  that a text-mode gate with an unanswered terminal waits forever, that `release` run from a topic
  branch pushes that branch, and states current behaviour only.

### Fixed

- **The per-OS pyright check no longer overrides a project's own platform setup.** Since 3.23.0
  it forced `--pythonplatform` for every declared OS over the main pyright config, even when the
  project pins `pythonPlatform` there on purpose; a project keeping Linux-only modules in its
  main config (and Windows/macOS arms over `src` only) got 159 errors `make test` reported and CI
  never showed. A pinned main config now runs once, under its pin, as CI runs it, and each
  declared platform's `pyrightconfig.<platform>.json` arm runs through `--project`.

### Security

- setuptools (a transitive of bashate via pbr) is floored at 84.1.0 for GHSA-xmj3-9gf7-h52w. The
  fixed release is younger than bmk's cooldown, so `[tool.uv]` pins it, as for certifi.

## [3.23.3] 2026-10-23 22:56:09

### Fixed

- **A release above a floor that the cooldown cuts through is no longer locked half-visible.** When
  the floor's own release was admitted whole but a higher satisfying release had files on both
  sides of the cutoff, bmk wrote no pin, and uv locked that higher release with only its older
  files, so other platforms built from source or failed. `deps --update` now pins the package
  back to the newest release still whole, and drops the pin once the cut release clears the
  cooldown. It never pins forward past the floor's own upload. A package's pin is now chosen from
  every requirement that reaches it at once, and the tree is walked again at the new pins until they
  settle, so the walk order no longer changes which pins are written.

## [3.23.2] 2026-10-23 21:24:19

### Changed

- bmk's own lint enforces cyclomatic complexity at most 10 (ruff `C90`, the CLI template's rule).
  Six stage helpers were split to meet it (`clean`, `run_coverage_tests`, the coverage `main`,
  `_build_updated_spec`, `update_dependencies`, `reconcile_floor_pins`), each pinned first by tests
  of its exact output; behaviour is unchanged.

### Fixed

- **A `[tool.uv] exclude-newer` that uv refuses no longer makes `deps --update` delete your
  floor pins.** uv only warns about such a value and resolves no cutoff, which the pin reconcile
  read as "no cooldown": every `exclude-newer-package` pin bmk recognises then looked undemanded
  and was removed, and only afterwards did the check refuse the value and exit 1. The refusal now
  comes first, so the update exits 1 naming the value and leaves `[tool.uv]` as it was.

## [3.23.1] 2026-10-23 16:42:34

### Changed

- The `devops-bmk` skill covers 3.23.0: the `pyright` stage checks every OS family in
  `[tool.ci].os` while `test-all` covers only the Python versions; `bmk install` writes
  `.bmk-cooldown.mk`, which is committed with the Makefile; an exact pin is never moved and never
  fails the `deps` stage; and how to read which bmk a repo runs. It no longer says bmk is managed
  per project: its env is shared by every project on the machine.

## [3.23.0] 2026-10-23 15:48:52

### Changed

- **bmk's own tool env resolves under bmk's supply-chain cooldown.** `make` upgraded bmk's shared
  env with no cooldown, so a dependency release reached the env that runs every repo's ruff, pyright,
  bandit, pip-audit and build a minute after its upload. A release now writes bmk's window and its
  `false` exemptions (bmk and its own libraries) as uv flags to `src/bmk/makefile/cooldown.mk`;
  `bmk install` deploys it as `.bmk-cooldown.mk` beside the Makefile, which includes it, and refreshes
  the two together. Before each upgrade the template refreshes uv's tool receipt with those flags,
  since `uv tool upgrade` stores no option it is given. Flags rather than `--config-file`, which would
  make uv ignore your own uv config (a private index or proxy). Dated per-package pins are left out:
  one older than the window makes uv silently resolve an older bmk. When the window cannot be met (a
  fresh install whose bmk floor is younger than the window) the make installs without a cooldown and
  says so on stderr; the next make has the window again. A repo without the file behaves as before.
  Commit `.bmk-cooldown.mk` with the Makefile.
- A failed `make bump-*` also removes a synced file the bump created, instead of leaving it behind.
- **The `pyright` stage type-checks every OS the project's CI runs on.** pyright checks one
  platform per run, so `make test` on Linux passed code whose types break under Windows' stubs
  (`os.geteuid()`, `signal.SIGHUP`), and every windows-latest CI cell went red; this cost bmk two
  extra CI rounds on releases. The stage now runs `pyright --pythonplatform` once per OS family in
  `[tool.ci].os` (`ubuntu-*` -> Linux, `windows-*` -> Windows, `macos-*` -> Darwin), the key the CI
  workflow builds its OS matrix from, and fails if any run does; each run's output is headed by its
  command line. A project with no `[tool.ci].os` is checked for the host only, as before. A project
  that declares Windows and carries a Windows-only type error goes red on its next `make test`.

### Fixed

- **An exact pin (`pkg==1.5.0`, `pkg===1.5.0`) is no longer rewritten by the dependency update.**
  bmk read `==` as a floor, so a dev pin moved to `==1.6.0` on the first `make test` after 1.6.0
  reached PyPI, which broke a test pinned to the 1.5.0 release. An exact pin is now reported as
  pinned and left as written, whether the update would have raised it or lowered it to a release
  the oldest supported Python installs. A wildcard (`pkg==1.*`) and `~=` still move as before.

## [3.22.7] 2026-10-23 13:02:17

### Fixed

- **A dependency floor is no longer lowered when no single release installs on every supported
  Python** (a regression in 3.22.6). In a project classified 3.10-3.15, `pythonnet>=3.1.0` was
  rewritten to `pythonnet>=2.5.2`: 3.1.0 caps Python below 3.15 and 3.2.x needs 3.11, so no
  release covers both ends, and bmk looked for ONE release installing on every supported Python.
  Each Python is now judged on its own, as an installer resolves: the floor stands while every
  supported Python still finds some release at or above it, and a raise stops where one of them
  would find none.
- `deps --update` pins a young floor whose release has files on both sides of the cooldown cutoff,
  so uv locks the whole release, not only its older files. pydantic-core 2.50.1 uploaded 137 files
  over four minutes and straddled a 1-day cutoff: no pin was demanded, and an existing one was kept
  with the false note "no declared floor demands it".
- A failed or cancelled `make bump-*` is undone in full: the `__init__conf__.py`, Makefile and
  plugin.json syncs run inside the bump's undo, and SIGTERM or SIGHUP (a CI cancel, a closed
  terminal) undo the bump like Ctrl-C does; such a bump exits 128 plus the signal number. Before,
  a failing sync left the version bumped, so a re-run skipped a version. On Windows a cancel that
  terminates the process cannot be undone.
- `make deps-update` in JSON mode shows uv's own error when `uv lock --upgrade` fails; the failed
  stage block held only "uv lock --upgrade failed after the floor update".

## [3.22.6] 2026-10-23 10:08:52

### Fixed

- **A dependency floor is no longer raised to a release that drops a Python the project declares.**
  The floor check judged only the OLDEST supported Python, so in a project classified 3.10-3.14,
  `pkg>=1.0` was raised to `pkg>=2.0` although `2.0` declares `Requires-Python <3.13`. uv ignores
  that upper bound and installs it on 3.14 anyway (measured, uv 0.13.0), so no bmk gate or uv-based
  CI shows the break; pip on 3.14 refuses it ("requires a different Python"). A raise must now keep
  every later classifier Python the requirement as written already installs on, and the report
  names it (`does not install on Python 3.14`, `newest that keeps Python 3.14`). A Python no
  release of the requirement installed on before is not checked.
- `send-email --smtp-host H` and `send-notification --smtp-host H` send through `H` when the
  configuration names no SMTP host; they exited 78 "No SMTP hosts configured", because the hosts
  were checked before the command-line overrides were applied.

## [3.22.5] 2026-10-22 22:01:10

### Fixed

- **A project that declares a `[dev]` extra no longer gets a venv without it.** When no lock could
  be made, the fallback install tried `-e ".[dev]"` and, on ANY failure, `-e "."`. That second
  step was meant for a project with no dev extra, but it also caught a declared extra failing to
  install: the bare project then counted as provisioned, and the gate died later with
  `No module named pytest` instead of naming the install that failed. The target now comes from
  `pyproject.toml` - `.[dev]` when the extra is declared, `.` otherwise - and a failed install is
  reported as one.
- **`pip_audit` no longer reddens an unpublished project when PyPI answers 503.** The stage
  audited the project's own editable install like any dependency, so pip-audit asked PyPI for
  `/pypi/<project>/<version>/json`. For a project that is not published that is a 404 pip-audit
  skips, but an edge `503 Backend is unhealthy` failed the gate with nothing wrong in the tree.
  The stage now passes `--skip-editable`: the project's own package is skipped before any query,
  and its dependencies, which are not editable, are still audited.
- **Dependency floors are judged in PEP 440 order.** The floor check compared only a version's
  leading digits, so every release differing in a post, pre or dev part tied and was ordered as
  a string, and an epoch was read as the whole version: `pkg>=1.0.post2` was reported up to date
  beside `1.0.post10`, `pkg>=1!7.0` beside `1!9.0`, and a floor held to the oldest Python went to
  `1!9.0` where `1!10.0` installs. Versions are now ordered by `packaging.version.Version`.
- **A prerelease is a candidate where uv would take one.** uv installs a prerelease when the
  requirement names one or when the package publishes nothing else; the floor check skipped every
  prerelease. So `pkg>=8.0b2` on a package whose `8.0b2` needs a newer Python stayed in place
  where `8.0b1` installs, and a package with only prereleases was reported as `no release
  installs` although uv installs one. Both cases now follow uv.
- **A floor raised without a Python to hold it to stays inside the requirement's own bounds.** In
  a project that states no Python versions, only bare `<` was read as a ceiling, so
  `hypothesis>=6.168.3,<=6.168.4` was rewritten to `hypothesis>=6.169.0,<=6.168.4`, which nothing
  satisfies, and an `!=` exclusion of the newest release was ignored the same way. The update now
  judges the whole ceiling (`<`, `<=`, `!=`), as the Python hold already did.
- **`bump` writes `[project].version` itself, whatever its spelling.** The bump replaced the
  text `version = "<old>"`, so `version="0.1.0"` was left unchanged while the bump printed
  `Bumped version: 0.1.0 -> 0.1.1` and exited 0, and a `version` key in a table before `[project]`
  was rewritten instead of the project's. The version is now set through a tomlkit round-trip,
  which keeps comments, formatting and the quote style.
- **A pre-release Python classifier no longer rebuilds its venv on every run.** The newest
  installed patch was taken as uv's version text, which for a beta reads `3.16.0b1`, and compared
  for equality with what the venv's interpreter reports, `3.16.0`. The two never matched, so the
  venv was deleted and re-resolved each time. The patch is now compared as `X.Y.Z` on both sides.

## [3.22.4] 2026-10-22 19:00:45

### Changed

- **Every venv-provisioning failure now says why, not only a failed sync.** A failed `uv venv`,
  `uv lock` or no-lock fallback install (`uv pip install` from `pyproject.toml`) used to discard
  uv's stderr in JSON mode, so provisioning said at most `uv lock failed` with no reason. Each now
  reports like the sync does: `[venv] uv venv failed for <venv> (exit N; venv afterwards: <state>)`,
  `[venv] uv lock failed in <project> (exit N); provisioning <venv> from pyproject.toml instead`, and
  `[venv] uv pip install (fallback from pyproject.toml) failed for <venv> (...)`, followed in JSON
  mode by all of uv's stderr; in text mode uv streams live and only the header is added. A `uv venv`
  that exits 0 without leaving a venv is reported too, and a report with nothing from uv to show
  no longer ends in a colon. When uv cannot be run at all (missing from `PATH`, not executable),
  the header is followed by `could not run uv: <error>` in both modes, where it used to stand alone.

### Fixed

- **A project with no Python classifier no longer loses a 3.10 (or 3.9) venv that `uv sync`
  recreates.** 3.22.3 asked the sync for the declared minor, but a project declaring none still
  passed the venv's own `bin/python` as `--python`, the request that leaves an empty directory when
  uv recreates the venv on CPython 3.10 and older. The sync now asks for what that venv's
  interpreter reports: `pypy@X.Y` for PyPy, `X.Yt` for a free-threaded build, otherwise the bare
  minor (`--python 3.10`), so a recreate keeps the implementation instead of falling back to uv's
  default CPython. Only an interpreter that cannot answer is still passed by path.
- **`bmk test` / `bmk deps update` print a failed venv sync once, and a `deps_update` stage that
  fails on that sync says why instead of `(no output captured)`.** Provisioning syncs the venv
  before the pipeline, and the `deps_update` stage synced it again after its `uv lock --upgrade`, so
  a failing sync printed its `[venv] ...` block twice while the stage's own block stayed empty: the
  re-sync wrote to stderr, past the stage's capture. When provisioning already failed this run on a
  venv that still exists and the upgrade left `uv.lock` byte-for-byte unchanged, the stage no longer
  retries; it fails with one line, `<project>: venv provisioning already failed above; uv.lock
  unchanged by the update, not retrying`. A failed provisioning that left no venv still passes the
  stage, so the gates fall back to bmk's own interpreter as before. When the lock did change it
  still re-syncs, and in JSON mode the `[venv]` report and the `... failed after the floor update`
  line now land in the stage's captured output (text mode keeps them on stderr). A `[tool.uv]`
  cooldown uv refuses is reported there too, where it used to go to stderr; a failed
  `uv lock --upgrade` is named there by its step, without uv's reason. `BMK_NO_VENV_SYNC=1` now also
  skips that re-sync, as it already skipped provisioning.
- **The devops-bmk skill describes the lock-first venv.** It said bmk syncs the project venv to
  `pyproject.toml` with an exact, upgrading install and gave
  `uv pip install --exact --upgrade -e ".[dev]"` as the hand resync. bmk syncs from `uv.lock`
  (`uv lock`, then `uv sync --locked`) and installs from the manifest only when no lock can be made.
  The skill now gives the lock-first resync, keeps the manifest install for a `[venv] uv lock
  failed` line only, lists every `[venv]` provisioning failure header, says when `make test`'s
  first stage, `update_deps` (it runs the `deps_update` pipeline), stops the run after a failed
  provisioning, and no longer says every in-process stage fails with only `(no output captured)`:
  `deps_update` names its failure, with uv's reason for a failed re-sync and by its step only for a
  failed lock upgrade. Its hand resync for a project without a Python classifier asks for what the
  venv's interpreter reports (`pypy@X.Y` for PyPy, `X.Yt` for a free-threaded build, otherwise the
  bare minor such as `--python 3.10`), never the interpreter's path.

## [3.22.3] 2026-10-21 20:59:38

### Fixed

- **A 3.10 (or 3.9) `test-all` cell no longer ends as an ERROR with an empty venv after a Python
  patch upgrade.** An old venv whose `pyvenv.cfg` names an older patch than its interpreter is
  removed and recreated by `uv sync`, from the `--python` interpreter's `sys._base_executable`. bmk
  passed the venv's own `bin/python`, and on CPython 3.10 and older that base executable is inside
  the venv uv had just deleted, so uv failed with `failed to canonicalize path`. The sync now asks
  for the cell's minor (`--python 3.10`), the same request `uv venv` gets; only a venv with no
  declared minor still passes its interpreter. One consequence: when the declared minor cannot be
  found (offline, not installed), the sync now fails with uv's "No interpreter found" and the
  `[venv]` report, instead of silently re-syncing an existing venv on a different minor.
- **The devops-bmk skill no longer says JSON mode hides a failed provisioning sync**: it points at
  the `[venv] uv sync from uv.lock failed ...` line, printed in every output mode since 3.22.2.

## [3.22.2] 2026-10-21 17:31:29

### Changed

- **A failed `uv sync` while provisioning a venv now shows uv's own error, in every output mode.**
  In JSON mode (the default) the sync's stderr used to be discarded and the failure line only
  suggested a text-mode re-run, which loses the evidence of an intermittent failure. The line now
  reads `[venv] uv sync from uv.lock failed for <venv> (exit <rc>; venv afterwards: <state>)`,
  where the state is `venv`, `directory without pyvenv.cfg`, `empty directory` or `absent`. In
  JSON mode a colon and ALL of uv's stderr follow it, indented, colour codes removed, written as
  one block so parallel `test-all` cells cannot interleave inside it. In text mode uv's output
  streams live as before, with its progress display, so only that line is added after it.

### Security

- **CI pins its third-party actions to full commit shas** (`pypa/gh-action-pypi-publish`,
  `astral-sh/setup-uv`, `codecov/codecov-action`, the ref kept in a comment), distributed from the
  `default_cicd_public` template; Dependabot groups their updates into one monthly PR.

## [3.22.1] 2026-10-21 15:44:41

### Fixed

- **A hand-placed `exclude-newer-package` pin is no longer removed while the cooldown still
  excludes its release.** bmk recognises its own floor pins by value (one second after an upload),
  so a pin a project set by hand at that same second read as bmk's. When no declared floor demanded
  it, `make test` and `deps update` removed it with "the cooldown admits it", although the cooldown
  did not, and the next lock went back to the older release the pin was placed to leave (a
  security fix in a transitive dependency was lost this way). Such a pin is now kept until the
  cooldown admits its release, and named on stderr as "pin kept: no declared floor demands it". A
  pin bmk wrote for a floor that has since been lowered therefore stays for at most one cooldown.

### Security

- **certifi is floored at 2026.10.19 (PYSEC-2026-4320).** It reaches bmk through pip-audit's
  requests. The release is younger than the 7-day cooldown, so `[tool.uv]` carries a per-package
  pin for it until the cooldown admits it.

## [3.22.0] 2026-10-19 20:08:07

### Changed

- **The default supply-chain cooldown is 7 days, up from 1 day.** `[bmk.supply_chain].cooldown`
  defaults to `"7 days"`, so `make test` and `deps update` write `[tool.uv] exclude-newer = "7 days"`
  into a project that has none, and raise third-party floors only to releases at least a week old. A
  project that already sets `exclude-newer` keeps its own value, as before. A test now also pins the
  value in the shipped `defaultconfig.d/10-bmk.toml`, which is what an installed bmk reads, to the
  documented default.

## [3.21.5] 2026-10-18 11:34:32

### Added

- **`devops-bmk` skill: a release refused for a dirty tree.** `release` counts only tracked
  changes as dirty. An unrelated edit is set aside and restored after the release, never
  committed to get past the refusal, because the tag lands on HEAD and that commit never ran
  in CI. bmk's own Makefile and floor churn is committed and pushed first, and the release
  waits for CI on that commit, since `release` does not check it.

## [3.21.4] 2026-10-17 00:39:55

### Fixed

- **`devops-bmk` skill: the empty integration lane.** `make testintegration` that collects no test
  exits 2 (make's code for a failed recipe, after `Error 5`), not 5; only bmk itself exits 5, so the
  skill now keys on the `[pytest_integration] (exit code: 5)` line. It also separates the two
  causes: no test carries the marker (an empty lane, reported as neither passed nor failed) and
  integration tests that exist but were filtered out (a real fault).

## [3.21.3] 2026-10-17 00:17:32

### Changed

- **`devops-bmk` skill: the reds that come from bmk itself, and two corrections.** It now names a
  `ModuleNotFoundError` inside bmk's own dependencies as bmk's shared env (`bmk_selfcheck` repairs it
  on the next `make`); says the "waited 10s for the lock ... gave up. Nothing was changed." line
  speaks only for the skipped upgrade, not for the target that printed it; explains the `push`
  `deps` stage that fails with only `(no output captured)` when a dependency floor falls behind a
  fresh PyPI release; states that `release` tags the version already in `pyproject.toml` (bumping
  first skips it) and pushes the branch then the tag, and that `push` commits with `git add -A`;
  says `make test-all` is the only cross-version run `local_only` tests get; and explains the
  exit 5 an empty integration lane produces. Corrected: a version mismatch is cured by the next
  sync, not by `rm -rf .venv`; the shell-lint gate runs `shfmt -d -i 4 -bn -ci` and takes
  bashate's line length and ignores from `[tool.bashate]`; and the Makefile no longer passes
  `--refresh-package bmk`.

## [3.21.2] 2026-10-15 15:23:57

### Fixed

- **`make test-all` honours `[tool.scripts.test].exclude-markers`.** Every cell ran pytest with a
  fixed `-m "not integration"`, so a project that keeps host-mutating tests out of `make test`
  with `exclude-markers = "mutating"` had them collected in every test-all cell, run in parallel
  and, on a host with passwordless sudo, run as root. The cells now apply the same filter
  `make test` does: the project's value, `integration` when the key is unset, and no filter when
  it is empty.

## [3.21.1] 2026-10-13 14:14:15

### Fixed

- **`make test-all` no longer loses a cell to "could not provision a venv for this Python".**
  `uv python install` and `uv python upgrade` rewrite every minor alias symlink in uv's Python
  store even when they change nothing, and every venv resolves its interpreter through such an
  alias. Each test-all cell ran both before syncing, in parallel, so a cell already syncing (most
  often 3.10, the first to finish) found "No interpreter found at path .venv-3.10/bin/python".
  bmk now asks `uv python list` first and runs neither command when uv has nothing newer for that
  minor, and test-all prepares every minor serially before its cells start; the cells no longer
  run `uv python install` or `upgrade` themselves. The no-op rewrite also broke venvs of any other bmk running on
  the same machine; that is gone too.
- **`make bump-*` re-locks a project that commits `uv.lock`.** The lock records the project's own
  version, so a bump left it stale and CI's `uv export --locked` (and `uv sync --locked`) refused
  the release commit. If the re-lock fails (uv's own error is shown), a file cannot be written,
  or the bump is interrupted with Ctrl-C, `pyproject.toml`, `CHANGELOG.md` and `uv.lock` are put
  back byte for byte, so a re-run does not skip a version. A file that cannot be put back is named
  with the reason, never reported as undone.
- **An own package released minutes ago is no longer invisible to the floor update.** PyPI serves
  its index with `max-age=600` and uv honours it, so `uv lock --upgrade` kept resolving the previous
  version and the own floor did not rise. The upgrade lock now passes `--refresh-package` for every
  package `[tool.uv] exclude-newer-package` exempts (`= false`). Only when uv refuses that flag
  itself (offline configured) does the lock run once more without it, saying so; any other lock
  failure stands as it is.

## [3.21.0] 2026-10-12 20:51:09

### Fixed

- **An unpublished project that names itself in its own extras no longer freezes its floor pins.**
  bmk 3.20.0 keeps per-package `[tool.uv] exclude-newer-package` pins for floors younger than the
  cooldown and removes each one once the cooldown has passed its release. To decide that, it reads
  every requirement's release list from PyPI - including a self-reference such as `demo[cli]` in
  demo's own `dev` extra. For a project that is not on PyPI that read fails, and bmk then left every
  pin as it was ("floor pins left as they are: release list of demo unreadable"), so a pin dated a
  second after today's pydantic release held pydantic at that version for good, and the next floor
  raise past it could not lock. The project's own name is now skipped: it is installed from the
  source tree and needs no pin. Pins already written are removed on the next `make test` once their
  release is older than the cooldown.

### Changed

- **`BMK_OUTPUT_FORMAT` is read in any case, and an unknown value is named.** bmk matched the
  value exactly, so `BMK_OUTPUT_FORMAT=TEXT` - the spelling people type - ran JSON mode without a
  word, and so did a typo: the reader saw no verbose output and concluded text mode had none to
  show. `text` and `json` are now accepted in any case. Any other non-empty value (whitespace
  included: `" text "` is not trimmed) still runs JSON mode, unless `--human` asks for text, and
  prints one line on stderr naming it:
  `[bmk] BMK_OUTPUT_FORMAT='txt' is not 'text' or 'json' (in any case); it is ignored.` An unset or
  empty variable is the JSON default, as before, without a warning. A caller that set `TEXT` and
  was silently getting JSON now gets text mode: verbose output, and the Makefile-outdated question
  when stdin is a terminal.

## [3.20.1] 2026-10-12 19:25:20

### Fixed

- **An all-digit value in a text setting no longer stops startup.** lib_layered_config reads an
  unquoted `.env` or environment value that spells a number losslessly as an int, so
  `LIB_LOG_RICH__SERVICE=2770` reached the logging settings model as `2770` and was refused with
  `Input should be a valid string`. The model now turns such a number back into the text the
  operator wrote. The email settings already did this for the user name and password; a test now
  pins it end to end through a real `.env`.
- **The "Makefile is outdated ... Update? [y/N]" question no longer hangs an unattended run.** In
  text mode (`BMK_OUTPUT_FORMAT=text`) bmk asked it on every command whose project carried an
  older Makefile, and read the answer from stdin whatever stdin was. An agent or a CI step hands
  its child an open pipe that nobody writes to, so the read never returned, and the stuck process
  kept holding the shared tool-env lock, so other repos' `make` runs waited out their timeouts as
  well. bmk now asks only when stdin is a terminal. Otherwise it keeps the Makefile, as the
  question's own default does, and prints `run 'bmk install' to update it` on stderr. JSON mode
  still updates the Makefile without asking. A terminal nobody answers (a pty driven by tmux,
  pexpect or `ssh -tt`) is still asked, so run such callers in JSON mode.

### Changed

- **Piped text no longer answers the Makefile question.** `yes y | make test` used to accept the
  update in text mode; it now gets the stderr note and the Makefile is kept. Run `bmk install` to
  update it. A console that Python does not see as a terminal - native Windows Python in mintty /
  Git Bash without winpty - gets the note instead of the question too.

## [3.20.0] 2026-10-12 18:25:31

### Added

- **A supply-chain cooldown: third-party releases are adopted only once they are 1 day old.**
  A malicious release is usually found and pulled within days of its upload. `make test` (the
  `update_deps` stage) now keeps `[tool.uv] exclude-newer = "1 day"` in the project's
  `pyproject.toml`, and uv refuses every file uploaded inside that window for the whole tree,
  transitive dependencies included. The floor update follows the same rule: a third-party floor
  rises only to the newest release older than the cooldown, a release still inside it no longer
  counts as outdated, and a floor that is itself younger than the cooldown is never lowered:
  when nothing it admits has passed the cooldown, `deps --update` gives it a per-package cutoff
  just after the upload of the satisfying release uploaded first that installs on the oldest
  supported Python (`exclude-newer-package`, `<name> = "<timestamp>"`), walks that release's own
  requirements the same way (pydantic 2.14.1 needs exactly pydantic-core 2.50.1) on every platform,
  Python and requested extra `uv lock` resolves for, and drops the entry once the cooldown admits
  the release. Entries the project set itself are never touched, and a
  `[tool.uv.exclude-newer-package]` table keeps its comments. A bare `deps` check fails on a floor
  `uv lock` cannot satisfy; one it could not read from PyPI is reported and does not fail it. Our
  own packages follow their newest
  release: bmk adds `<name> = false` under `exclude-newer-package` for every own package the
  project reaches, walking own packages' requirements on PyPI, because an exempt package whose
  newest release needs a non-exempt own package silently resolves to an OLDER release. A value
  the project already set (its own cooldown, or a shorter one for a young security fix) is kept.
  The cooldown and the own-package list are configurable under `[bmk.supply_chain]`; bmk writes
  only values uv certainly reads, and a value uv refused stops the check instead of silently
  disabling the cooldown: floors are judged against the cutoff uv resolved, read back from
  `uv.lock`, never from a second parser of uv's grammar. An own package's floor rises only to the
  newest release `uv lock` can resolve under the cooldown. `push`, `deps`, `cov`, `build` and the
  integration lane now honour `[bmk.supply_chain]` and `[bmk].package_name` like `test` does.
- **Venvs are built from `uv.lock`.** Every venv bmk provisions, the `test-all` matrix included,
  is synced with `uv sync --locked` after `uv lock`, so `make test`, pyright and pip-audit check
  exactly the tree the lock pins and CI installs; `uv pip install --upgrade` used to keep a release
  newer than the cooldown. `update_deps` re-locks with `uv lock --upgrade` and re-syncs, and the
  `uv_lock` stage that follows only checks the lock (`uv lock --check`). Without a lock, bmk falls
  back to installing from `pyproject.toml` and says so.
- **`--env-file PATH`** root option: read this `.env` file instead of searching upward for one.
  Without it, the upward search behaves as before.

### Changed

- **Synced with bitranox_template_py_cli 2.4.0** (a three-way merge from the template of
  2026-07-24, the nearest version bmk matched). The template's fixes replace bmk's hand-made
  versions of them; bmk's own commands and aliases, the stage runner, the bundled Makefile,
  `config.d/10-bmk.toml` and the grouped runtime dependencies stay.
- A configuration that cannot be loaded no longer stops every command: the root records the
  failure, a command that reads the configuration (`config`, `send-email`, `send-notification`,
  `test`/`t`, `custom`) refuses with exit 78 and one `Error:` line, and the others run.
- `EmailConfig` is a subclass of btx_lib_mail's `ConfMail` (`btx_lib_mail>=4.0.0`). The Python
  field names follow ConfMail (`smtphosts`, `smtp_use_starttls`, `smtp_timeout`); the keys in the
  configuration files stay the same.
- An unknown key in `[email]` or `[email.attachments]` is refused (exit 78), with one `Error:` line
  per problem that names the file key (`email.timeout`, not `email`).
- New `[email]` keys: `starttls_verify`, `local_hostname`, `delivery_deadline`,
  `recipient_max_count`, and `attachments.max_count`.
- A delivery error keeps the library's message; it is no longer replaced when it contains a word
  such as "password".
- `config --profile` checks the logging configuration with `lib_log_rich.validate_config` and
  refuses what `config` without a profile refuses.
- A `--set` value appears in the `config` output with the source `cli`.
- `send-notification` no longer offers `--raise-on-missing-attachments`; it takes no attachments.
- Command output goes through `safe_console.echo`, so a console with a legacy code page (cp1252)
  does not abort it.

### Fixed

- The `graylog_endpoint` and `rate_limit` notes in `.env.example` and `90-logging.toml` said a
  `host:port` or `100:60` string makes every command exit 22. It does not: `info` still runs
  (exit 0) and the commands that read the configuration exit 78. The notes now say that only the
  native `LOG_GRAYLOG_ENDPOINT` and `LOG_RATE_LIMIT` variables take that form.
- **The shell-lint and PSScriptAnalyzer stages no longer lint scripts git ignores.** Both found
  their files by walking the whole project, so a scratch launcher left in a gitignored directory
  (one whose own `.gitignore` says `*`, for instance) failed shellcheck or shfmt and turned
  `make test` red while the code under test was clean. Inside a git work tree they now lint the
  scripts git tracks plus untracked ones no `.gitignore` excludes; a tracked script stays linted
  even where an ignore pattern covers it. Outside a git work tree, or when the enclosing
  repository ignores the project directory itself, they walk the directory as before; on Windows
  `Build.PS1` still matches in any letter case. Variables inherited from git that would change
  its answer (`GIT_DIR`, `GIT_LITERAL_PATHSPECS` and the like) are not passed on. When git
  refuses a checkout (dubious ownership, for instance) or cannot be started there, the stage walks
  the directory and says so on stderr. The PowerShell stage now also skips a nested git
  checkout (a linked worktree or a nested clone), as the shell stage already did.

## [3.19.0] 2026-10-12 09:38:11

### Fixed

- **The dependency update no longer raises a floor past the project's oldest supported Python.**
  It took each package's newest release from PyPI regardless of that release's `Requires-Python`,
  so when hypothesis 6.169.0 dropped Python 3.10, every 3.10 project's `make test` rewrote
  `hypothesis>=6.168.x` to `>=6.169.0` and its dev extras stopped resolving on 3.10 (`test-all`
  then reported only "No module named pytest" for that cell). The floor now rises only to the
  newest non-yanked release whose `Requires-Python` admits the oldest Python the project supports
  (its lowest classifier that `requires-python` admits, or `requires-python`'s own lower bound
  when it has no classifiers; a `requires-python` below every classifier no longer counts, and
  one with no lower bound, such as `<4`, states no oldest Python); a requirement marked for newer Pythons
  only (`; python_version >= '3.11'`) follows those.
  A floor already above that release, so that nothing the requirement admits installs on that
  Python, is lowered to it: an unresolvable floor is the one case in which the update lowers a
  floor, so a project whose floor was already raised past its oldest Python repairs itself on
  its next `make test`. Newer Pythons keep installing the newest release, since a floor is only
  a minimum. Each package's PyPI document is read once per check, and when its release list
  cannot be read the floor is kept and the dependency reported as an error rather than raised
  blind; a connection reset or a corrupt response from PyPI no longer crashes the check.
- **A requirement whose cap or exclusion is written before its floor is no longer read as having
  that cap as its floor.** `pkg<=7,>=6` and `pkg!=2.0` were read as floors 7 and 2.0; `pkg!=2.0`
  was reported outdated on every run, which the update could never settle, so `make push` failed
  at its dependency check. The floor is now taken only from `>=`, `>`, `==`, `===` and `~=`.
- **Versions in a requirement are read whole, epoch and pre-, post- and dev-release parts
  included.** `pkg>=7.0.post1` was read as floor `7.0.` and rewritten as `pkg>=7.0post1`,
  `pkg>=1!2.0` as `pkg>=8.0!8.0`, and `pkg==1.*` as `pkg==8.0*`; all three were invalid
  requirements. A wildcard is now kept on the release segment only (`pkg==8.0.*` when the
  newest release is `8.0.post1`). Versions are read in their normalized PEP 440 spelling; a
  rewrite that would not be a valid requirement (as with `pkg>=1.0c1` or `pkg>=1.0RC1`) is
  never written, but reported on stderr, and the dependency stays outdated until the spec is
  normalized.
- **Whether a floor installs is judged the way the installer judges it.** A prerelease floor
  (`pkg>=8.0rc1`) counts as installable while a prerelease the floor does not name does not, and
  a yanked release counts when the requirement pins
  it exactly (`pkg==6.5`), which is when uv still installs it (PEP 592). A requirement that is
  not valid PEP 508 keeps its floor and is reported, rather than crashing the check.
- **A strict floor (`pkg>X`) moved to a release is written as `pkg>=release`**, so it admits the
  release it was moved to; `>` kept as-is excluded exactly that release.
- **`email.smtp_hosts` and `email.recipients` set to nothing mean not configured.** A bare YAML
  key or an environment `null` was refused as "Input should be a valid list" for both settings.
  Both now read `None` as an empty list.

### Security

- **An email attachment allow or block list given in a form it cannot be read in is refused
  instead of silently ignored.** A comma-separated value (`.pdf,.txt` in an environment variable
  or `.env`) arrives as one string, and the validators turned any value that was not a list into
  "not configured", so btx_lib_mail's default lists applied in place of the configured ones. A
  list or tuple is read as its items (an empty one still means not configured), a set is kept as
  given, an empty value means not configured, and anything else fails validation naming the
  setting and the accepted form (a JSON array such as `[".pdf", ".txt"]`). `smtp_hosts` and
  `recipients` no longer turn a tuple or another non-list value into an empty list. The shipped
  `50-mail.toml` and `.env.example` documented the comma form for all six list settings; they now
  show the JSON-array and per-index forms.

## [3.18.0] 2026-09-28 22:58:34

### Added

- **`test-all` can be capped to run its version cells one at a time.** Every declared Python
  version's cell ran fully in parallel with no knob: fine for most projects, but one whose suite
  binds fixed `127.0.0.1` ports or shares one test database sees its cells break each other -
  measured in soundtouch-zonemaster as 45/50/1 failures plus around 150 errors per cell that were
  all green run serially. `[tool.scripts.test-all].workers = 1` in the project's own
  `pyproject.toml` (or `BMK_TEST_ALL_WORKERS=1` for a one-off run, which wins when both are set)
  now declares that once. The default is unchanged - unset, `test-all` stays fully parallel. A
  configured value above the number of declared versions is capped down to it; a value below 1 is
  refused with a clear error and exit code 2, never a silent no-op.

## [3.17.1] 2026-09-02 12:12:33

## [3.17.1]

### Added

- **`devops-bmk`: how to prove a gate actually enforces.** Two readings of a green `make test` that
  are wrong, both verified against the installed source. `ruff_fix_apply` is stage order 30 while
  `bandit`, `lint_imports`, `pip_audit`, `pyright`, `pytest` and `ruff_lint` are all 40, so a probe
  planted to prove a checker fires can be deleted before that checker ever sees it. And an
  undeclared tool does NOT mean its stage was skipped: `context._prepend_tool_bin_to_path` puts
  bmk's own venv bin dir first on the child PATH so bare-name stages resolve to bmk's pinned
  toolchain, and `lint_imports_argv` returns a bare argv, so a missing tool fails loudly rather
  than silently skipping. Mirrors the same section in the bitranox-skills copy of this skill.

## [3.17.0] 2026-08-20 17:51:25

### Fixed

- **A new bmk release could rebuild the shared tool environment under a gate running in
  another repo.** bmk installs itself once per machine, into uv's tool dir, and the generated
  Makefile upgrades that environment before EVERY target. The moment a new version reached
  PyPI, the first `make` that noticed rebuilt it in place while any other bmk - another repo's
  gate, a subagent's `make test` beside the main agent's - was still running out of it. What
  the victim reported was an ImportError inside bmk's OWN dependencies (`pip_api._hash`,
  `pydantic.functional_serializers`) that cleared on a re-run, so it read as a flake rather
  than as its interpreter's site-packages being deleted mid-gate. Every bmk process now holds
  a SHARED lock on the tools root for its lifetime, and the Makefile takes the same lock
  EXCLUSIVE around the upgrade. Readers never exclude each other, so two repos still gate
  concurrently - a guard that serialised gates would be the machine-wide stall this removes.
  The wait is bounded in both directions: an upgrade that cannot get the lock is SKIPPED,
  because a deferred upgrade costs nothing and blocking would serialise every repo's `make`
  behind the longest gate on the machine, while a REPAIR that cannot get it FAILS, because
  skipping would continue on a damaged environment.

### Added

- **`bmk_toollock`, a second stdlib-only top-level module, and `BMK_TOOL_LOCK`.** The guard has
  to run from the Makefile before bmk's Python starts, and it must keep working when the
  environment it guards is the damaged thing being repaired - so it imports nothing, not even
  bmk. That is not circular: a uv tool env's `bin/python` is a symlink to a base interpreter
  OUTSIDE the tool dir, so the stdlib it runs on is not part of the tree uv replaces. POSIX uses
  `fcntl.flock`; Windows uses `LockFileEx` through `ctypes`, because `msvcrt.locking` cannot
  express a shared lock at all. `BMK_TOOL_LOCK=0` disables it.
- **bmk now says when its own environment was replaced mid-run.** A lock only helps once both
  sides take it, and two writers are permanently out of reach: a repo whose Makefile predates
  this change, until its next `make` regenerates it, and a hand-run `uv tool install bmk`. When
  a command fails and the tool env's receipt turns out to have changed since the run started,
  bmk prints one line saying so. It is checked on any failure rather than only on an ImportError,
  because a replaced environment usually kills a spawned pyright or pip-audit and surfaces as a
  non-zero stage instead.

### Changed

- **bmk's own `Makefile` guards its editable rebuild too.** Its stamp makes that rebuild rare,
  not safe; when it does fire it still tears the environment down, and its own comment names the
  case - a subagent and the main agent both running `make` in this repo. The lock resolves to
  `.venv-bmk/.bmk-tool.lock` there and to uv's shared tools root for the template, with no branch
  in the code: `uv-receipt.toml` is what marks a tool environment, and its parent is where the
  lock goes.

## [3.16.0] 2026-08-20 17:05:36

### Fixed

- **Two bmk processes could provision the same venv at once, and the one that lost went on to
  test a different environment without saying so.** `ensure_project_venv_at` ran `uv venv` and
  `uv pip install --exact --upgrade` with no cross-process guard, so a subagent's `make test`
  beside the main agent's, or `test-all` beside `test`, could pull the environment out from under
  a running gate. Measured on the unguarded code, driving the real function from two separate
  processes on a cold start: one of the two returned a provisioning failure in 5 of 8 rounds; with
  the lock, 8 of 8 succeed. The failure was silent, which is what made it worth fixing -
  provisioning never raises, by design, so the losing gate degraded to bmk's own interpreter and
  type-checked, audited and tested the wrong environment with nothing in its output saying so.
  Provisioning is now serialised by an exclusive lock whose scope is one venv path, so the version
  matrix still provisions its cells in parallel. The lock covers the sync only, never a whole
  gate: a gate-lifetime lock would deadlock bmk against itself, because `push` runs the test
  pipeline and `test-all` spawns a cell per Python version inside one process tree. A timeout does
  not fall through to syncing anyway - provisioning may fail, but it may never run concurrently
  with another bmk's sync, which is the corruption being prevented. Editing `pyproject.toml` while
  a gate is already running remains unguarded; closing that needs a reader-writer design and is
  deliberately not attempted here.

### Added

- **`BMK_VENV_LOCK_TIMEOUT` and `BMK_VENV_LOCK_DIR`.** How long to wait for another bmk that is
  provisioning the same venv (default 600 seconds), and where the lock files live (default
  `~/.cache/bmk/venv-locks`). The directory is deliberately outside every repository: inside the
  venv is destroyed by the rebuild the lock exists to guard, and beside the venv leaves an
  untracked file in `git status`, because the existing `.venv*` rules are written with a trailing
  slash and so match directories only.

### Changed

- **`filelock` is a declared dependency rather than a transitive one.** It arrived via
  `pip-audit -> cachecontrol[filecache]`, far too fragile a provenance for something bmk imports:
  dropping pip-audit would have taken the lock with it.

## [3.15.0] 2026-08-17 15:47:15

### Added

- **A project version may now be any canonical PEP 440 version, not only `X.Y.Z`.** `release`
  refused `0.1.0rc1` outright ("Could not read version X.Y.Z from pyproject.toml"), `bump` crashed
  on it (`invalid literal for int() with base 10: '0rc1'`), and the plugin-version sync silently
  stopped running - three gates, three different failures, so fixing only the loud one would have
  left a project able to release a pre-release but not to bump it. hatchling builds
  `pkg-0.1.0rc1.tar.gz` and PyPI accepts it; bmk was the only thing saying no. Pre-releases, dev
  releases, post releases, a short release segment (`1.0`) and an epoch (`1!2.0.0`) are all
  accepted now. The rules live in one place, `bmk.domain.version`, shared by all three gates.

- **`bump` finalizes a non-final version instead of stepping past it.** `1.2.3rc1` patch-bumps to
  `1.2.3`, not `1.2.4`, so the release an rc was rehearsing stays reachable; a post release is
  final, so `1.2.3.post1` still goes to `1.2.4`. The epoch survives; pre, dev, post and local
  segments are dropped. Full table in `docs/pyproject-reference.md`.

### Changed

- **`release` refuses a non-canonical spelling and names the canonical one.** `packaging` accepts
  more spellings than it round-trips: `v1.0.0` parses and normalises to `1.0.0`, `1.0.0-beta` to
  `1.0.0b0`. Accepting the raw string would have tagged `vv1.0.0` (the tag is built as
  `f"v{version}"`) and, for the respelled ones, made the git tag disagree with the artifact
  hatchling uploads. A local version (`1.2.3+local`) is refused too, because PyPI rejects it on
  upload - previously it would have tagged cleanly and died in CI. Each refusal prints the fix.

- **The plugin-version sync orders with PEP 440 instead of a three-part regex.** A manifest version
  the old regex could not read (`1.0`, `2026.07.30-1`) was dropped on the floor and the sync
  skipped, which is the exact silent-skill-drift this feature exists to prevent; those now compare
  correctly. A non-final PACKAGE version is still not written into `.claude-plugin/plugin.json`:
  ordering it is no longer the problem, but that manifest is read by Claude Code's marketplace
  machinery and is only ever seen carrying a plain `X.Y.Z`.

## [3.14.0] 2026-07-30 17:37:50

### Added

- **A shipped skill's plugin version now follows the package version, and never moves backward.**
  A repo that ships a Claude Code skill publishes it through its own marketplace, and an install
  re-fetches only when `.claude-plugin/plugin.json` changes version - so a release that edits
  `skills/` without moving that version ships the code and leaves every install on the old skill,
  silently. `sync_plugin_version` raises the plugin version to the package version wherever it lags,
  alongside the existing `__init__conf__.py` and Makefile sync, and refuses to lower it: a skill
  legitimately ships more often than the package it documents, so the plugin version can be
  legitimately ahead, and writing the package version there unconditionally would move an install
  BACKWARD to a version it already had. Measured across seven bitranox repos that ship a skill, two
  were in exactly that state. A version that is not a plain `X.Y.Z` on either side is left alone
  rather than ordered by guesswork.
- **`release` refuses to ship a skill edit the installs would never fetch.** The sync covers every
  case but one: when the package and plugin versions are already equal there is nothing to raise, so
  the edit would ship unannounced. `shipped_skill_needs_a_bump` stops the release there, naming the
  changed files and the version that did not move. It stays silent where there is nothing to judge -
  no plugin manifest, no `skills/` directory, no git, no previous tag, or an untouched skill - so it
  cannot block a repo it does not concern.

### Changed

- Dependency floors raised to the current releases of `lib_cli_exit_tools` and `hypothesis`.
- The bundled `devops-bmk` skill carries the `.sh` shell-lint gate's actual settings (`shfmt -i 4
  -ci`, `bashate --max-line-length 120`, and that bashate reads no config file) and the pre-3.13.2
  nested-worktree file discovery. Both had been written into the bitranox-skills mirror only.

## [3.13.2] 2026-07-28 14:49:10

### Fixed
- **The shell-lint stage no longer crosses into a nested git checkout.** `find_sh_files`
  walked the whole project directory excluding only `.venv*`, `node_modules` and `.git`, so a
  git worktree living inside the project (for example `.claude/worktrees/<branch>/`, a path a
  project's own `.gitignore` typically ignores) had ANOTHER branch's shell scripts linted as
  part of this branch's gate. A project could then stay red over a file it had already fixed,
  pointing at a path that is not its source, with no way to exclude it. Any directory that is
  its own checkout is now skipped: a `.git` directory for a clone or submodule, a `.git` file
  for a linked worktree. The project root's own `.git` is never treated as a nested checkout,
  whether the project is a normal clone or is itself checked out as a worktree.

## [3.13.1] 2026-07-24 18:24:00

### Fixed
- **PLR0917 (too many positional arguments) on the three Click command callbacks and one
  internal helper.** `cli_config_deploy`, `cli_send_email`, and `cli_send_notification` now
  take their options keyword-only (a bare `*,` after `ctx`) - Click already invokes them with
  `f(ctx, **ctx.params)`, so this is a no-op for callers. `_execute_deploy` (an internal
  helper, not a Click callback) got the same treatment plus its one call site updated to pass
  everything by keyword.

### Changed
- **Removed the blanket `[tool.ruff.lint].ignore` list** (`RUF002`, `RUF022`, `PLC0415`,
  `TC001`-`TC003`, `TC006`). Ruff 0.16 surfaced ~400 real findings once the ignores came off;
  fixed each at the root instead of re-suppressing:
  - `RUF022`/`TC001`-`TC003`/`TC006`/`I`: mechanical autofix (import sorting, moving
    type-only imports into `TYPE_CHECKING`, quoting `cast()` expressions) across `src` and
    `tests`.
  - Added `[tool.ruff.lint.flake8-type-checking].runtime-evaluated-base-classes =
    ["pydantic.BaseModel"]` so the TC00x autofix never moves a Pydantic field-type import
    into `TYPE_CHECKING` (Pydantic resolves those at runtime).
  - `PLC0415` (import not at top-level): moved trivial stdlib deferrals (`os`, `sys`,
    `pathlib.Path`) to the module top; kept genuine lazy/circular-import cases with a narrow
    `# noqa: PLC0415` and a one-line reason (CLI command registration staying import-light,
    breaking a documented stagerunner import cycle, skipping the `dotenv` import when
    `CODECOV_TOKEN` is already set, keeping test-only in-memory adapters out of production
    imports). Added `PLC0415` to the `tests/*.py` per-file-ignore: several tests defer
    imports on purpose to exercise import/cache behaviour.
  - Added `PLR0917` to the `tests/*.py` per-file-ignore: five `test_helper_dependencies.py`
    tests stack four `@patch` decorators, which inject mocks positionally in decorator
    (bottom-up) order - they cannot be made keyword-only without breaking the injection.
  - Cleared stray executable bits on 146 test files (an artifact of the softdev ZFS/SMB
    mount; git already stored them as `100644`, so this never affected CI - only local
    `ruff check` via `EXE002`).

## [3.13.0] 2026-07-20 14:46:40

### Fixed
- **The Makefile no longer rebuilds bmk's shared environment before every target.** bmk's env lives
  in uv's machine-wide tool dir, and `_ensure_bmk` ran `uv tool install --reinstall --force` on
  every single make, which tore that env down and rebuilt it in place. Any bmk already RUNNING out
  of it, in any other repo, lost its `site-packages` mid-run. The symptom was an ImportError inside
  bmk's own dependencies rather than in project code (a vanished `pip_api._hash`, a half-written
  pyright typeshed emitting diagnostics against the CPython stdlib), and because a later run
  repaired the env, it cleared by itself and read as a flake. The common path is now
  `uv tool upgrade bmk`, which leaves the environment byte-identical when bmk is already current
  ("Nothing to upgrade", measured at ~0.9s with directory mtimes unchanged), so the destructive
  window shrinks from every make to an actual version change.

### Changed
- **`--refresh-package bmk` and the `UV_OFFLINE` carve-out are gone.** They existed because
  `uv tool install` re-resolves against uv's cached index, so a release published minutes ago
  stayed invisible. `uv tool upgrade` revalidates the index on every run with no freshness window
  and rejects `--refresh` outright (exit 2); offline it answers "Nothing to upgrade" cleanly.

### Added
- **`bmk_selfcheck`, a stdlib-only integrity check for bmk's own environment.** Rebuilding the env
  on every make also repaired a damaged one as a side effect; upgrading does not, so that repair is
  now deliberate. The Makefile runs `python -m bmk_selfcheck` before the upgrade: it compares every
  installed distribution's `RECORD` against the filesystem and exits non-zero if a package was only
  partially written, which is how uv's copy fallback on a mount it cannot hardlink across has left
  `pip_api._hash` and `pydantic.functional_serializers` missing. That flavour does not clear on a
  re-run. A miss falls through to the full reinstall, and an absent env stays quiet so a first-ever
  make does not report an error before the install that fixes it. Net cost is still below the old
  recipe: ~1.15s against ~2s of unconditional teardown. It is a top-level module rather than
  `bmk._selfcheck` so that `-m` does not execute `bmk/__init__.py` first, and it deliberately is
  not an import probe: `bmk --version` costs 1.3s, more than the upgrade it guards, and never
  imports `pip_api`.

## [3.12.2] 2026-07-20 14:04:50

### Fixed
- **PSScriptAnalyzer no longer lints vendored `.ps1` files inside the project venv.**
  `find_ps1_files` excluded `.venv` and `node_modules`, but the scan itself was handed the project
  ROOT with `-Recurse`, so it re-walked the whole tree and undid every exclusion. Discovery was
  therefore only a "run at all?" gate: a repo holding one real script plus an in-tree `.venv` linted
  the npm wrappers that ship inside `pyright[nodejs]`. The scan now receives exactly the discovered
  file list and no longer recurses. This was invisible in CI, which builds its venv outside the
  repository, so no vendored script was ever in range - it only ever hit local runs.
- **A violation count of exactly 256 no longer reports success.** The helper exits with the number
  of violations, and a POSIX exit status is taken mod 256, so 256 findings wrapped to 0. The count
  is now capped at 255.
- **The Quickstart notebook's CI job now actually gates.** CI executes the notebook with
  `allow_errors=False`, which only catches exceptions raised in the kernel - `!cmd` goes through
  IPython's `system()` and never raises, so a broken command printed its error and the run stayed
  green. IPython also records only the last `!` per cell in `_exit_code`, so an earlier failure was
  erased outright. That is how a `bmk hello` invoking a nonexistent command survived in the
  notebook. Every `!` is now followed by an assertion on its exit status, stating whether the
  command must succeed or (for the `bmk fail` traceback demos) must exit 1.

## [3.12.0] 2026-07-20 12:12:14

### Fixed
- **Email delivery works against `btx_lib_mail` 1.5.0.** The dependency floor moves to `>=1.5.0`,
  which is where `ConfMail.smtp_password` became a `SecretStr` (1.4.0) and delivery moved to RFC 3030
  BDAT framing (1.5.0). Production code already fed the new contract correctly; the scheduled CI run
  went red on tests pinned to the old one.
- **`test-all` cells now resolve their own venv's console scripts.** Each cell spawned pytest and
  pyright with the ambient environment, so no venv `bin/` was ever on `PATH`: a project whose tests
  shell out to a console script (`ruff`, `pip-audit`) failed under `test-all` while passing under
  `test`, whose pytest runs with the stage runner's env. Each cell is now pinned at its own venv
  (`PATH`, `VIRTUAL_ENV`, `PIPAPI_PYTHON_LOCATION`), which also makes the matrix per-version in
  earnest - every interpreter resolves the tools installed for it.
- **A failing `test-all` cell reports the cause.** The per-cell detail was a plain tail of the
  output, and because the suite logs to stderr the real `FAILED` summary had already scrolled past,
  so a genuine failure printed as `no output captured`. Verdict lines are now hoisted above the tail.

### Added
- **`send_email` / `send_notification` accept a `transport` delivery seam**, forwarded to
  `btx_lib_mail`. Passing `None` (the default) keeps the library's own SMTP transport, so existing
  callers are unaffected. Delivery tests now inject a recording double through this seam instead of
  monkeypatching `smtplib.SMTP`, which pinned the library's private wire protocol and is what broke.

## [3.11.2] 2026-07-19 14:07:59

### Fixed
- **`config-deploy` no longer crashes on a legacy Windows console codepage (cp1252).** It printed a
  Unicode checkmark per deployed path, which raised `UnicodeEncodeError` and exited 1 even though the
  files had already been written, misreporting a successful deploy as a failure. It now prints a
  plain ASCII marker.
- **Venv provisioning no longer inherits a foreign `VIRTUAL_ENV`.** When an unrelated venv (an IDE's,
  say) was active, uv printed `VIRTUAL_ENV=... does not match the project environment path ... and
  will be ignored` on every provisioning call. Provisioning now runs with `VIRTUAL_ENV` stripped; bmk
  already targets the venv explicitly, so nothing else changes.
- **Quickstart notebook installs its package with uv**, so a fresh CI kernel can import it.

### Changed
- The CI pytest marker exclusion is now configurable via the distributed CI template.
- `devops-bmk` skill: Windows `make install` uses winget instead of choco, and `make release` skips
  the GitHub step cleanly when `gh` is not on PATH.

## [3.11.1] 2026-07-16 18:40:48

### Security
- **PowerShell command injection via `pyproject.toml` closed.** `_psscriptanalyzer.py` was the one
  place that built a `pwsh -Command` string instead of an argv list, and it interpolated
  `[tool.psscriptanalyzer].exclude-rules` and the project path unescaped. A hostile `pyproject.toml`
  (a reviewed PR branch, a cloned repo) could run arbitrary PowerShell during a plain `bmk test`
  when pwsh and a `.ps1` file were present. Fixed at two layers: the config boundary now drops any
  rule id that is not `^PS[A-Za-z0-9]+$`, and the path and rules are PowerShell-escaped
  (single-quoted with doubled quotes; rules emitted as a quoted array, or omitted when empty).

### Fixed
- **Perpetual venv rebuild on hosts with a non-CPython interpreter.** `latest_installed_patch` took
  the highest patch across all implementations, but bmk only ever provisions CPython. With PyPy (or
  another impl) installed for the same `X.Y` at an equal-or-higher patch, the reported "newest"
  never matched the CPython venv, so `test`/`push`/`cov`/`deps`/`bld` rebuilt it on every run. It now
  filters to CPython.
- **Unattributed, interleaved `--human` output.** Concurrent stages in a batch streamed to the same
  stream and tore each other's lines mid-write with no way to tell which tool a line came from.
  Text-mode concurrent batches now use a lock-guarded, `[stage]`-prefixed sink, so lines stay whole
  and attributed. JSON mode is unchanged.
- **PyPI metadata fetch is now streamed with a size cap**, so a broken or hostile endpoint cannot
  make bmk buffer an unbounded body into memory.

### Changed
- **Missing email configuration now exits `78` (`CONFIG_ERROR`), not `2`.** A missing `from_address`
  or missing recipients raised `ValueError` (mapped to exit 2, an argument error) while missing SMTP
  hosts already raised `ConfigurationError` (exit 78). All three now raise `ConfigurationError` for
  a consistent diagnosis; a malformed recipient override still raises the argument-level error.
- **`--smtp-password` help discourages the flag** in favour of the `BMK___EMAIL__SMTP_PASSWORD` env
  var or a `.env` file (a CLI password is visible in the process list and shell history).
- **Strict data-architecture pass (internal).** `output_format` is typed `ToolOutputFormat` end to
  end in the shell/PSScriptAnalyzer/coverage helpers; a `ToolName` enum centralises the ensure and
  prerequisite tool vocabulary; a `BumpPart` enum types the version-bump part; `ToolOutputFormat.from_env`
  is the single `BMK_OUTPUT_FORMAT` decoder; `uv python list` and `gh run list` JSON are parsed into
  Pydantic models; the in-memory `EmailSpy` records are typed dataclasses; and `custom` reads
  `[tool.bmk]` settings via dotted `config.get` instead of dumping the whole config.

### Added
- **Root dev `Makefile` gains `test-all` and `clean-all`**, mirroring the template Makefile so
  `make test-all` (per-version matrix) and `make clean-all` (purge every `.venv*`) work here too.
- **Expanded test coverage** for the injection defences, `ship` orchestration and CI gate, the
  config-deploy return path, the new Pydantic models' malformed-entry skip paths, `test-all` CLI
  dispatch, and previously untested `_toml_config` / `PoetryDepSpec` / `_sync_initconf` branches.

## [3.11.0] 2026-07-16 14:34:33

### Added
- **`make test-all`: run the suite and type-check on EVERY declared Python version, in parallel.**
  `make test` gates against one venv - the newest declared Python. CI runs the whole matrix, but
  there was no way to reproduce it locally, so a break that only shows on 3.10 stayed invisible
  until CI. `test-all` provisions one `.venv-<minor>` per `Programming Language :: Python :: X.Y`
  classifier (by minor, not patch - the dir stays stable while uv auto-follows patch upgrades),
  runs `pytest` and `pyright --pythonpath <that venv>` in each concurrently, and reports per
  version with the actual patch it ran on:

  ```
  test-all:
    3.10     3.10.20   PASS
    3.14     3.14.5    PASS
  ```

  Only pytest and pyright are repeated - they are the version-sensitive gates (pyright's typeshed
  has per-version conditionals); ruff/bandit are AST-only and pip-audit is env-based, so running
  them per version buys nothing. A version whose venv cannot be provisioned (a dep dropped that
  Python) is reported ERROR, distinct from a test FAIL; any non-PASS fails the run, and every
  version still runs. With no `:: Python :: X.Y` classifier, `test-all` tests the default
  interpreter once and prints a WARNING naming the version so a green run is not mistaken for
  full-matrix coverage. `make test` is unchanged (newest version, under coverage). The same
  classifiers already drive CI's matrix, so local and CI cannot disagree about the supported set.

- **`make clean-all`: everything `clean` removes, plus every `.venv*`.** Plain `clean` keeps the
  venvs on purpose (deleting one forces a full re-resolve on the next command). `clean-all` is the
  explicit "remove it all" - the whole matrix (`.venv-3.10` .. `.venv-3.14`) plus `.venv` and
  `.venv-bmk` - for reclaiming disk or forcing a from-scratch rebuild.

### Changed
- **The venv `.gitignore` entry is now a single `.venv*` glob** instead of listing `.venv`,
  `.venv-win`, `.venv-bmk` individually. One glob covers those and every `.venv-<minor>` the matrix
  creates, so no per-version line is ever needed. An existing rule (however spelled) is respected;
  a repo with only the old literal `.venv/` gains the glob so its matrix venvs are covered too.

### Fixed
- **A new Python patch no longer rebuilds every venv for nothing.** 3.10.0 decided whether the
  venv was current by reading `pyvenv.cfg`'s `version_info`. That text is written once, at
  creation, and then goes stale - so it reported a mismatch against a venv uv had *already*
  upgraded, and forced a full re-resolve in every repo on every patch release.

  uv builds a venv against the MINOR alias (`.../cpython-3.12-linux.../bin`), so
  `uv python upgrade 3.12` migrates existing venvs onto the new patch just by repointing what
  that alias resolves to. Measured, both halves:

  ```
  venv on the 3.12 alias  -> pyvenv.cfg 3.12.12, interpreter 3.12.12
  uv python upgrade 3.12  -> installs 3.12.13, repoints the alias
  same venv, untouched    -> pyvenv.cfg 3.12.12, interpreter 3.12.13
  ```

  `venv_version` now asks the interpreter (`sys.version_info`) instead of trusting the text, so
  it sees 3.12.13 and leaves the venv alone. One subprocess, true in both directions.

  This also inverts the cost of the feature, in your favour: because `upgrade` migrates
  alias-built venvs by itself, **a new patch needs no rebuild at all** - the venv is already on
  it. Only a MINOR change (a classifier moving 3.14 -> 3.15) still forces one, which is the case
  that genuinely cannot be done in place.

## [3.10.0] 2026-07-16 00:49:30

### Added
- **The project venv is built on the newest Python your project declares, at its latest patch.**
  bmk read no version at all: it ran a bare `uv venv`, so uv used whatever interpreter it happened
  to prefer. In practice that is a uv-managed install refreshed only when someone remembers to,
  which is how a whole machine ends up with every venv on 3.14.0 while 3.14.5 is a download away.

  The version comes from the **`Programming Language :: Python :: X.Y` classifiers** - the highest
  one, compared numerically (`3.14` beats `3.9`; a lexical sort inverts that). Dotted entries only,
  so the conventional bare `:: Python :: 3` is skipped.

  `requires-python` deliberately does NOT decide this. It is a floor: `>=3.10` says nothing about
  the newest version you support. The classifiers are where a project states that, and the CI
  workflow already builds its test matrix from exactly those entries - so reading the same key
  keeps your venv and your CI matrix agreeing about "newest supported" instead of drifting apart.
  Declare no `:: Python :: X.Y` and bmk chooses nothing: uv's own default stands, unchanged.

  Before a command that touches the environment, bmk runs `uv python install <X.Y>` **and**
  `uv python upgrade <X.Y>`. Both are needed and neither substitutes for the other: `install`
  fetches a minor just added to the classifiers, while `upgrade` is the only one that moves an
  already-installed minor onto a newer patch - given an installed 3.14.0, `install` reports
  "Installed Python 3.14.0" and keeps the stale one. Current and offline, the pair costs ~0.1s.

  A venv built on a different version is **rebuilt**, because an interpreter cannot be upgraded in
  place. The path never changes, so the pins derived from it stay valid, and it happens before
  `build_context` freezes them. It fires only on a real mismatch against a target uv actually
  reports: if uv cannot answer (offline with the version absent, uv missing), the existing venv is
  left exactly as it is. A rebuild costs a full re-resolve and must never run on a guess.

  Expect one rebuild per repo the first time this runs, wherever the venv is behind.

  Documented in `docs/pyproject-reference.md`, the `devops-bmk` skill, and `CLAUDE.md`.

## [3.9.1] 2026-07-16 00:13:38

### Fixed
- **`pyright` is now pinned at the project's interpreter, like every other gate.** It ran as a
  bare `pyright`, and pyright does NOT honour `VIRTUAL_ENV` (verified against pyright 1.1.x):
  with no `--pythonpath` it resolves an interpreter from PATH, and `_prepend_tool_bin_to_path`
  puts bmk's OWN tool bin first. So `make test` type-checked every project against bmk's
  environment rather than the one the project declares - the exact defect `_test_python_flags`
  was written to keep out of the pytest stage, which bmk's own comments call "the defect (tests
  running against a tree the project never declared)".

  It hid almost perfectly. bmk's env carries bmk's dependencies (pydantic, rich-click, orjson,
  lib_layered_config, ...), which overlap what most projects import, so repo after repo passed
  by luck. Only a project importing something bmk lacks sees it, and then not as a missing
  import but as strict-mode `reportUnknown*` errors, because the package's types are simply not
  there. Measured on such a repo: **7 phantom errors before the pin, 0 after**, with no change
  to the code being checked.

  `--pythonpath` is omitted when no project venv resolves, which leaves pyright's own PATH
  discovery - no worse than before. In CI the resolver returns the CI venv, so the gate keeps
  checking exactly what CI installs.

  pytest, the integration pytest and pip-audit were already pinned; ruff, bandit and
  import-linter need no interpreter (they never resolve imports from site-packages). pyright was
  the only gap.

## [3.9.0] 2026-07-15 22:27:01

### Security
- **`EmailConfig` no longer leaks the SMTP password on any export path.** Only `__repr__` was
  redacted, while its own docstring promised protection for "logs, error messages, and debugging
  output". Verified live: `str(config)`, `f"{config}"`, `logger.error("%s", config)`,
  `model_dump()` and `model_dump_json()` all emitted the plaintext password. `f"{config}"` and
  `%s`-logging are the most natural ways anyone logs an object, so this was one debug line away
  from a credential in a log file. Redaction now happens in a `field_serializer` plus `__str__`,
  which closes every export path at once.

  A caller that round-trips the dump back into an `EmailConfig` must opt out explicitly with
  `model_dump(context={REVEAL_SECRETS: True})` - `apply_validated_overrides` dumps and
  re-validates, so a blanket redaction would have re-validated `"[REDACTED]"` as the real
  password and broken SMTP auth with a credential that looks plausible in a log. That is the
  only place the opt-out is used, and it is covered by a test.

  The gap survived because the one test that existed pinned `repr()` - the single path that
  already worked. There is now a test per leaking path.

### Fixed
- **A failed tool run no longer leaves the tool running.** `run_argv` is the path every tool,
  git and pip-audit call takes. It reads the child's output with `text=True`, which decodes
  strictly, so a tool emitting one undecodable byte raises `UnicodeDecodeError` mid-stream. The
  `finally` only unregistered the signal handler, so the stage failed while the child kept
  running, orphaned and unreaped. It is now killed and reaped on that path (a no-op on the
  normal one). Reachable in practice wherever a tool's output is not valid UTF-8.
- **Non-ASCII characters no longer reach the console.** Several user-facing strings carried
  em-dashes, which raise `UnicodeEncodeError` on a Windows console under cp1252 when output is
  redirected - in a tool whose whole premise is cross-OS, and next to a helper already commented
  "ASCII-safe for Windows compatibility".

### Changed
- **The pyproject readers parse with Pydantic, so each default exists in exactly one place.**
  The hand-rolled readers declared every default twice (once on the dataclass field, once in the
  getter), which is how the `-vv`/`-v` verbosity default drifted apart. `_coverage.py` was primed
  for the identical bug with six twice-declared defaults. Behaviour-preserving: the parser's
  output was diffed byte-identical against real pyprojects, and the never-raise contract is
  re-tested with a missing file, garbage TOML and wrong-typed values.
- **`DependencyInfo.status` is a `DependencyStatus` enum** rather than a `str` whose five legal
  values lived only in a trailing comment and were compared as bare literals at a dozen sites. It
  subclasses `str`, so the wire format and the report tables are unchanged.
- `ship_cmd` raises `ExitCode.GENERAL_ERROR` instead of a bare `SystemExit(1)`. The two engine
  helpers keep their bare literal on purpose: `ExitCode` lives in the CLI layer, and `cli`
  imports `stagerunner` and never the reverse, so importing it there would couple the engine to
  the CLI to spell the same integer.
- `is_windows()` / `is_macos()` are defined once in `_prerequisites.py` instead of being
  duplicated verbatim across two modules.

### Documentation
- **`DEVELOPMENT.md` rewritten against the code.** It documented a pre-3.0.0 bmk: env vars that
  do not exist (`SKIP_BOOTSTRAP`, `TEST_VERBOSE`, `COVERAGE`, `PY`, `PIP`), a `menu` and
  `test-slow` target that do not exist, `scripts/build.py` and `scripts/release.py` in a
  `scripts/` directory that does not exist, and the wrong CI workflow filenames. It now lists
  only the variables bmk actually reads, and states plainly that `make test` **writes to your
  working tree before checking it** (it applies ruff fixes and bumps dependency floors), which
  was never documented.
- `INSTALL.md` no longer shows `uv tool install --reinstall bmk --with .` as the command the
  Makefile runs. It contradicted both the real command and the paragraph twenty lines above it,
  which tells you never to add `--with .`.
- `docs/pipelines.md` dropped two stale version floors and stopped calling bmk's toolchain "dev
  dependencies" - bmk ships no `[dev]` extra by design, because the tools are the product.
- `docs/make-targets.md` documents `ship`/`sh`, which existed but was listed nowhere.

## [3.8.2] 2026-07-15 19:54:07

### Removed
- **Two dead dependencies, and 22 packages with them: 95 -> 73.** Both were declared and
  never used, in an environment every repo installs.

  `textual` was the orphan of `scripts/menu.py`, a 637-line TUI deleted in the 3.0.0 rewrite;
  the dependency was never pruned. Its only remaining trace was a string in a test fixture.
  `make menu` is gone from the docs with it - it was documented in four places and had no
  target, no command and no module behind it.

  `twine` was never invoked at any point in bmk's history (`git log -S twine` over `src/`
  finds nothing). bmk does not upload to PyPI itself: `release` tags, pushes and calls
  `gh release`, and the publish is `pypa/gh-action-pypi-publish` in the release workflow.

  Removing twine also removed `keyring` and the `jaraco-*` chain, which is why the
  `jaraco-context` CVE floor went too: that package only ever reached the tree via
  twine -> keyring. A floor in `[project].dependencies` INSTALLS a package rather than merely
  bounding it, so leaving it would have dragged jaraco-context back in to guard nothing. The
  `urllib3` floor stays - pip-audit genuinely pulls it - and its comment no longer credits
  twine or the disabled codecov-cli.

### Changed
- **`[project].dependencies` is now grouped by WHY each dep is there**: imported by bmk,
  invoked as a tool but never imported, present on purpose though neither, or deliberately
  absent. An undifferentiated list is how both dead entries hid: most of bmk's dependencies
  are tools it shells out to, so an import scan calls the whole toolchain unused and no one
  trusts the result. The awkward cases are now stated where they are read - `click` is both
  imported and a CVE floor, `hatchling` is duplicated from `[build-system]` so that pip-audit
  (which audits the project venv, not build's ephemeral one) can see it, `pytest-cov` is a
  plugin rather than an executable, and `import-linter`/`shellcheck-py`/`shfmt-py` ship
  executables under different names.
- `docs/systemdesign/module_reference.md` regenerated to the architecture-only template.
  It was a file index - every path, exit code and CLI option - which duplicates what the code
  already states and therefore rots: it declared itself "Complete (v1.1.2+)" at v3.8.1, with
  roughly half its paths pointing at files that no longer exist. It now carries the layer
  contract, how a command resolves and runs, and the decisions with their trade-offs, and no
  file paths at all. 371 -> 123 lines.

## [3.8.1] 2026-07-15 18:45:01

### Fixed
- **A new bmk release is now picked up immediately, instead of whenever uv's index cache
  happened to revalidate.** `_ensure_bmk` runs before EVERY target for exactly one reason -
  so `--reinstall` re-resolves and you never run a bmk that has quietly drifted - but
  `--reinstall` re-resolves against uv's CACHED package index, so a release published
  minutes ago was invisible and you silently kept the old bmk. Measured with 3.8.0 already
  on PyPI: `uv tool install "bmk>=3.7.1"` still installed **3.7.1**, and the Makefile's own
  claim that a new release "is picked up automatically" was therefore false for as long as
  the cache stayed warm. The install now refreshes bmk's own index metadata
  (`--refresh-package bmk`), which costs about 1s per make.

  The refresh is skipped when `UV_OFFLINE` is set. That is not politeness: uv REFUSES the
  combination ("the argument `UV_OFFLINE` cannot be used with `--refresh`"), so an
  unconditional flag would have failed every `make` for an offline or air-gapped user, with
  an error blaming an environment variable they never connected to this Makefile - and no
  way to opt out. Offline keeps installing from the cache, which is what an offline user
  wants regardless.

## [3.8.0] 2026-07-15 18:09:41

### Changed
- **bmk's environment now holds bmk alone, and is shared by every repo.** The Makefile no
  longer installs your project into it (`--with-editable ".[dev]"` is gone) and no longer
  builds a `.venv-bmk` per project - bmk goes once into uv's own tool dir. Your
  dependencies live in the project's `.venv`, which bmk already provisions from your
  `pyproject.toml`. See `docs/adr/0002-bmk-env-holds-bmk-alone.md`.

  `--with` made uv resolve bmk and your project as ONE dependency problem, and every
  release since 2.9.0 patched a consequence of that rather than the cause: 3.1.7 test deps
  missing; 3.3.1 the install degrading silently; 3.4.0 two projects overwriting each other;
  3.5.0 `codecov-cli` capping `click<8.3.0` **silently backtracking bmk itself to 3.1.7**;
  3.6.0 pyright walking the co-resolved site-packages for **6h20m across 21 repos**; 3.6.1
  a **yanked** transitive floor making bmk uninstallable and bricking `make` fleet-wide.
  With none of your packages in bmk's env, that entire class is gone: nothing of yours can
  cap, backtrack or break bmk's install. `BMK_MIN` is kept as inert insurance.

  It also removes an undocumented **cycle**: bmk depends on `lib_cli_exit_tools`,
  `lib_log_rich`, `lib_layered_config` and `btx_lib_mail`, which are themselves bmk-managed
  repos - so their `make` resolved bmk against the very library being developed. bmk
  requires `lib_layered_config>=5.6.0` and the working copy is 5.6.0: one floor bump above
  the dev version and that repo could not `make test` at all.

  And it stops ~300MB (mostly pyright's bundled Node) being duplicated into every repo: one
  shared env instead of ~46. `pyright[nodejs]` therefore stays - paid once, and bmk's
  toolchain needs no system Node.

  **Migration is automatic** (the Makefile regenerates itself), with one requirement your
  project almost certainly already meets: declare `pytest` and `pytest-cov` in its `[dev]`
  extra, since the suite now runs in your venv. A leftover `.venv-bmk` is disposable and
  gitignored - delete it.

  bmk's own development Makefile deliberately keeps a per-project env: it installs bmk from
  local source, and sharing that would make every other repo run bmk out of a working tree.

### Fixed
- **The tests ran in the wrong environment, and no gate could see it.** `python_cmd` was
  always `sys.executable`, so pytest ran in bmk's env while pyright (`VIRTUAL_ENV`) and
  pip-audit (`PIPAPI_PYTHON_LOCATION`) inspected the project's `.venv` - two independently
  resolved trees, so the suite and the audit described different environments. They differ
  in practice: the project venv gets every extra, bmk's env only ever got `[dev]`. A real
  bug hid in exactly that gap - a project's `[full]` extra was present in `.venv` and absent
  from bmk's env, so 16 tests took a different branch depending on which env ran them,
  invisible to both `make test` and CI.

  `resolve_test_python` (mirroring the existing `resolve_audit_python`) now resolves the
  project's interpreter when the stage runs, and `_coverage.py` takes it as `--python`
  instead of using `sys.executable`; the integration stage no longer runs a bare `pytest`
  off PATH. It deliberately never falls back to bmk's interpreter - a silent fallback is
  the defect itself - so with no project venv it fails and names the fix.

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
