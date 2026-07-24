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
``VIRTUAL_ENV``, so the pin is what makes per-version type-checking real). ruff/bandit/
import-linter are version-independent and pip-audit is env-based, so they are not repeated.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from bmk.adapters.stagerunner.venv import (
    all_python_minors,
    ensure_project_venv,
    ensure_project_venv_at,
    venv_python,
    venv_version,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["CellResult", "CellStatus", "main"]

_MAX_DETAIL_LINES = 40  # how much of a failing tool's output to surface per cell


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


_VERDICT_PREFIXES = ("FAILED", "ERROR", "error:")


def _tail(text: str) -> str:
    """The lines that explain a cell's failure - the verdicts first, then the tail.

    A plain tail is not enough: the suite logs to stderr, so on a real failure the last
    lines are routine log chatter and pytest's ``FAILED ...`` summary has already scrolled
    past. That made a genuine matrix failure read as "no output captured". Verdict lines are
    hoisted so the cause is visible whatever else the run printed.
    """
    lines = text.strip().splitlines()
    verdicts = [line for line in lines if line.startswith(_VERDICT_PREFIXES)]
    tail = lines[-_MAX_DETAIL_LINES:]
    hoisted = [line for line in verdicts if line not in tail]
    return "\n".join(hoisted + tail)


def _cell_env(venv: Path) -> dict[str, str]:
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


def _run_gate_in_venv(venv: Path, project_dir: Path, *, quiet: bool) -> tuple[CellStatus, str]:
    """Run pytest then pyright in ``venv``; the first failure wins.

    pytest runs from the venv's own interpreter (the project is installed there), pyright is
    pinned at it with ``--pythonpath``. ``-p no:cacheprovider`` keeps parallel cells from
    racing on a shared ``.pytest_cache``. Both run under ``_cell_env`` so the cell's own
    tools resolve.
    """
    python = venv_python(venv)
    env = _cell_env(venv)
    pytest_cmd = [str(python), "-m", "pytest", "-m", "not integration", "-q", "-p", "no:cacheprovider"]
    result = subprocess.run(pytest_cmd, cwd=project_dir, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0:
        return CellStatus.FAIL, _tail(result.stdout + result.stderr)

    pyright_cmd = ["pyright", "--pythonpath", str(python)]
    if quiet:
        pyright_cmd.append("--outputjson")
    checked = subprocess.run(pyright_cmd, cwd=project_dir, capture_output=True, text=True, check=False, env=env)
    if checked.returncode != 0:
        return CellStatus.FAIL, _tail(checked.stdout + checked.stderr)
    return CellStatus.PASSED, ""


def _run_cell(project_dir: Path, minor: str, *, quiet: bool) -> CellResult:
    """Provision ``.venv-<minor>`` and run its gates. Provisioning failure is ERROR, not FAIL."""
    venv = ensure_project_venv_at(project_dir, project_dir / f".venv-{minor}", minor, quiet=quiet)
    if venv is None:
        return CellResult(minor, "?", CellStatus.ERROR, "could not provision a venv for this Python")
    version = venv_version(venv) or "?"
    status, detail = _run_gate_in_venv(venv, project_dir, quiet=quiet)
    return CellResult(minor, version, status, detail)


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
    status, detail = _run_gate_in_venv(venv, project_dir, quiet=quiet)
    _print_report([CellResult("default", version or "?", status, detail)])
    return 0 if status is CellStatus.PASSED else 1


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


def main(*, project_dir: Path, quiet: bool = True, run_cell: Callable[..., CellResult] = _run_cell) -> int:
    """Run the version matrix; exit non-zero if any cell is not PASS.

    Falls back to a single default cell (with a warning) when no versions are declared.

    ``run_cell`` is the per-version unit of work, injected so the orchestration (fan-out,
    aggregation, exit code) can be tested with a real fake at this seam rather than by
    patching internals; production always uses the default. The real cell is proven by the
    ``local_only`` end-to-end tests.
    """
    minors = all_python_minors(project_dir)
    if not minors:
        return _run_default_cell(project_dir, quiet=quiet)

    def run(minor: str) -> CellResult:
        return run_cell(project_dir, minor, quiet=quiet)

    workers = min(len(minors), os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, minors))

    _print_report(results)
    return _exit_code(results)
