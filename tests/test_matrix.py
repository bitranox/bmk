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
import sys
import threading
import time
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.helpers._matrix import (
    MAX_DETAIL_LINES,
    WORKERS_ENV,
    CellResult,
    CellStatus,
    cell_env,
    cell_pytest_argv,
    failure_excerpt,
    main,
    pytest_marker_args,
    resolve_workers,
)
from bmk.adapters.stagerunner.helpers._parallel import WORKERS_ENV as TEST_WORKERS_ENV
from bmk.adapters.stagerunner.venv import probe_interpreter, venv_python
from bmk.domain.enums import RefusalKind
from bmk.domain.errors import RefusalError


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
        self.pytest_workers: list[str] = []

    def __call__(self, _project_dir: Path, minor: str, *, quiet: bool = True, pytest_workers: str = "1") -> CellResult:
        _ = quiet
        self.seen.append(minor)
        self.pytest_workers.append(pytest_workers)
        return CellResult(minor, f"{minor}.0", self.statuses.get(minor, CellStatus.PASSED))


def _no_prepare(_project_dir: Path, _minors: list[str], *, quiet: bool = True) -> None:
    """Injected at ``main``'s ``prepare_minors`` seam so the fast tests never touch uv's Python store."""
    _ = quiet


# ---------------------------------------------------------------------------
# Orchestration (fast, offline, injected fake at the run_cell seam)
# ---------------------------------------------------------------------------


def test_all_pass_exits_zero_and_runs_every_declared_version(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12", "3.14"])
    cells = _FakeCells({})

    rc = main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells)

    assert rc == 0
    assert sorted(cells.seen) == ["3.10", "3.12", "3.14"]


def test_any_failure_exits_nonzero_but_every_cell_still_runs(tmp_path: Path) -> None:
    """A break on one version fails the run yet does not stop the others - you want the whole matrix."""
    _write_pyproject(tmp_path, ["3.10", "3.11", "3.12"])
    cells = _FakeCells({"3.11": CellStatus.FAIL})

    rc = main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells)

    assert rc == 1
    assert sorted(cells.seen) == ["3.10", "3.11", "3.12"], "the other versions must still be tested"


def test_an_error_cell_also_fails_the_run(tmp_path: Path) -> None:
    """ERROR (a version whose venv could not be provisioned) fails the run like a FAIL does."""
    _write_pyproject(tmp_path, ["3.10", "3.11"])
    cells = _FakeCells({"3.10": CellStatus.ERROR})

    assert main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells) == 1


def test_report_names_each_version_and_its_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.14"])

    main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=_FakeCells({"3.10": CellStatus.FAIL}))

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


# A type error only Windows sees: on any other platform pyright treats the branch as unreachable,
# and os.getuid does not exist in the Windows stubs. The test itself passes everywhere.
_WINDOWS_ONLY_TYPE_ERROR = (
    "import os\nimport sys\n\n\n"
    "def test_ok() -> None:\n"
    '    if sys.platform == "win32":\n'
    "        assert os.getuid() >= 0\n"
)


def _make_platform_project(project: Path, *, declared_os: list[str] | None) -> None:
    """A one-cell project holding ``_WINDOWS_ONLY_TYPE_ERROR``, with ``[tool.ci].os`` when given."""
    _make_project(project, _E2E_MINORS[:1], _WINDOWS_ONLY_TYPE_ERROR)
    if declared_os is not None:
        pyproject = project / "pyproject.toml"
        listed = ", ".join(f'"{label}"' for label in declared_os)
        pyproject.write_text(pyproject.read_text(encoding="utf-8") + f"[tool.ci]\nos = [{listed}]\n", encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_a_declared_platforms_type_error_fails_the_cell(tmp_path: Path) -> None:
    """Each cell types the code for every OS ``[tool.ci].os`` declares, as ``make test`` does.

    Host-only, a Windows-only type error on an older Python passed test-all and reached CI.
    """
    _make_platform_project(tmp_path, declared_os=["ubuntu-latest", "windows-latest"])

    assert main(project_dir=tmp_path, quiet=True) == 1


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_without_declared_platforms_a_cell_types_for_the_host_only(tmp_path: Path) -> None:
    """The control: the same code with no ``[tool.ci].os`` passes, so the failure above is Windows-only."""
    if os.name == "nt":
        pytest.skip("the host is Windows, where the error is the host's own")
    _make_platform_project(tmp_path, declared_os=None)

    assert main(project_dir=tmp_path, quiet=True) == 0


_MARKED_FAILURE = (
    "import pytest\n\n\n"
    "def test_ok() -> None:\n    assert True\n\n\n"
    "@pytest.mark.{marker}\n"
    "def test_marked_fails() -> None:\n    assert False\n"
)


def _make_marker_project(project: Path, *, marker: str, exclude_markers: str | None) -> None:
    """One-cell project whose only failing test carries ``marker``.

    ``exclude_markers`` is written to ``[tool.scripts.test].exclude-markers`` (``None`` leaves
    the key out, so bmk's default applies). The marker is registered so pytest does not warn.
    """
    _make_project(project, _E2E_MINORS[:1], _MARKED_FAILURE.format(marker=marker))
    extra = f'[tool.pytest.ini_options]\nmarkers = ["{marker}: test marker"]\n'
    if exclude_markers is not None:
        extra += f'[tool.scripts.test]\nexclude-markers = "{exclude_markers}"\n'
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8") + extra, encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_a_projects_exclude_markers_reach_every_cell(tmp_path: Path) -> None:
    """``exclude-markers = "mutating"`` keeps mutating tests out of test-all, as it does in test.

    A project marks host-mutating tests so the gate never runs them; test-all used to hardcode
    ``not integration`` and ran them in every cell.
    """
    _make_marker_project(tmp_path, marker="mutating", exclude_markers="mutating")

    assert main(project_dir=tmp_path, quiet=True) == 0


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_integration_stays_excluded_when_nothing_is_configured(tmp_path: Path) -> None:
    """With no ``exclude-markers`` the default (``integration``) still applies in every cell."""
    _make_marker_project(tmp_path, marker="integration", exclude_markers=None)

    assert main(project_dir=tmp_path, quiet=True) == 0


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_an_empty_exclude_markers_runs_every_test(tmp_path: Path) -> None:
    """``exclude-markers = ""`` filters nothing, as in test, so a failing integration test fails the run."""
    _make_marker_project(tmp_path, marker="integration", exclude_markers="")

    assert main(project_dir=tmp_path, quiet=True) == 1


def _pyproject_with_test_table(project: Path, table: str) -> Path:
    _write_pyproject(project, ["3.12"])
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8") + table, encoding="utf-8")
    return project


@pytest.mark.os_agnostic
def test_marker_args_follow_the_projects_exclude_markers(tmp_path: Path) -> None:
    """The cell filter is the project's ``exclude-markers``, not a fixed ``integration``."""
    project = _pyproject_with_test_table(tmp_path, '[tool.scripts.test]\nexclude-markers = "mutating"\n')

    assert pytest_marker_args(project) == ["-m", "not mutating"]


@pytest.mark.os_agnostic
def test_marker_args_default_to_excluding_integration(tmp_path: Path) -> None:
    """No ``exclude-markers`` key: the same default as ``make test``."""
    _write_pyproject(tmp_path, ["3.12"])

    assert pytest_marker_args(tmp_path) == ["-m", "not integration"]


@pytest.mark.os_agnostic
def test_marker_args_are_empty_when_exclude_markers_is_empty(tmp_path: Path) -> None:
    """An empty ``exclude-markers`` filters nothing, so no ``-m`` at all."""
    project = _pyproject_with_test_table(tmp_path, '[tool.scripts.test]\nexclude-markers = ""\n')

    assert pytest_marker_args(project) == []


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
    env = cell_env(venv)

    expected_bin = str(venv_python(venv).parent)
    assert env["PATH"].split(os.pathsep)[0] == expected_bin
    assert os.environ.get("PATH", "") in env["PATH"], "the ambient PATH must be kept, not replaced"


@pytest.mark.os_agnostic
def test_cell_env_pins_the_interpreter_for_venv_aware_tools(tmp_path: Path) -> None:
    """VIRTUAL_ENV and PIPAPI_PYTHON_LOCATION name the cell, not whatever was active."""
    venv = tmp_path / ".venv-3.12"
    env = cell_env(venv)

    assert env["VIRTUAL_ENV"] == str(venv)
    assert env["PIPAPI_PYTHON_LOCATION"] == str(venv_python(venv))


@pytest.mark.os_agnostic
def test_failure_detail_hoists_verdicts_above_trailing_log_noise() -> None:
    """pytest's FAILED lines survive even when stderr chatter fills the tail.

    The suite logs to stderr, so on a real failure the last lines are routine chatter and the
    verdict has scrolled past - which made a genuine matrix failure read as no output at all.
    """
    noise = "\n".join(f"[INFO]: routine chatter {i}" for i in range(MAX_DETAIL_LINES * 2))
    detail = failure_excerpt(f"FAILED tests/test_thing.py::test_the_real_cause\n{noise}")

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

    workers = resolve_workers(tmp_path, ["3.10", "3.12", "3.14"], env={WORKERS_ENV: "2"})

    assert workers == 2


def test_resolve_workers_is_capped_at_the_number_of_cells(tmp_path: Path) -> None:
    """A generous `workers = 10` on a two-version project asks for no more than 2 threads."""
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.12"], 10)

    assert resolve_workers(tmp_path, ["3.10", "3.12"], env={}) == 2


@pytest.mark.parametrize("bad_value", [0, -1])
def test_resolve_workers_rejects_less_than_one_from_pyproject(tmp_path: Path, bad_value: int) -> None:
    _write_pyproject_with_workers(tmp_path, ["3.10", "3.12"], bad_value)

    with pytest.raises(RefusalError) as excinfo:
        resolve_workers(tmp_path, ["3.10", "3.12"], env={})
    assert excinfo.value.kind is RefusalKind.INVALID_ARGUMENT


@pytest.mark.parametrize("bad_value", ["0", "-1"])
def test_resolve_workers_rejects_less_than_one_from_env(tmp_path: Path, bad_value: str) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12"])

    with pytest.raises(RefusalError) as excinfo:
        resolve_workers(tmp_path, ["3.10", "3.12"], env={WORKERS_ENV: bad_value})
    assert excinfo.value.kind is RefusalKind.INVALID_ARGUMENT


def test_resolve_workers_rejects_a_non_integer_env_value(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12"])

    with pytest.raises(RefusalError) as excinfo:
        resolve_workers(tmp_path, ["3.10", "3.12"], env={WORKERS_ENV: "not-a-number"})
    assert excinfo.value.kind is RefusalKind.INVALID_ARGUMENT


class _PrepareSpy:
    """Records every ``prepare_minors`` call, so a refusal can be shown to come before any install."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, _project_dir: Path, minors: list[str], *, quiet: bool = True) -> None:
        _ = quiet
        self.calls.append(list(minors))


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("env_value", "pyproject_workers", "named"),
    [("0", None, WORKERS_ENV), ("not-a-number", None, WORKERS_ENV), ("", 0, "[tool.scripts.test-all].workers")],
    ids=["env-zero", "env-not-a-number", "pyproject-zero"],
)
def test_main_refuses_a_bad_worker_count_with_exit_2_before_preparing_any_python(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    env_value: str,
    pyproject_workers: int | None,
    named: str,
) -> None:
    """A refused worker count is the helper's exit code, not a SystemExit escaping the stage engine."""
    if pyproject_workers is None:
        _write_pyproject(tmp_path, ["3.10", "3.12"])
    else:
        _write_pyproject_with_workers(tmp_path, ["3.10", "3.12"], pyproject_workers)
    prepare = _PrepareSpy()
    cells = _FakeCells({})

    rc = main(project_dir=tmp_path, prepare_minors=prepare, run_cell=cells, env={WORKERS_ENV: env_value})

    err = capsys.readouterr().err
    assert rc == 2
    assert f"[test-all] {named} must be" in err
    assert prepare.calls == []
    assert cells.seen == []


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

    def __call__(self, _project_dir: Path, minor: str, *, quiet: bool = True, pytest_workers: str = "1") -> CellResult:
        _ = quiet, pytest_workers
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

    rc = main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells, env={})

    assert rc == 0
    assert cells.max_concurrent == 1


@pytest.mark.os_agnostic
@pytest.mark.skipif((os.cpu_count() or 1) < 2, reason="needs more than one CPU to show real overlap")
def test_default_workers_still_run_cells_concurrently(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.11", "3.12"])
    cells = _ConcurrencyProbeCells()

    rc = main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells, env={})

    assert rc == 0
    assert cells.max_concurrent > 1, "the default must stay parallel"


def test_every_minor_is_prepared_once_before_any_cell_starts(tmp_path: Path) -> None:
    """Installing a Python rewrites every minor alias in uv's store (bmk OPEN-WORK [102]).

    Run concurrently with the cells, that pulled the interpreter out from under a cell already
    syncing its venv. So all minors are prepared, serially, before the first cell runs.
    """
    _write_pyproject(tmp_path, ["3.10", "3.12", "3.14"])
    events: list[str] = []

    def prepare(_project_dir: Path, minors: list[str], *, quiet: bool = True) -> None:
        _ = quiet
        events.append("prepare:" + ",".join(minors))

    class _Cells(_FakeCells):
        def __call__(
            self, _project_dir: Path, minor: str, *, quiet: bool = True, pytest_workers: str = "1"
        ) -> CellResult:
            events.append("cell:" + minor)
            return super().__call__(_project_dir, minor, quiet=quiet, pytest_workers=pytest_workers)

    assert main(project_dir=tmp_path, prepare_minors=prepare, run_cell=_Cells({})) == 0
    assert events[0] == "prepare:3.10,3.12,3.14"
    assert sorted(events[1:]) == ["cell:3.10", "cell:3.12", "cell:3.14"]


# ---------------------------------------------------------------------------
# Free-threaded cells: `[tool.ci] free-threaded = ["3.15"]` adds a `3.15t` cell, as in CI
#
# The CI template (default_cicd_public) adds an `X.Yt` job for each entry and refuses an entry
# that is not an "X.Y" string or not a declared classifier. test-all reads the same key and
# refuses the same entries, so the local matrix and the CI matrix cannot disagree.
# ---------------------------------------------------------------------------

_FREE_THREADING_CLASSIFIER = '  "Programming Language :: Python :: Free Threading :: 2 - Beta",\n'


def _write_free_threaded_pyproject(
    project: Path, minors: list[str], free_threaded: str, *, classifier: bool = True
) -> None:
    """``_write_pyproject`` plus ``[tool.ci] free-threaded = <free_threaded>`` (TOML, verbatim)."""
    _write_pyproject(project, minors)
    pyproject = project / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    if classifier:
        text = text.replace("classifiers = [\n", "classifiers = [\n" + _FREE_THREADING_CLASSIFIER, 1)
    pyproject.write_text(text + f"[tool.ci]\nfree-threaded = {free_threaded}\n", encoding="utf-8")


class _RecordingPrepare:
    """Records what ``main`` asked to prepare, so the free-threaded build is shown to be installed too."""

    def __init__(self) -> None:
        self.prepared: list[list[str]] = []

    def __call__(self, _project_dir: Path, minors: list[str], *, quiet: bool = True) -> None:
        _ = quiet
        self.prepared.append(list(minors))


@pytest.mark.os_agnostic
def test_a_free_threaded_entry_adds_its_cell_right_after_the_regular_one(tmp_path: Path) -> None:
    _write_free_threaded_pyproject(tmp_path, ["3.13", "3.14", "3.15"], '["3.13"]')
    cells = _FakeCells({})
    prepare = _RecordingPrepare()

    rc = main(project_dir=tmp_path, prepare_minors=prepare, run_cell=cells, env={})

    assert rc == 0
    assert prepare.prepared == [["3.13", "3.13t", "3.14", "3.15"]]
    assert sorted(cells.seen) == ["3.13", "3.13t", "3.14", "3.15"]


@pytest.mark.os_agnostic
def test_the_report_names_the_free_threaded_cell(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_free_threaded_pyproject(tmp_path, ["3.15"], '["3.15"]')

    main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=_FakeCells({"3.15t": CellStatus.FAIL}), env={})

    out = capsys.readouterr().out
    assert "3.15t" in out
    assert "FAIL" in out


@pytest.mark.os_agnostic
def test_a_failing_free_threaded_cell_fails_the_run(tmp_path: Path) -> None:
    _write_free_threaded_pyproject(tmp_path, ["3.14", "3.15"], '["3.15"]')

    rc = main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=_FakeCells({"3.15t": CellStatus.FAIL}), env={})

    assert rc == 1


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("free_threaded", "named"),
    [
        ('["3.15t"]', "'3.15t'"),
        ("[3]", "3"),
        ('["3"]', "'3'"),
        ('["3.16"]', "3.16"),
        ('"3.15"', "array"),
    ],
    ids=["t-suffix", "not-a-string", "no-minor", "not-declared", "not-an-array"],
)
def test_a_free_threaded_entry_ci_refuses_is_refused_before_anything_is_installed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], free_threaded: str, named: str
) -> None:
    _write_free_threaded_pyproject(tmp_path, ["3.14", "3.15"], free_threaded)
    cells = _FakeCells({})
    prepare = _RecordingPrepare()

    rc = main(project_dir=tmp_path, prepare_minors=prepare, run_cell=cells, env={})

    assert rc == 2
    assert prepare.prepared == []
    assert cells.seen == []
    err = capsys.readouterr().err
    assert "[tool.ci] free-threaded" in err
    assert named in err


@pytest.mark.os_agnostic
def test_a_free_threaded_entry_without_any_classifier_is_refused(tmp_path: Path) -> None:
    """CI refuses it (no declared version to match), so test-all must not fall back to one default cell."""
    _write_free_threaded_pyproject(tmp_path, [], '["3.15"]', classifier=False)

    assert main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=_FakeCells({}), env={}) == 2


@pytest.mark.os_agnostic
def test_free_threaded_without_its_trove_classifier_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_free_threaded_pyproject(tmp_path, ["3.15"], '["3.15"]', classifier=False)

    rc = main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=_FakeCells({}), env={})

    assert rc == 0
    assert "Free Threading" in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_free_threaded_with_its_trove_classifier_does_not_warn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_free_threaded_pyproject(tmp_path, ["3.15"], '["3.15"]')

    main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=_FakeCells({}), env={})

    assert "Free Threading" not in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_an_empty_free_threaded_list_changes_nothing(tmp_path: Path) -> None:
    _write_free_threaded_pyproject(tmp_path, ["3.14", "3.15"], "[]", classifier=False)
    cells = _FakeCells({})

    assert main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells, env={}) == 0
    assert sorted(cells.seen) == ["3.14", "3.15"]


@pytest.mark.os_agnostic
@pytest.mark.local_only
@pytest.mark.skipif(not _TOOLS_PRESENT, reason="needs uv + pyright")
def test_e2e_the_free_threaded_cell_runs_on_the_free_threaded_build(tmp_path: Path) -> None:
    """The real matrix: `.venv-3.15t` is provisioned on the GIL-free build, `.venv-3.15` on the GIL one."""
    _make_project(tmp_path, ["3.15"], "def test_ok() -> None:\n    assert True\n")
    pyproject = tmp_path / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8").replace(
        "classifiers = [\n", "classifiers = [\n" + _FREE_THREADING_CLASSIFIER, 1
    )
    pyproject.write_text(text + '[tool.ci]\nfree-threaded = ["3.15"]\n', encoding="utf-8")

    rc = main(project_dir=tmp_path, quiet=True)

    assert rc == 0
    regular = probe_interpreter(tmp_path / ".venv-3.15")
    free_threaded = probe_interpreter(tmp_path / ".venv-3.15t")
    assert regular is not None and not regular.gil_disabled
    assert free_threaded is not None and free_threaded.gil_disabled


# ---------------------------------------------------------------------------
# Parallel pytest inside each cell: the cells share the CPUs instead of each taking all of them
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_each_cell_gets_its_share_of_the_cpus_so_the_matrix_never_oversubscribes(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.11", "3.12", "3.13"])
    cells = _FakeCells({})
    cpus = os.cpu_count() or 1
    at_once = min(4, cpus)

    assert main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells, env={}) == 0

    assert cells.pytest_workers == [str(max(1, cpus // at_once))] * 4
    assert int(cells.pytest_workers[0]) * at_once <= max(cpus, at_once)


@pytest.mark.os_agnostic
def test_an_explicit_pytest_worker_count_reaches_every_cell_unchanged(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12"])
    cells = _FakeCells({})

    assert main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells, env={TEST_WORKERS_ENV: "3"}) == 0

    assert cells.pytest_workers == ["3", "3"]


@pytest.mark.os_agnostic
def test_a_bad_pytest_worker_count_is_refused_with_exit_2_before_any_cell_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_pyproject(tmp_path, ["3.10", "3.12"])
    cells = _FakeCells({})

    rc = main(project_dir=tmp_path, prepare_minors=_no_prepare, run_cell=cells, env={TEST_WORKERS_ENV: "lots"})

    assert rc == 2
    assert TEST_WORKERS_ENV in capsys.readouterr().err
    assert cells.seen == []


@pytest.mark.os_agnostic
def test_a_cell_runs_pytest_across_workers_when_its_venv_has_xdist(tmp_path: Path) -> None:
    # bmk's own venv interpreter has pytest-xdist; a real probe decides, nothing is patched.
    argv = cell_pytest_argv(Path(sys.executable), tmp_path, pytest_workers="3", env=dict(os.environ))

    assert argv[:3] == [sys.executable, "-m", "pytest"]
    assert argv[3:7] == ["-n", "3", "--dist", "loadgroup"]


@pytest.mark.os_agnostic
def test_a_cell_without_xdist_runs_pytest_in_one_process(tmp_path: Path) -> None:
    venv = tmp_path / "bare"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)

    argv = cell_pytest_argv(venv_python(venv), tmp_path, pytest_workers="3", env=dict(os.environ))

    assert "-n" not in argv


@pytest.mark.os_agnostic
def test_one_pytest_worker_never_asks_the_interpreter(tmp_path: Path) -> None:
    argv = cell_pytest_argv(tmp_path / "absent-python", tmp_path, pytest_workers="1", env={})

    assert "-n" not in argv
