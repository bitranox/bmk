"""Run the test suite on every Python version the project declares (`test-all`).

`make test` gates against ONE venv - the newest declared Python. This runs the version-
sensitive gates (pytest + pyright) against EACH declared minor, in parallel, so a break that
only shows on, say, 3.10 is caught locally instead of waiting for CI.

Why a helper and not stages: the versions are discovered at runtime, each needs its own venv,
and a ``StageContext`` is frozen to a single pinned venv. So the matrix cannot be expressed as
pipeline stages - it provisions and runs each cell itself, here.

Each cell provisions ``.venv-<minor>`` (by minor, not patch: the dir name stays stable while
uv auto-follows patch upgrades), installs the project into it, then runs
``python -m pytest`` and ``pyright --pythonpath <venv-python>`` (pyright does not honour
``VIRTUAL_ENV``, so the pin is what makes per-version type-checking real), once per OS
``[tool.ci].os`` declares (``--pythonplatform``), as ``make test``'s pyright stage does. ruff/bandit/
import-linter are version-independent and pip-audit is env-based, so they are not repeated.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, NamedTuple

from bmk.adapters.stagerunner.helpers._coverage import CoverageConfig
from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config
from bmk.adapters.stagerunner.project import pyright_runs
from bmk.adapters.stagerunner.venv import (
    all_python_minors,
    ensure_minors_installed,
    ensure_project_venv,
    ensure_project_venv_at,
    venv_python,
    venv_version,
)
from bmk.domain.enums import RefusalKind
from bmk.domain.errors import RefusalError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

__all__ = [
    "MAX_DETAIL_LINES",
    "WORKERS_ENV",
    "CellResult",
    "CellStatus",
    "cell_env",
    "failure_excerpt",
    "main",
    "pytest_marker_args",
    "resolve_workers",
    "run_version_cell",
]

MAX_DETAIL_LINES = 40  # how much of a failing tool's output to surface per cell

#: Overrides `[tool.scripts.test-all].workers` for one run; empty/unset means "read
#: pyproject.toml instead". Named after the setting it overrides, like `BMK_GIT_REMOTE`
#: overrides `[tool.git].default-remote` - see `git_ops.py`.
WORKERS_ENV = "BMK_TEST_ALL_WORKERS"


class CellStatus(str, Enum):
    """Outcome of one version's gate. A ``str`` Enum (3.10 floor: no ``StrEnum``)."""

    PASSED = "pass"
    FAIL = "fail"  # a gate (pytest or pyright) reported a real failure
    ERROR = "error"  # the venv could not even be provisioned - a distinct outcome


@dataclass(frozen=True)
class CellResult:
    """The result of running the gates for one Python version."""

    label: str  # the declared minor ("3.14"), or "default" for the no-classifier fallback
    version: str  # the patch actually run ("3.14.5"), or "?" when it could not be determined
    status: CellStatus
    detail: str = ""


class _GateOutcome(NamedTuple):
    """What the gates said for one venv, before it is labelled with a version.

    Kept apart from :class:`CellResult` because the gate runner does not know the cell's
    label: the default cell and the per-minor cells name their result differently.

    Attributes:
        status: PASSED, or FAIL for the first gate that failed.
        detail: That gate's explaining output, empty on success.
    """

    status: CellStatus
    detail: str


_VERDICT_PREFIXES = ("FAILED", "ERROR", "error:")


def failure_excerpt(text: str) -> str:
    """The lines that explain a cell's failure - the verdicts first, then the tail.

    A plain tail is not enough: the suite logs to stderr, so on a real failure the last
    lines are routine log chatter and pytest's ``FAILED ...`` summary has already scrolled
    past. That made a genuine matrix failure read as "no output captured". Verdict lines are
    hoisted so the cause is visible whatever else the run printed.
    """
    lines = text.strip().splitlines()
    verdicts = [line for line in lines if line.startswith(_VERDICT_PREFIXES)]
    tail = lines[-MAX_DETAIL_LINES:]
    hoisted = [line for line in verdicts if line not in tail]
    return "\n".join(hoisted + tail)


def cell_env(venv: Path) -> dict[str, str]:
    """Environment pinning a cell's subprocesses at that cell's own venv.

    A cell must not inherit the ambient environment unchanged. The matrix runs as a
    HelperAction (in-process), so there is no ``StageContext`` env to inherit - unlike
    ``make test``, whose pytest runs as a ToolAction with the stage runner's env. Without
    this, a test that shells out to a console script (``ruff``, ``pip-audit``) finds no
    such tool on ``PATH`` and fails in ``test-all`` while passing in ``test``.

    Pointing ``PATH`` at the CELL's ``bin`` (not bmk's tool bin) is what makes the matrix
    honest: each version's tests resolve the tools installed for THAT interpreter.
    """
    env = dict(os.environ)
    python = venv_python(venv)
    env["VIRTUAL_ENV"] = str(venv)
    env["PIPAPI_PYTHON_LOCATION"] = str(python)
    bin_dir = str(python.parent)
    existing = env.get("PATH", "")
    env["PATH"] = f"{bin_dir}{os.pathsep}{existing}" if existing else bin_dir
    return env


def pytest_marker_args(project_dir: Path) -> list[str]:
    """The ``-m`` filter ``make test`` applies, read from the same ``[tool.scripts.test]`` key.

    A project marks tests that must never run in the gate (host-mutating ones, say) through
    ``exclude-markers``; a matrix with its own hardcoded filter runs them in every cell. An
    empty value filters nothing, as it does in ``make test``.
    """
    exclude = CoverageConfig.from_pyproject(project_dir).exclude_markers
    return ["-m", f"not {exclude}"] if exclude else []


def _run_gate_in_venv(venv: Path, project_dir: Path, *, quiet: bool) -> _GateOutcome:
    """Run pytest then pyright in ``venv``; the first failure wins.

    pytest runs from the venv's own interpreter (the project is installed there), with the
    project's ``exclude-markers`` filter; pyright is pinned at it with ``--pythonpath``.
    ``-p no:cacheprovider`` keeps parallel cells from racing on a shared ``.pytest_cache``.
    Both run under ``cell_env`` so the cell's own tools resolve.
    """
    python = venv_python(venv)
    env = cell_env(venv)
    pytest_cmd = [str(python), "-m", "pytest", *pytest_marker_args(project_dir), "-q", "-p", "no:cacheprovider"]
    result = subprocess.run(pytest_cmd, cwd=project_dir, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0:
        return _GateOutcome(CellStatus.FAIL, failure_excerpt(result.stdout + result.stderr))

    # The same runs as make test's pyright stage (pyright_runs): pyright checks one platform per
    # run, so a cell typed for the host alone passes a Windows-only error that only the older Python
    # this cell exists for shows.
    for extra in pyright_runs(project_dir):
        pyright_cmd = ["pyright", "--pythonpath", str(python), *extra]
        if quiet:
            pyright_cmd.append("--outputjson")
        checked = subprocess.run(pyright_cmd, cwd=project_dir, capture_output=True, text=True, check=False, env=env)
        if checked.returncode != 0:
            header = f"pyright {' '.join(extra)}:\n" if extra else ""
            return _GateOutcome(CellStatus.FAIL, header + failure_excerpt(checked.stdout + checked.stderr))
    return _GateOutcome(CellStatus.PASSED, "")


def run_version_cell(project_dir: Path, minor: str, *, quiet: bool) -> CellResult:
    """Provision ``.venv-<minor>`` and run its gates. Provisioning failure is ERROR, not FAIL.

    ``install_python=False``: :func:`main` already prepared every minor, serially, before any cell.
    """
    venv = ensure_project_venv_at(project_dir, project_dir / f".venv-{minor}", minor, quiet=quiet, install_python=False)
    if venv is None:
        return CellResult(minor, "?", CellStatus.ERROR, "could not provision a venv for this Python")
    version = venv_version(venv) or "?"
    outcome = _run_gate_in_venv(venv, project_dir, quiet=quiet)
    return CellResult(minor, version, outcome.status, outcome.detail)


def _run_default_cell(project_dir: Path, *, quiet: bool) -> int:
    """No classifiers: test the default ``.venv`` once, WARN, and return its exit code.

    The warning names the version actually tested so a green run is not mistaken for full-
    matrix coverage, and says how to get the matrix (declare the classifiers).
    """
    venv = ensure_project_venv(project_dir, os.environ, quiet=quiet)
    version = venv_version(venv) if venv else "?"
    print(
        "WARNING: no `Programming Language :: Python :: X.Y` classifiers in pyproject.toml.\n"
        f"         test-all tested only the default interpreter ({version}). Declare the\n"
        "         versions you support as classifiers to test the full matrix.",
        file=sys.stderr,
    )
    if venv is None:
        return 1
    outcome = _run_gate_in_venv(venv, project_dir, quiet=quiet)
    _print_report([CellResult("default", version or "?", outcome.status, outcome.detail)])
    return 0 if outcome.status is CellStatus.PASSED else 1


def _print_report(results: list[CellResult]) -> None:
    """One line per version: status, the patch it ran on, and any failure detail."""
    print("\ntest-all:")
    for r in results:
        print(f"  {r.label:<8} {r.version:<9} {r.status.value.upper()}")
    for r in results:
        if r.status is not CellStatus.PASSED and r.detail:
            print(f"\n--- {r.label} ({r.status.value}) ---\n{r.detail}", file=sys.stderr)


def _exit_code(results: list[CellResult]) -> int:
    """0 only when every version passed; any FAIL or ERROR fails the whole run."""
    return 0 if all(r.status is CellStatus.PASSED for r in results) else 1


def _workers_from_pyproject(project_dir: Path) -> int | None:
    """``[tool.scripts.test-all].workers``, or ``None`` if unset, unreadable or not an integer.

    Never raises: a missing file, malformed TOML, or a wrong-shaped table or value all
    degrade to ``None`` (``ScriptsTestAllConfig`` drops a non-integer, a bool included),
    same as every other ``[tool.*]`` reader here - a bad pyproject.toml must not abort the
    build that is trying to read it. An integer below 1 IS returned: unlike a wrong-shaped
    value it is a real instruction, and the caller refuses it.
    """
    manifest = project_dir / "pyproject.toml"
    if not manifest.is_file():
        return None
    try:
        config = load_pyproject_config(manifest)
    except Exception:  # an unreadable manifest degrades, never aborts - see all_python_minors
        return None
    return config.tool.scripts.test_all.workers


def _reject_below_one(value: int, *, source: str) -> None:
    """A configured worker count below 1 is a deliberate but nonsensical instruction -
    unlike an absent or wrong-shaped value, this does not degrade to the default.

    Raises:
        RefusalError: ``value`` is below 1; the message names ``source``.
    """
    if value < 1:
        msg = f"{source} must be >= 1 (1 means serial), got: {value}"
        raise RefusalError(msg, kind=RefusalKind.INVALID_ARGUMENT)


def resolve_workers(project_dir: Path, minors: list[str], *, env: Mapping[str, str] | None = None) -> int:
    """The number of version cells to run at once.

    Precedence: ``BMK_TEST_ALL_WORKERS`` env var, then
    ``[tool.scripts.test-all].workers`` in the project's own pyproject.toml, then the
    default (parallel: one worker per declared version, capped at the CPU count) -
    unchanged current behaviour for every project that sets neither.

    A configured value is capped at ``len(minors)`` (no point asking for more threads
    than there are cells) but never raised - a project that explicitly asks for
    ``workers = 1`` gets exactly the serial behaviour it declared. An explicit value
    below 1, or a non-integer env value, is refused with a :class:`RefusalError` naming
    which setting was wrong; a
    wrong-shaped or unparsable value falls back to the default instead, matching how
    every other pyproject-authored setting in this project degrades (see
    ``_toml_config.py``) - only a value the project MEANT to set to something invalid is
    an error. Called only with a non-empty ``minors`` (``main`` takes the no-classifiers
    fallback before this is reached), so capping against ``len(minors)`` never collapses
    to zero.

    Raises:
        RefusalError: The env var or the pyproject setting holds a worker count bmk refuses.
    """
    resolved_env: Mapping[str, str] = env if env is not None else os.environ
    default = min(len(minors), os.cpu_count() or 4)

    raw_env = resolved_env.get(WORKERS_ENV, "").strip()
    if raw_env:
        try:
            configured = int(raw_env)
        except ValueError:
            msg = f"{WORKERS_ENV} must be an integer, got: {raw_env!r}"
            raise RefusalError(msg, kind=RefusalKind.INVALID_ARGUMENT) from None
        _reject_below_one(configured, source=WORKERS_ENV)
        return min(configured, len(minors))

    configured_pyproject = _workers_from_pyproject(project_dir)
    if configured_pyproject is None:
        return default
    _reject_below_one(configured_pyproject, source="[tool.scripts.test-all].workers")
    return min(configured_pyproject, len(minors))


def main(
    *,
    project_dir: Path,
    quiet: bool = True,
    run_cell: Callable[..., CellResult] = run_version_cell,
    prepare_minors: Callable[..., None] = ensure_minors_installed,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run the version matrix; exit non-zero if any cell is not PASS.

    Falls back to a single default cell (with a warning) when no versions are declared.

    ``run_cell`` is the per-version unit of work, injected so the orchestration (fan-out,
    aggregation, exit code) can be tested with a real fake at this seam rather than by
    patching internals; production always uses the default. The real cell is proven by the
    ``local_only`` end-to-end tests. ``env`` is injected the same way for
    ``resolve_workers``; production always reads ``os.environ``.

    ``prepare_minors`` installs or upgrades every declared Python, serially, before the first
    cell: doing it inside the cells let one cell's install rewrite uv's minor aliases while
    another cell synced its venv, which then had no interpreter (bmk OPEN-WORK [102]).

    A refused worker count returns 2 with one stderr line, before any Python is installed:
    raising past this helper would leave the stage engine nothing to report but a crash.
    """
    minors = all_python_minors(project_dir)
    if not minors:
        return _run_default_cell(project_dir, quiet=quiet)

    try:
        workers = resolve_workers(project_dir, minors, env=env)
    except RefusalError as exc:
        print(f"[test-all] {exc}", file=sys.stderr)
        return 2

    prepare_minors(project_dir, minors, quiet=quiet)

    def run(minor: str) -> CellResult:
        return run_cell(project_dir, minor, quiet=quiet)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, minors))

    _print_report(results)
    return _exit_code(results)
