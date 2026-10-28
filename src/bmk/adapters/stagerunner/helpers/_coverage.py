"""Coverage file management, test execution, and Codecov upload helpers.

Purpose
-------
Isolate everything related to cleaning coverage artefacts, running tests with
coverage, resolving git metadata for Codecov, and uploading coverage reports.

Contents
--------
* ``prune_coverage_data_files`` / ``remove_report_artifacts`` -- housekeeping
  before and after coverage runs.
* ``run_coverage_tests`` -- run pytest under coverage and generate reports.
* ``ensure_codecov_token`` -- discovers ``CODECOV_TOKEN`` from the environment
  or ``.env`` file and returns it without mutating global state.
* ``upload_coverage_report`` -- drives the official Codecov CLI uploader.
* Git resolution helpers (commit SHA, branch, service).
* ``main`` -- entry point for standalone execution.

System Role
-----------
Run as a subprocess by the ``pytest`` and ``coverage`` stages
(``tools.pytest_cov_argv`` / ``tools.coverage_run_argv``), under bmk's interpreter; the
suite itself runs under the project's.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, NamedTuple

import rtoml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from bmk.adapters.stagerunner.helpers._parallel import (
    AUTO,
    ParallelProbe,
    ParallelSupport,
    PytestPlugins,
    marker_args,
    normalise_workers,
    probe_parallel,
    resolve_test_workers,
    xdist_args,
)
from bmk.adapters.stagerunner.helpers._toml_config import coerce_table, describe_validation_error
from bmk.domain.enums import ToolOutputFormat
from bmk.domain.errors import RefusalError

__all__ = [
    "WorkerPlan",
    "build_codecov_args",
    "build_codecov_env",
    "build_env",
    "check_codecov_prerequisites",
    "ensure_codecov_token",
    "find_dotenv_upward",
    "get_repo_metadata_from_git",
    "handle_codecov_result",
    "main",
    "plan_test_workers",
    "prune_coverage_data_files",
    "remove_report_artifacts",
    "resolve_commit_sha",
    "resolve_git_branch",
    "resolve_git_service",
    "run_coverage_tests",
    "upload_coverage_report",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# The single source for the coverage report filename default. CoverageConfig's
# Field default and every other function default (remove_report_artifacts,
# upload_coverage_report) point at this constant so the value exists exactly
# once - this is the name that already drifted once (see CoverageConfig below).
DEFAULT_COVERAGE_REPORT_FILE = "coverage.xml"


class CoverageConfig(BaseModel):
    """Configuration for coverage runs loaded from pyproject.toml.

    A Pydantic model (not a dataclass) so each default is declared exactly once,
    as a Field default here - never duplicated in a second reader. The previous
    dataclass version hardcoded these same six defaults again in the "no
    pyproject.toml" early return, and that second copy is exactly how a prior
    version shipped a live drift bug (a "-vv" default in one reader while the
    other used "-v"). model_construct is not used here: this model marshals
    directly from parsed TOML, an external boundary, so full validation applies.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    # Aliases are the hyphenated [tool.scripts.test] / [tool.coverage.run] TOML
    # keys; field names stay underscored Python. fail_under keeps its TOML name
    # unchanged (that key is coverage's own, already underscored, not a typo).
    pytest_verbosity: str = Field(default="-v", alias="pytest-verbosity")
    coverage_report_file: str = Field(default=DEFAULT_COVERAGE_REPORT_FILE, alias="coverage-report-file")
    src_path: str = Field(default="src", alias="src-path")
    fail_under: int = Field(default=80)
    coverage_source: list[str] = Field(default_factory=lambda: ["src"], alias="source")
    exclude_markers: str = Field(default="integration", alias="exclude-markers")
    # "auto" or a count; 1 runs the suite in one process. Only takes effect once the project's
    # venv has pytest-xdist (see _parallel), so the default changes nothing for a project
    # that never declared it.
    workers: Annotated[str, BeforeValidator(normalise_workers)] = Field(default=AUTO)

    @classmethod
    def from_pyproject(cls, project_dir: Path) -> CoverageConfig:
        """Load coverage configuration from pyproject.toml.

        Args:
            project_dir: Directory containing pyproject.toml.

        Returns:
            CoverageConfig with values from pyproject.toml or defaults.
        """
        pyproject_path = project_dir / "pyproject.toml"
        if not pyproject_path.is_file():
            # No second copy of the defaults: the Field defaults above ARE the
            # "file missing" answer.
            return cls()

        # rtoml (not stdlib tomllib) so parsing works on Python 3.10, where
        # tomllib does not exist; rtoml is a declared dependency and fully typed.
        document = _CoveragePyproject.model_validate(rtoml.loads(pyproject_path.read_text(encoding="utf-8")))
        tool = document.tool

        # coverage.py's own keys win over a same-named key in [tool.scripts.test], which
        # the model also accepts (its alias and field names), so only a key coverage.py
        # actually sets replaces it.
        overrides: dict[str, object] = {}
        if tool.coverage.report.fail_under is not None:
            overrides["fail_under"] = tool.coverage.report.fail_under
        if tool.coverage.run.source is not None:
            overrides["coverage_source"] = tool.coverage.run.source
        return tool.scripts.test.model_copy(update=overrides)


# ---------------------------------------------------------------------------
# pyproject.toml boundary models for CoverageConfig
#
# Only the keys from_pyproject reads. A misshapen TABLE degrades to its defaults
# (coerce_table); a misshapen VALUE is refused by validation, so a typo'd fail_under
# fails the run rather than silently gating at the default.
# ---------------------------------------------------------------------------


class _CoverageRunTable(BaseModel):
    """[tool.coverage.run] - the measured source paths."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    # None means absent (TOML has no null), so the CoverageConfig value stands.
    source: list[str] | None = None


class _CoverageReportTable(BaseModel):
    """[tool.coverage.report] - the coverage floor."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    fail_under: int | None = None


class _CoverageTable(BaseModel):
    """[tool.coverage] - the two sub-tables bmk reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    run: Annotated[_CoverageRunTable, BeforeValidator(coerce_table)] = Field(default_factory=_CoverageRunTable)
    report: Annotated[_CoverageReportTable, BeforeValidator(coerce_table)] = Field(default_factory=_CoverageReportTable)


class _ScriptsTable(BaseModel):
    """[tool.scripts] - the runner settings under [tool.scripts.test], hyphenated keys."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    test: Annotated[CoverageConfig, BeforeValidator(coerce_table)] = Field(default_factory=CoverageConfig)


class _CoverageToolTable(BaseModel):
    """[tool] - the two tables CoverageConfig is assembled from."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    scripts: Annotated[_ScriptsTable, BeforeValidator(coerce_table)] = Field(default_factory=_ScriptsTable)
    coverage: Annotated[_CoverageTable, BeforeValidator(coerce_table)] = Field(default_factory=_CoverageTable)


class _CoveragePyproject(BaseModel):
    """The pyproject.toml document, reduced to what CoverageConfig needs."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    tool: Annotated[_CoverageToolTable, BeforeValidator(coerce_table)] = Field(default_factory=_CoverageToolTable)


# ---------------------------------------------------------------------------
# Coverage File Management
# ---------------------------------------------------------------------------


def prune_coverage_data_files(project_dir: Path | None = None) -> None:
    """Delete SQLite coverage data shards to keep the Codecov CLI simple.

    Args:
        project_dir: Directory to search for coverage files. Defaults to cwd.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    for path in project_dir.glob(".coverage*"):
        if path.is_dir() or path.suffix == ".xml":
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"[coverage] warning: unable to remove {path}: {exc}", file=sys.stderr)


def remove_report_artifacts(
    project_dir: Path | None = None,
    coverage_report_file: str = DEFAULT_COVERAGE_REPORT_FILE,
) -> None:
    """Remove coverage reports that might lock the SQLite database on reruns.

    Args:
        project_dir: Directory to search for coverage files. Defaults to cwd.
        coverage_report_file: Name of the coverage report file.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    for name in (coverage_report_file, "codecov.xml"):
        artifact = project_dir / name
        try:
            artifact.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"[coverage] warning: unable to remove {artifact}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Coverage Test Execution
# ---------------------------------------------------------------------------


def build_env(project_dir: Path, src_path: str) -> dict[str, str]:
    """Build environment for subprocess execution.

    Args:
        project_dir: Project root directory.
        src_path: Source path to add to PYTHONPATH.

    Returns:
        Environment dictionary with updated PYTHONPATH.
    """
    pythonpath_parts = [str(project_dir / src_path)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        pythonpath_parts.append(existing)
    pythonpath = os.pathsep.join(pythonpath_parts)
    return os.environ.copy() | {"PYTHONPATH": pythonpath}


class _InterpreterRefusal(NamedTuple):
    """Why there is no interpreter to run the tests under.

    A type of its own rather than an ``(interpreter, error)`` pair, so a caller cannot
    read an interpreter out of a refusal or an error out of a usable interpreter.

    Attributes:
        reason: The explanation printed after ``Cannot run tests:``.
    """

    reason: str


def _resolve_test_interpreter(python: str | None) -> str | _InterpreterRefusal:
    """Validate the interpreter the tests will run under.

    The interpreter must be the PROJECT's venv python, which ``ensure_project_venv``
    syncs from the project's own ``pyproject.toml`` (including its ``[dev]`` extra, so
    pytest and coverage are there).

    This refuses to fall back to ``sys.executable`` (bmk's own interpreter). bmk's env
    and the project's venv are two independently resolved trees - bmk's only ever
    received ``[dev]``, the project's receives every extra - so running the suite in
    bmk's env exercises an environment the project does not declare, while pyright and
    pip-audit inspect the real one. A silent fallback would reinstate exactly that.

    Deliberately checks only that the interpreter EXISTS; it does not probe it for
    coverage/pytest. A probe would add a subprocess to every run to pre-empt a case
    ``ensure_project_venv`` already prevents, and a missing module reports itself
    perfectly well ("No module named coverage") from the command that needs it.

    Args:
        python: The project's venv interpreter, or None when no venv was found.

    Returns:
        The interpreter path, or the refusal explaining why the tests cannot run.
    """
    if not python:
        return _InterpreterRefusal(
            "no project virtualenv found, so there is no environment to run the tests in.\n"
            "bmk runs the suite in the project's own venv (the one it syncs from pyproject.toml),\n"
            "never in its own tool env. Create it with `uv venv` (bmk normally provisions it\n"
            "automatically), or unset BMK_NO_VENV_SYNC=1 if you set it."
        )
    if not Path(python).exists():
        return _InterpreterRefusal(f"the project's interpreter does not exist: {python}")
    return python


@dataclass(frozen=True)
class _CoverageRun:
    """Everything the three coverage steps of one run share.

    Bundled so the steps cannot be handed mismatched pieces: the report and the
    XML step must read the data file the pytest step wrote, which only holds if
    all three see the same interpreter and the same ``COVERAGE_FILE``.

    Attributes:
        python: The project's venv interpreter every step runs under.
        config: Coverage settings read from the project's pyproject.toml.
        env: Subprocess environment, including ``PYTHONPATH`` and ``COVERAGE_FILE``.
        project_dir: Working directory for every step.
        quiet: Suppress the announced command lines and the terminal report.
        workers: The pytest-xdist worker setting the suite runs with; ``"1"`` is serial.
        plugins: What the project's pytest loads and already configures (see ``_parallel``).
    """

    python: str
    config: CoverageConfig
    env: dict[str, str]
    project_dir: Path
    quiet: bool
    workers: str
    plugins: PytestPlugins


def _announce(line: str, *, quiet: bool) -> None:
    """Print a progress line to stdout unless quiet.

    Args:
        line: The complete line, including its ``[coverage]`` / ``[codecov]`` prefix.
        quiet: When True, print nothing.
    """
    if not quiet:
        print(line)


class _PytestCommand(NamedTuple):
    """The pytest-under-coverage command and the line that announces it.

    Attributes:
        argv: The argv to execute.
        display: The human-readable ``[coverage] ...`` line describing it.
    """

    argv: list[str]
    display: str


def _pytest_argv(run: _CoverageRun, *, include_integration: bool) -> _PytestCommand:
    """Build the pytest-under-coverage command and the line that announces it.

    Args:
        run: The shared settings of this coverage run.
        include_integration: Include integration tests (no marker filter).

    Returns:
        The argv to execute and the human-readable line describing it.
    """
    config = run.config
    head, head_display = _pytest_head(run)
    # The PROJECT's interpreter, never sys.executable: that is bmk's own tool env,
    # whose dependency tree is not the one the project declares (bmk's got only
    # `[dev]`; the project's venv gets every extra), so testing there exercised an
    # environment nobody ships while pyright/pip-audit inspected the real one.
    argv = [run.python, *head]

    marker_filter = ""
    markers = [] if include_integration else marker_args(config.exclude_markers, project=run.plugins)
    if markers:
        marker_filter = markers[1]
        argv.extend(markers)

    if run.quiet:
        argv.extend(["--tb=short", "-q", "--no-header"])
    else:
        argv.append(config.pytest_verbosity)

    marker_display = f"-m '{marker_filter}' " if marker_filter else ""
    display = f"[coverage] python {head_display} {marker_display}{config.pytest_verbosity}"
    return _PytestCommand(argv=argv, display=display)


def _pytest_head(run: _CoverageRun) -> tuple[list[str], str]:
    """The interpreter arguments that start pytest under coverage, and how they read.

    Serial runs keep ``coverage run -m pytest``. A parallel run measures through
    pytest-cov instead, because ``coverage run`` sees only the controller process
    while the tests execute in the xdist workers; pytest-cov starts coverage in every
    worker and combines their data into ``COVERAGE_FILE``, which the report and XML
    steps then read unchanged. ``--cov-report=`` leaves the reporting to those steps, and
    ``--cov-fail-under=0`` the floor: pytest-cov would otherwise enforce coverage's own
    ``fail_under`` inside pytest and fail the run as if a test had failed, before the
    report step could print which lines are missing.
    """
    sources = run.config.coverage_source
    if run.workers == "1":
        joined = ",".join(sources)
        # coverage run measures this process only; a project's own -n would move the tests
        # into workers it never sees, so xdist_args overrides it with -n 0.
        head = ["-m", "coverage", "run", f"--source={joined}", "-m", "pytest", *xdist_args("1", project=run.plugins)]
    else:
        head = [
            "-m",
            "pytest",
            *xdist_args(run.workers, project=run.plugins),
            *(f"--cov={source}" for source in sources),
            "--cov-report=",
            "--cov-fail-under=0",
        ]
    return head, " ".join(head)


class WorkerPlan(NamedTuple):
    """How one coverage run spreads the suite.

    Attributes:
        workers: ``"1"`` for a serial run, else ``"auto"`` or a count.
        plugins: What the project's pytest loads; unanswered when it was never asked.
    """

    workers: str
    plugins: PytestPlugins


def plan_test_workers(
    configured: str, *, python: str, env: dict[str, str], cwd: Path, probe: ParallelProbe = probe_parallel
) -> WorkerPlan:
    """The worker setting this coverage run uses, after asking the project's own pytest.

    A parallel run needs pytest-xdist AND pytest-cov loaded by the project's pytest. When
    one is not installed the suite runs serially and one stderr line names the package to
    add; it reaches the user in text mode and, in JSON mode, only with a failing stage's
    output. A plugin that is installed but switched off by the project's configuration is
    the project's decision: serial, and nothing printed. A pytest that drops xdist's groups
    (``ParallelSupport.GROUPS_IGNORED``) also runs serially, with one stderr line naming why:
    grouped tests share a database or a port, and a green parallel run would hide the clash.

    Args:
        configured: ``[tool.scripts.test] workers``, already normalised.
        python: The project's interpreter.
        env: The run's environment; ``BMK_TEST_WORKERS`` in it overrides ``configured``.
        cwd: The project directory.
        probe: Asks the project's interpreter what its pytest loads.

    Returns:
        The worker setting and the plugin facts the pytest command is built from.

    Raises:
        RefusalError: ``BMK_TEST_WORKERS`` holds no valid worker setting.
    """
    workers = resolve_test_workers(configured, env=env)
    # Asked even for a serial run: a project whose addopts passes -n needs -n 0 then.
    plugins = probe(python, env=env, cwd=cwd)
    if workers == "1":
        return WorkerPlan("1", plugins)
    if plugins.support is ParallelSupport.READY:
        return WorkerPlan(workers, plugins)
    if plugins.support is ParallelSupport.GROUPS_IGNORED:
        print(
            "[coverage] tests run in one process: this pytest drops pytest-xdist's xdist_group marks "
            "(pytest-xdist issue #1386), so grouped tests would run in parallel; a pytest-xdist release "
            "with the fix, or pytest<9.2 in the dev extra, restores the parallel run",
            file=sys.stderr,
        )
        return WorkerPlan("1", plugins)
    if plugins.missing:
        print(
            f"[coverage] tests run in one process: add {plugins.missing} to the project's dev extra to run "
            "them in parallel, or set [tool.scripts.test] workers = 1 to keep them serial",
            file=sys.stderr,
        )
    return WorkerPlan("1", plugins)


def _run_pytest_under_coverage(run: _CoverageRun, *, include_integration: bool) -> int:
    """Announce and run the test suite under coverage.

    Args:
        run: The shared settings of this coverage run.
        include_integration: Include integration tests (no marker filter).

    Returns:
        The pytest exit code.
    """
    command = _pytest_argv(run, include_integration=include_integration)
    _announce(command.display, quiet=run.quiet)
    result = subprocess.run(
        command.argv,
        env=run.env,
        cwd=run.project_dir,
        check=False,
    )
    return result.returncode


def _run_coverage_report(run: _CoverageRun) -> int:
    """Announce and run the terminal coverage report, enforcing ``fail_under``.

    The report is silenced in quiet mode because its summary only adds noise there.
    It must use the same interpreter as the test run: the data file was written by
    THAT coverage, and a different coverage version may refuse to read it.

    Args:
        run: The shared settings of this coverage run.

    Returns:
        The coverage report exit code (non-zero below ``fail_under``).
    """
    fail_under = run.config.fail_under
    _announce(f"[coverage] python -m coverage report -m --fail-under={fail_under}", quiet=run.quiet)
    argv = [run.python, "-m", "coverage", "report", "-m", f"--fail-under={fail_under}"]
    if not run.quiet:
        result = subprocess.run(argv, env=run.env, cwd=run.project_dir, check=False)
    else:
        # Captured, not discarded: a passing report is noise in quiet mode, but a failing one is
        # the only place that names the lines the floor is missing.
        result = subprocess.run(
            argv,
            env=run.env,
            cwd=run.project_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
    if result.returncode != 0:
        print(f"[coverage] Coverage is below fail_under = {fail_under} (exit {result.returncode})", file=sys.stderr)
    return result.returncode


def _write_coverage_xml(run: _CoverageRun) -> None:
    """Announce and write the XML report Codecov uploads.

    A failure only warns: the tests and the coverage floor have already passed, and
    a missing upload artefact says nothing about the code under test.

    Args:
        run: The shared settings of this coverage run.
    """
    report_file = run.config.coverage_report_file
    _announce(f"[coverage] python -m coverage xml -o {report_file}", quiet=run.quiet)
    result = subprocess.run(
        [run.python, "-m", "coverage", "xml", "-o", report_file],
        env=run.env,
        cwd=run.project_dir,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"[coverage] warning: XML report generation failed (exit {result.returncode})",
            file=sys.stderr,
        )


def run_coverage_tests(
    *,
    project_dir: Path | None = None,
    verbose: bool = False,
    generate_xml: bool = True,
    include_integration: bool = False,
    quiet: bool = False,
    python: str | None = None,
    probe: ParallelProbe = probe_parallel,
) -> int:
    """Run pytest under coverage and generate reports.

    Args:
        project_dir: Project directory. Defaults to cwd.
        verbose: Enable verbose output.
        generate_xml: Generate XML coverage report for Codecov.
        include_integration: Include integration tests (excluded by default).
        quiet: Minimize output (short tracebacks, no per-test lines).
        python: Interpreter to run the suite under - the PROJECT's venv python. Required;
            this script itself runs under bmk's interpreter (it is stdlib-only), but the
            tests must not.
        probe: Asks the project's interpreter what its pytest loads (``probe_parallel``).

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    if project_dir is None:
        project_dir = Path.cwd()

    test_python = _resolve_test_interpreter(python)
    if isinstance(test_python, _InterpreterRefusal):
        print(f"Cannot run tests: {test_python.reason}", file=sys.stderr)
        return 1

    config = CoverageConfig.from_pyproject(project_dir)

    # Clean up before run
    prune_coverage_data_files(project_dir)
    remove_report_artifacts(project_dir, config.coverage_report_file)

    base_env = build_env(project_dir, config.src_path)
    plan = plan_test_workers(config.workers, python=test_python, env=base_env, cwd=project_dir, probe=probe)

    with tempfile.TemporaryDirectory() as tmpdir:
        run = _CoverageRun(
            python=test_python,
            config=config,
            env=base_env | {"COVERAGE_FILE": str(Path(tmpdir) / ".coverage")},
            project_dir=project_dir,
            quiet=quiet,
            workers=plan.workers,
            plugins=plan.plugins,
        )
        returncode = _run_pytest_under_coverage(run, include_integration=include_integration)
        if returncode != 0:
            print(f"[coverage] Tests failed (exit {returncode})", file=sys.stderr)
            return returncode

        returncode = _run_coverage_report(run)
        if returncode != 0:
            return returncode

        if generate_xml:
            _write_coverage_xml(run)

    return 0


# ---------------------------------------------------------------------------
# Codecov Token Management
# ---------------------------------------------------------------------------


def find_dotenv_upward(start_dir: Path) -> Path | None:
    """Search for .env file in start_dir and its parents up to filesystem root."""
    current = start_dir.resolve()
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def ensure_codecov_token(project_dir: Path | None = None) -> str | None:
    """Find and return codecov token without mutating os.environ.

    Checks ``CODECOV_TOKEN`` env var first, then searches for a ``.env``
    file starting from *project_dir* and walking up to filesystem root.

    Args:
        project_dir: Directory to start searching for .env file. Defaults to cwd.

    Returns:
        The token string if found, or ``None`` if unavailable.
    """
    existing = os.getenv("CODECOV_TOKEN")
    if existing:
        return existing

    # Deferred: skip the dotenv import/parse entirely in the common CI case
    # above, where CODECOV_TOKEN is already set in the environment.
    from dotenv import dotenv_values  # noqa: PLC0415

    start = project_dir or Path.cwd()
    env_path = find_dotenv_upward(start)
    if env_path is None:
        return None

    values = dotenv_values(env_path)
    return values.get("CODECOV_TOKEN") or None


# ---------------------------------------------------------------------------
# Git Utilities
# ---------------------------------------------------------------------------


def resolve_commit_sha() -> str | None:
    """Resolve the current git commit SHA from environment or git."""
    sha = os.getenv("GITHUB_SHA")
    if sha:
        return sha.strip()
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    candidate = proc.stdout.strip()
    return candidate or None


def resolve_git_branch() -> str | None:
    """Resolve the current git branch from environment or git."""
    branch = os.getenv("GITHUB_REF_NAME")
    if branch:
        return branch.strip()
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    candidate = proc.stdout.strip()
    if candidate in {"", "HEAD"}:
        return None
    return candidate


class GitService(str, Enum):
    """Codecov git service identifiers for a closed set of known hosts.

    Inherits from str (the StrEnum pattern on Python 3.10, where the stdlib
    ``enum.StrEnum`` does not exist yet - this project targets >=3.10), so a
    member compares equal to its value (``GitService.GITHUB == "github"``).
    It does NOT render as its value: ``str()`` and f-strings give
    ``GitService.GITHUB`` on 3.11+, so the argv takes ``.value``, byte-identical to what
    codecovcli received before this was an enum.
    """

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


_GIT_SERVICE_BY_HOST = {
    "github.com": GitService.GITHUB,
    "gitlab.com": GitService.GITLAB,
    "bitbucket.org": GitService.BITBUCKET,
}


def resolve_git_service(repo_host: str | None) -> GitService | None:
    """Map repository host to Codecov git service identifier.

    Args:
        repo_host: Repository host (e.g., 'github.com').

    Returns:
        Codecov service identifier or None.
    """
    host = (repo_host or "").lower()
    return _GIT_SERVICE_BY_HOST.get(host)


class RepoRemote(NamedTuple):
    """The parts of the ``origin`` remote URL Codecov needs.

    Each part is the segment the URL held, which can be empty (``git@host:/repo``
    yields an empty owner): an empty part never contributes a slug or a service,
    so a half-parsable remote still uploads with whatever it does carry.

    Attributes:
        host: Repository host, e.g. ``github.com``.
        owner: Repository owner or organization.
        name: Repository name, without a ``.git`` suffix.
    """

    host: str
    owner: str
    name: str

    @property
    def slug(self) -> str | None:
        """The ``owner/name`` slug, or None when either part is empty.

        Examples:
            >>> RepoRemote("github.com", "myorg", "myrepo").slug
            'myorg/myrepo'
            >>> RepoRemote("github.com", "", "myrepo").slug is None
            True
        """
        if self.owner and self.name:
            return f"{self.owner}/{self.name}"
        return None


def get_repo_metadata_from_git() -> RepoRemote | None:
    """Extract repo metadata from git remote origin.

    Returns:
        The parsed remote, or None when git has no ``origin`` or its URL is not an
        SSH or HTTP(S) URL with an owner and a name segment.
    """
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None

    url = proc.stdout.strip()
    # Handle SSH URLs: git@github.com:owner/repo.git
    if url.startswith("git@"):
        parts = url.split(":", 1)
        if len(parts) == 2:
            host = parts[0].replace("git@", "")
            path = parts[1].removesuffix(".git")
            path_parts = path.split("/")
            if len(path_parts) >= 2:
                return RepoRemote(host, path_parts[0], path_parts[1])
    # Handle HTTPS URLs: https://github.com/owner/repo.git
    # Also handles embedded auth: https://token@github.com/owner/repo.git
    elif url.startswith("https://") or url.startswith("http://"):
        url_without_proto = url.split("://", 1)[1]
        parts = url_without_proto.removesuffix(".git").split("/")
        if len(parts) >= 3:
            host = parts[0].rsplit("@", 1)[-1]
            return RepoRemote(host, parts[1], parts[2])
    return None


# ---------------------------------------------------------------------------
# Codecov Upload
# ---------------------------------------------------------------------------


def upload_coverage_report(
    *,
    project_dir: Path | None = None,
    coverage_report_file: str = DEFAULT_COVERAGE_REPORT_FILE,
    codecov_token: str | None = None,
) -> bool:
    """Upload coverage report via the official Codecov CLI when available.

    Args:
        project_dir: Project directory containing coverage report. Defaults to cwd.
        coverage_report_file: Name of the coverage report file.
        codecov_token: Codecov token to inject into the subprocess environment.
            When provided, avoids reliance on a globally-set environment variable.

    Returns:
        True if upload succeeded, False otherwise.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    uploader = check_codecov_prerequisites(project_dir, coverage_report_file, codecov_token=codecov_token)
    if uploader is None:
        return False

    commit_sha = resolve_commit_sha()
    if commit_sha is None:
        print("[codecov] Unable to resolve git commit; skipping upload", file=sys.stderr)
        return True

    remote = get_repo_metadata_from_git()

    args = build_codecov_args(
        uploader=uploader,
        commit_sha=commit_sha,
        coverage_report_file=coverage_report_file,
        remote=remote,
    )
    env_overrides = build_codecov_env(remote)

    # Build subprocess environment without mutating os.environ
    env = os.environ.copy()
    env.update(env_overrides)
    if codecov_token:
        env.setdefault("CODECOV_TOKEN", codecov_token)

    result = subprocess.run(
        args,
        env=env,
        check=False,
        cwd=project_dir,
    )
    return handle_codecov_result(result.returncode)


def check_codecov_prerequisites(
    project_dir: Path,
    coverage_report_file: str = DEFAULT_COVERAGE_REPORT_FILE,
    *,
    codecov_token: str | None = None,
) -> str | None:
    """Check prerequisites for codecov upload, return uploader path or None.

    Args:
        project_dir: Project directory containing coverage report.
        coverage_report_file: Name of the coverage report file.
        codecov_token: Codecov token discovered by the caller.

    Returns:
        Path to codecovcli executable, or None if prerequisites not met.
    """
    report_path = project_dir / coverage_report_file
    if not report_path.is_file():
        print(f"[codecov] Coverage report not found: {report_path}")
        return None

    has_token = bool(codecov_token or os.getenv("CODECOV_TOKEN"))
    if not has_token and not os.getenv("CI"):
        print("[codecov] CODECOV_TOKEN not configured; skipping upload (set CODECOV_TOKEN or run in CI)")
        return None

    uploader = shutil.which("codecovcli")
    if uploader is None:
        print(
            "[codecov] 'codecovcli' not found; install with 'pip install codecov-cli' to enable uploads",
            file=sys.stderr,
        )
        return None

    return uploader


def build_codecov_args(
    *,
    uploader: str,
    commit_sha: str,
    coverage_report_file: str = DEFAULT_COVERAGE_REPORT_FILE,
    remote: RepoRemote | None = None,
) -> list[str]:
    """Build the codecov CLI arguments.

    Args:
        uploader: Path to codecovcli executable.
        commit_sha: Git commit SHA.
        coverage_report_file: Name of the coverage report file.
        remote: The parsed ``origin`` remote, or None when it could not be read.

    Returns:
        List of command-line arguments.
    """
    args = [
        uploader,
        "upload-coverage",
        "--file",
        coverage_report_file,
        "--disable-search",
        "--fail-on-error",
        "--sha",
        commit_sha,
        "--name",
        f"local-{platform.system()}-{platform.python_version()}",
        "--flag",
        "local",
    ]

    branch = resolve_git_branch()
    if branch:
        args.extend(["--branch", branch])

    if remote is None:
        return args

    git_service = resolve_git_service(remote.host)
    if git_service:
        args.extend(["--git-service", git_service.value])

    if remote.slug:
        args.extend(["--slug", remote.slug])

    return args


def build_codecov_env(remote: RepoRemote | None) -> dict[str, str]:
    """Build environment overrides for codecov upload.

    Args:
        remote: The parsed ``origin`` remote, or None when it could not be read.

    Returns:
        Dictionary of environment variable overrides.
    """
    env_overrides: dict[str, str] = {"CODECOV_NO_COMBINE": "1"}
    if remote is not None and remote.slug:
        env_overrides["CODECOV_SLUG"] = remote.slug
    return env_overrides


def handle_codecov_result(exit_code: int) -> bool:
    """Handle the codecov upload result.

    Args:
        exit_code: Exit code from codecov CLI.

    Returns:
        True if upload succeeded, False otherwise.
    """
    if exit_code == 0:
        print("[codecov] upload succeeded")
        return True
    print(f"[codecov] upload failed (exit {exit_code})", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def _warn(line: str, *, quiet: bool) -> None:
    """Print a skip warning to stderr unless quiet.

    Args:
        line: The complete warning line, colour codes included.
        quiet: When True, print nothing.
    """
    if not quiet:
        print(line, file=sys.stderr)


def _run_tests_step(
    project_dir: Path,
    *,
    verbose: bool,
    include_integration: bool,
    quiet: bool,
    python: str | None,
    probe: ParallelProbe,
) -> int:
    """Run the suite under coverage, reporting the outcome.

    A failure is reported even in quiet mode: quiet trims progress noise, it must
    never make a red run look silent.

    Args:
        project_dir: Project directory.
        verbose: Enable verbose output.
        include_integration: Include integration tests (excluded by default).
        quiet: Minimize output (short tracebacks, no per-test lines).
        python: Interpreter to run the suite under - the project's own venv python.
        probe: Asks the project's interpreter what its pytest loads.

    Returns:
        The test exit code (0 when the suite and the coverage floor passed).
    """
    _announce(f"[coverage] Running tests with coverage in {project_dir}...", quiet=quiet)
    exit_code = run_coverage_tests(
        project_dir=project_dir,
        verbose=verbose,
        include_integration=include_integration,
        quiet=quiet,
        python=python,
        probe=probe,
    )
    if exit_code != 0:
        # run_coverage_tests has already said which step failed: the tests or the floor.
        return exit_code
    _announce("[coverage] Tests passed", quiet=quiet)
    return 0


def _upload_step(project_dir: Path, *, quiet: bool) -> int:
    """Upload the coverage report to Codecov when a token and the uploader exist.

    Args:
        project_dir: Project directory containing the coverage report.
        quiet: Suppress the skip warnings and the uploading line.

    Returns:
        0 when the upload succeeded or was skipped, 1 when a real upload failed.
    """
    token = ensure_codecov_token(project_dir)
    if not token:
        _warn(
            "\033[33m[codecov] warning: CODECOV_TOKEN not found; skipping upload "
            "(set CODECOV_TOKEN in environment or .env)\033[0m",
            quiet=quiet,
        )
        return 0

    # An absent uploader is a missing optional tool, not a coverage failure:
    # skip it the same way a missing token is skipped. Only a real upload
    # attempt that fails is worth failing the run over.
    if shutil.which("codecovcli") is None:
        _warn("\033[33m[codecov] warning: 'codecovcli' not installed; skipping upload\033[0m", quiet=quiet)
        return 0

    _announce(f"[codecov] Uploading coverage from {project_dir}...", quiet=quiet)
    if not upload_coverage_report(project_dir=project_dir, codecov_token=token):
        return 1
    return 0


def main(
    *,
    project_dir: Path | None = None,
    run_tests: bool = False,
    upload: bool = True,
    verbose: bool = False,
    include_integration: bool = False,
    quiet: bool = False,
    python: str | None = None,
    probe: ParallelProbe = probe_parallel,
) -> int:
    """Main entry point for coverage operations.

    Args:
        project_dir: Project directory. Defaults to cwd.
        run_tests: Run pytest with coverage before uploading.
        upload: Upload coverage to Codecov after running tests.
        verbose: Enable verbose output.
        include_integration: Include integration tests (excluded by default).
        quiet: Minimize output (short tracebacks, no per-test lines).
        python: Interpreter to run the suite under - the project's own venv python.
        probe: Asks the project's interpreter what its pytest loads (``probe_parallel``).

    Returns:
        Exit code: the test run's own code when it fails, 2 when a setting is refused, 1
        when an upload fails, otherwise 0 (a skipped upload counts as success).
    """
    if project_dir is None:
        project_dir = Path.cwd()

    if run_tests:
        # This runs as the stage's subprocess, out of reach of the CLI's refusal handler, so a
        # refused setting is reported here as one line with test-all's exit code, not a traceback.
        try:
            exit_code = _run_tests_step(
                project_dir,
                verbose=verbose,
                include_integration=include_integration,
                quiet=quiet,
                python=python,
                probe=probe,
            )
        except RefusalError as exc:
            print(f"[coverage] {exc}", file=sys.stderr)
            return 2
        except ValidationError as exc:
            print(f"[coverage] pyproject.toml: {describe_validation_error(exc)}", file=sys.stderr)
            return 2
        if exit_code != 0:
            return exit_code

    if upload:
        return _upload_step(project_dir, quiet=quiet)

    return 0


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Run tests with coverage and upload to Codecov",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run tests with coverage and upload (excludes integration tests)
  python _coverage.py --run --project-dir /path/to/project

  # Run all tests including integration tests
  python _coverage.py --run --integration --project-dir /path/to/project

  # Upload existing coverage.xml only
  python _coverage.py --project-dir /path/to/project

  # Run tests only, skip upload
  python _coverage.py --run --no-upload --project-dir /path/to/project
""",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory containing pyproject.toml (default: cwd)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run pytest with coverage before uploading",
    )
    parser.add_argument(
        "--python",
        default=None,
        help=(
            "Interpreter to run the suite under - the project's own venv python. "
            "This script runs under bmk's interpreter, but the tests must not: bmk's "
            "tool env is a different dependency tree from the one the project declares."
        ),
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Include integration tests (excluded by default)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip uploading coverage to Codecov",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--output-format",
        choices=[fmt.value for fmt in ToolOutputFormat],
        default=ToolOutputFormat.TEXT.value,
        help="Output format (accepted for pipeline consistency; coverage XML is always generated)",
    )
    args, _unknown = parser.parse_known_args()
    sys.exit(
        main(
            project_dir=args.project_dir,
            run_tests=args.run,
            upload=not args.no_upload,
            verbose=args.verbose,
            include_integration=args.integration,
            quiet=ToolOutputFormat(args.output_format) is ToolOutputFormat.JSON,
            python=args.python,
        )
    )
