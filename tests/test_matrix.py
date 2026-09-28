# pyright: reportPrivateUsage=false
"""Tests for the version matrix helper (`test-all`).

Two layers, no patching of internals:

* Fast/offline: the orchestration (fan-out, aggregation, exit code) is tested by INJECTING a
  real fake cell-runner at ``main``'s ``run_cell`` seam - not by monkeypatching module globals.
* ``local_only`` end-to-end: the real thing - real uv venvs on real Python minors, real pytest
  and pyright - is the proof of the contract. It runs in ``make test`` and skips cleanly when
  uv / pyright / the interpreters are absent (so CI, which lacks them, skips it).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner.helpers._matrix import (
    _MAX_DETAIL_LINES,
    _WORKERS_ENV,
    CellResult,
    CellStatus,
    _cell_env,
    _tail,
    main,
    resolve_workers,
)
from bmk.adapters.stagerunner.venv import venv_python

if TYPE_CHECKING:
    from pathlib import Path


def _classifiers(minors: list[str]) -> str:
    lines = "\n".join(f'  "Programming Language :: Python :: {m}",' for m in minors)
    return f"classifiers = [\n{lines}\n]\n" if minors else ""


def _write_pyproject(project: Path, minors: list[str]) -> None:
    (project / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.10"\n'
        f"{_classifiers(minors)}"
        "[project.optional-dependencies]\n"
        'dev = ["pytest"]\n'
        "[tool.pyright]\n"
        'typeCheckingMode = "basic"\n'
        'include = ["tests"]\n'
        "[build-system]\n"
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n',
        encoding="utf-8",
    )


def _write_pyproject_with_workers(project: Path, minors: list[str], workers: object) -> None:
    """Same as ``_write_pyproject`` plus ``[tool.scripts.test-all].workers``.

    ``workers`` is written verbatim via ``repr`` (so a bare string can be planted too,
    proving a non-integer value is rejected rather than silently coerced).
    """
    (project / "pyproject.toml").write_text(
        "[project]\n"
        'name = "demo"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.10"\n'
        f"{_classifiers(minors)}"
        "[project.optional-dependencies]\n"
        'dev = ["pytest"]\n'
        "[tool.scripts.test-all]\n"
        f"workers = {workers!r}\n"
        "[tool.pyright]\n"
        'typeCheckingMode = "basic"\n'
        'include = ["tests"]\n'
        "[build-system]\n"
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n',
        encoding="utf-8",
    )


class _FakeCells:
    """A real callable that stands in for the per-version cell runner.

    Injected at ``main``'s ``run_cell`` seam (dependency injection, not a patch). Records the
    minors it saw and returns a scripted status per minor, so the fan-out and aggregation are
    exercised deterministically and offline.
    """

    def __init__(self, statuses: dict[str, CellStatus]) -> None:
        self.statuses = statuses
        self.seen: list[str] = []

    def __call__(self, _project_dir: Path, minor: str, *, quiet: bool = True) -> CellResult:
        _ = quiet
        self.seen.append(minor)
        return CellResult(minor, f"{minor}.0", self.statuses.get(minor, CellStatus.PASSED))


# ---------------------------------------------------------------------------
# Orchestration (fast, offline, injected fake at the run_cell seam)
# ---------------------------------------------------------------------------


def test_all_pass_exits_zero_and_runs_every_declared_version(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12", "3.14"])
    cells = _FakeCells({})

    rc = main(project_dir=tmp_path, run_cell=cells)

    assert rc == 0
    assert sorted(cells.seen) == ["3.10", "3.12", "3.14"]


def test_any_failure_exits_nonzero_but_every_cell_still_runs(tmp_path: Path) -> None:
    """A break on one version fails the run yet does not stop the others - you want the whole matrix."""
    _write_pyproject(tmp_path, ["3.10", "3.11", "3.12"])
    cells = _FakeCells({"3.11": CellStatus.FAIL})

    rc = main(project_dir=tmp_path, run_cell=cells)

    assert rc == 1
    assert sorted(cells.seen) == ["3.10", "3.11", "3.12"], "the other versions must still be tested"


def test_an_error_cell_also_fails_the_run(tmp_path: Path) -> None:
    """ERROR (a version whose venv could not be provisioned) fails the run like a FAIL does."""
    _write_pyproject(tmp_path, ["3.10", "3.11"])
    cells = _FakeCells({"3.10": CellStatus.ERROR})

    assert main(project_dir=tmp_path, run_cell=cells) == 1


def test_report_names_each_version_and_its_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.14"])

    main(project_dir=tmp_path, run_cell=_FakeCells({"3.10": CellStatus.FAIL}))

    out = capsys.readouterr()
    assert "3.10" in out.out and "3.14" in out.out
    assert "FAIL" in out.out and "PASS" in out.out


# ---------------------------------------------------------------------------
# End-to-end: the REAL matrix on real interpreters (local_only)
# ---------------------------------------------------------------------------

_E2E_MINORS = ["3.10", "3.11"]  # both are commonly installed; uv fetches them if not
_TOOLS_PRESENT = shutil.which("uv") is not None and shutil.which("pyright") is not None


def _make_project(project: Path, minors: list[str], test_body: str) -> None:
    _write_pyproject(project, minors)
    (project / "src" / "demo").mkdir(parents=True)
    (project / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_e2e.py").write_text(test_body, encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_matrix_all_versions_pass(tmp_path: Path) -> None:
    """The real matrix: two venvs provisioned, pytest+pyright run in each, all green -> exit 0."""
    _make_project(tmp_path, _E2E_MINORS, "def test_ok() -> None:\n    assert True\n")

    rc = main(project_dir=tmp_path, quiet=True)

    assert rc == 0
    for minor in _E2E_MINORS:
        venv = tmp_path / f".venv-{minor}"
        assert (venv / "pyvenv.cfg").is_file(), f"{venv} was not provisioned"


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_a_version_specific_failure_fails_the_run(tmp_path: Path) -> None:
    """A test that only fails on 3.10 makes the run non-zero - the whole point of the matrix."""
    body = "import sys\n\n\ndef test_not_on_310() -> None:\n    assert sys.version_info[:2] != (3, 10)\n"
    _make_project(tmp_path, _E2E_MINORS, body)

    assert main(project_dir=tmp_path, quiet=True) == 1


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_no_classifiers_warns_and_names_the_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No classifiers: one default cell, and a WARNING naming the version actually tested."""
    _make_project(tmp_path, [], "def test_ok() -> None:\n    assert True\n")

    rc = main(project_dir=tmp_path, quiet=True)

    err = capsys.readouterr().err
    assert rc == 0
    assert "WARNING" in err and "classifier" in err.lower()
    # names the concrete version it fell back to (whatever uv provided), e.g. "3.14.5"
    default_version = subprocess.run(
        [str(tmp_path / ".venv" / "bin" / "python"), "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert default_version and default_version in err


# ---------------------------------------------------------------------------
# Cell environment: a cell's subprocesses must resolve the CELL's own tools
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cell_env_puts_the_cells_bin_first_on_path(tmp_path: Path) -> None:
    """A cell's PATH leads with its own venv bin, so console scripts resolve per version.

    Without this the matrix inherits the ambient PATH: a test that shells out to a console
    script (ruff, pip-audit) then fails under `test-all` while passing under `test`, whose
    pytest runs as a ToolAction with the stage runner's env.
    """
    venv = tmp_path / ".venv-3.12"
    env = _cell_env(venv)

    expected_bin = str(venv_python(venv).parent)
    assert env["PATH"].split(os.pathsep)[0] == expected_bin
    assert os.environ.get("PATH", "") in env["PATH"], "the ambient PATH must be kept, not replaced"


@pytest.mark.os_agnostic
def test_cell_env_pins_the_interpreter_for_venv_aware_tools(tmp_path: Path) -> None:
    """VIRTUAL_ENV and PIPAPI_PYTHON_LOCATION name the cell, not whatever was active."""
    venv = tmp_path / ".venv-3.12"
    env = _cell_env(venv)

    assert env["VIRTUAL_ENV"] == str(venv)
    assert env["PIPAPI_PYTHON_LOCATION"] == str(venv_python(venv))


@pytest.mark.os_agnostic
def test_failure_detail_hoists_verdicts_above_trailing_log_noise() -> None:
    """pytest's FAILED lines survive even when stderr chatter fills the tail.

    The suite logs to stderr, so on a real failure the last lines are routine chatter and the
    verdict has scrolled past - which made a genuine matrix failure read as no output at all.
    """
    noise = "\n".join(f"[INFO]: routine chatter {i}" for i in range(_MAX_DETAIL_LINES * 2))
    detail = _tail(f"FAILED tests/test_thing.py::test_the_real_cause\n{noise}")

    assert "FAILED tests/test_thing.py::test_the_real_cause" in detail


# ---------------------------------------------------------------------------
# resolve_workers: the project-level cap on parallel version cells
#
# A project whose suite binds fixed ports or shares one test database cannot pass
# test-all in parallel - the cells break each other. `[tool.scripts.test-all].workers`
# (and the BMK_TEST_ALL_WORKERS env override) let such a project declare `workers = 1`
# once, without changing the default (still parallel) for everyone else.
# ---------------------------------------------------------------------------


def test_resolve_workers_defaults_to_parallel_when_nothing_configured(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12", "3.14"])

    workers = resolve_workers(tmp_path, ["3.10", "3.12", "3.14"], env={})

    assert workers == min(3, os.cpu_count() or 4)


def test_resolve_workers_reads_the_pyproject_setting(tmp_path: Path) -> None:
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.12", "3.14"], 1)

    assert resolve_workers(tmp_path, ["3.10", "3.12", "3.14"], env={}) == 1


def test_resolve_workers_env_override_beats_pyproject(tmp_path: Path) -> None:
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.12", "3.14"], 1)

    workers = resolve_workers(tmp_path, ["3.10", "3.12", "3.14"], env={_WORKERS_ENV: "2"})

    assert workers == 2


def test_resolve_workers_is_capped_at_the_number_of_cells(tmp_path: Path) -> None:
    """A generous `workers = 10` on a two-version project asks for no more than 2 threads."""
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.12"], 10)

    assert resolve_workers(tmp_path, ["3.10", "3.12"], env={}) == 2


@pytest.mark.parametrize("bad_value", [0, -1])
def test_resolve_workers_rejects_less_than_one_from_pyproject(tmp_path: Path, bad_value: int) -> None:
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.12"], bad_value)

    with pytest.raises(SystemExit) as excinfo:
        resolve_workers(tmp_path, ["3.10", "3.12"], env={})
    assert excinfo.value.code == 2


@pytest.mark.parametrize("bad_value", ["0", "-1"])
def test_resolve_workers_rejects_less_than_one_from_env(tmp_path: Path, bad_value: str) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12"])

    with pytest.raises(SystemExit) as excinfo:
        resolve_workers(tmp_path, ["3.10", "3.12"], env={_WORKERS_ENV: bad_value})
    assert excinfo.value.code == 2


def test_resolve_workers_rejects_a_non_integer_env_value(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12"])

    with pytest.raises(SystemExit) as excinfo:
        resolve_workers(tmp_path, ["3.10", "3.12"], env={_WORKERS_ENV: "not-a-number"})
    assert excinfo.value.code == 2


def test_resolve_workers_ignores_a_non_integer_pyproject_value(tmp_path: Path) -> None:
    """A malformed pyproject value degrades to the default rather than aborting the build -
    the same leniency every other `[tool.*]` reader in this project gives a wrong-shaped
    value (see `_toml_config.py`); only an explicit `< 1` is a deliberate instruction and
    raises.
    """
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.12"], "not-a-number")

    workers = resolve_workers(tmp_path, ["3.10", "3.12"], env={})

    assert workers == min(2, os.cpu_count() or 4)


# ---------------------------------------------------------------------------
# Concurrency proof: workers=1 never overlaps two cells; the default still does.
#
# A fake cell records its own entry/exit around a fixed, BOUNDED sleep (never an
# unbounded wait or spin) so the peak number of cells alive at once can be read back
# after the run - proof of serialisation rather than a timing guess.
# ---------------------------------------------------------------------------


class _ConcurrencyProbeCells:
    """Records how many cells were alive at once; each cell holds the slot for a fixed,
    bounded interval so two overlapping cells are actually observed rather than merely
    possible.
    """

    def __init__(self, hold_seconds: float = 0.15) -> None:
        self._hold_seconds = hold_seconds
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrent = 0

    def __call__(self, _project_dir: Path, minor: str, *, quiet: bool = True) -> CellResult:
        _ = quiet
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        time.sleep(self._hold_seconds)  # bounded hold, never an unbounded wait
        with self._lock:
            self._active -= 1
        return CellResult(minor, f"{minor}.0", CellStatus.PASSED)


@pytest.mark.os_agnostic
def test_workers_one_never_lets_two_cells_overlap(tmp_path: Path) -> None:
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.11", "3.12"], 1)
    cells = _ConcurrencyProbeCells()

    rc = main(project_dir=tmp_path, run_cell=cells, env={})

    assert rc == 0
    assert cells.max_concurrent == 1


@pytest.mark.os_agnostic
@pytest.mark.skipif((os.cpu_count() or 1) < 2, reason="needs more than one CPU to show real overlap")
def test_default_workers_still_run_cells_concurrently(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.11", "3.12"])
    cells = _ConcurrencyProbeCells()

    rc = main(project_dir=tmp_path, run_cell=cells, env={})

    assert rc == 0
    assert cells.max_concurrent > 1, "the default must stay parallel"
