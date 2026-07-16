"""Tests for the version matrix helper (`test-all`).

Two layers, no patching of internals:

* Fast/offline: the orchestration (fan-out, aggregation, exit code) is tested by INJECTING a
  real fake cell-runner at ``main``'s ``run_cell`` seam - not by monkeypatching module globals.
* ``local_only`` end-to-end: the real thing - real uv venvs on real Python minors, real pytest
  and pyright - is the proof of the contract. It runs in ``make test`` and skips cleanly when
  uv / pyright / the interpreters are absent (so CI, which lacks them, skips it).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.helpers._matrix import CellResult, CellStatus, main


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
