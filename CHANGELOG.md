# Changelog

All notable changes to this project will be documented in this file following
the [Keep a Changelog](https://keepachangelog.com/) format.


## [Unreleased]

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
- **Makefile recipe override warning**: `make push test parameters` no longer warns about overriding the `test` target recipe — extra arguments that collide with existing target names are now skipped in the no-op eval

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
- Custom `_PROFILE_PATTERN` regex — replaced by lib_layered_config's built-in validation

## [1.2.0] - 2026-01-30

### Added
- **Attachment security settings** for email configuration (`[email.attachments]` section in `50-mail.toml`)
  - `allowed_extensions` / `blocked_extensions` — whitelist/blacklist file extensions
  - `allowed_directories` / `blocked_directories` — whitelist/blacklist attachment source directories
  - `max_size_bytes` — maximum attachment file size (default 25 MiB, 0 to disable)
  - `allow_symlinks` — whether symbolic links are permitted (default false)
  - `raise_on_security_violation` — raise or skip on violations (default true)
- New `EmailConfig` fields for attachment security with Pydantic validators
- `load_email_config_from_dict()` now flattens nested `[email.attachments]` section

### Changed
- Bumped `btx_lib_mail` dependency from `>=1.2.1` to `>=1.3.0` for attachment security features

## [1.1.2] - 2026-01-28

### Fixed
- Coverage SQLite "database is locked" errors on Python 3.14 free-threaded builds and network mounts (SMB/NFS)
- Removed bogus `COVERAGE_NO_SQL=1` environment variable from `scripts/test.py` (not a real coverage.py setting)
- CI workflow now sets `COVERAGE_FILE` to `runner.temp` so coverage always writes to local disk
- **Import-linter was a silent no-op** in `make test` / `make push` — `python -m importlinter.cli lint` silently exits 0 without checking; replaced with `lint-imports` (the working console entry point)
- CI/local parameter mismatches: ruff now targets `.` (not hardcoded `src tests notebooks`), pytest uses `python -m pytest` with `--cov=src/$PACKAGE_MODULE`, `--cov-fail-under=90`, and `-vv` matching local runs
- `scripts/test.py` bandit source path now reads `src-path` from `[tool.scripts.test]` instead of hardcoding `Path("src")`
- `scripts/test.py` module-level `_default_env` now rebuilt with configured `src_path` before running checks
- `run_slow_tests()` now reads pytest verbosity from `[tool.scripts.test].pytest-verbosity` instead of hardcoding `"-vv"`

### Changed
- **pyproject.toml as single source of truth**: CI workflow extracts all tool configuration (src-path, pytest-verbosity, coverage-report-file, fail_under, bandit skips) from `pyproject.toml` via metadata step — workflow is portable across projects without editing
- `scripts/test.py` removed module-level `PACKAGE_SRC` constant; bandit source path computed from `config.src_path` inside the functions that need it
- `make push` now accepts an unquoted message as trailing words (e.g. `make push fix typo in readme`); commit message format is `<version> - <message>`, defaulting to `<version> - chores` when no message is given
- Removed interactive commit-message prompt from `push.py` — message is either provided via CLI args / `COMMIT_MESSAGE` env var, or defaults to `"chores"`

### Added
- `pytest_configure` hook in `tests/conftest.py` that redirects coverage data to `tempfile.gettempdir()` and purges stale SQLite journal files before each run

## [1.1.1] - 2026-01-28

### Fixed
- CLAUDE.md: replaced stale package name `bitranox_template_cli_app_config_log_mail` with `bmk` throughout
- Brittle SMTP mock assertions in `test_cli.py` now use structured `call_args` attributes instead of `str()` coercion
- Stale docstring in `__init__conf__.py` claiming "adapters/platform layer" — corrected to "Package-level metadata module"
- Weak OR assertion in `test_cli.py` for SMTP host display — replaced with two independent assertions
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
- **ARCHITECTURE**: Purified domain layer — `emit_greeting()` renamed to `build_greeting()` (returns `str`, no I/O); decoupled `display.py` from Click
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
