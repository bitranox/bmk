"""The coverage helper runs a project's suite across processes when the project's venv has xdist.

End to end: a scratch project's real suite runs through ``run_coverage_tests`` under bmk's own venv
interpreter, which has pytest-xdist and pytest-cov. Nothing is patched; the worker count comes in
through ``BMK_TEST_WORKERS``, the way a user sets it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET  # parses the coverage.xml this test just wrote, never foreign XML
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from bmk.adapters.stagerunner.helpers import _coverage as _coverage_module
from bmk.adapters.stagerunner.helpers._coverage import CoverageConfig, plan_test_workers, run_coverage_tests
from bmk.adapters.stagerunner.helpers._parallel import WORKERS_ENV

_MODULE = """
def kind(n: int) -> str:
    if n < 0:
        return "negative"
    if n == 0:
        return "zero"
    return "positive"


def double(n: int) -> int:
    return n * 2
"""

_TESTS = """
import os
import time
from pathlib import Path

import pytest

from pkg.mod import double, kind

MARKS = Path(__file__).parent / "marks"


def _record(name: str) -> None:
    # One file per test, written once: worker processes never share a file. Windows emulates
    # append as seek-then-write, so concurrent appends to one log lose and tear lines.
    start = time.time()
    time.sleep(0.3)
    MARKS.mkdir(exist_ok=True)
    (MARKS / name).write_text(f"{os.getpid()} {start} {time.time()}", encoding="utf-8")


@pytest.mark.parametrize("n", [-1, 0, 1])
def test_kind(n: int) -> None:
    _record(f"kind{n}")
    assert kind(n) in {"negative", "zero", "positive"}


@pytest.mark.parametrize("n", range(3))
@pytest.mark.xdist_group("db")
def test_db(n: int) -> None:
    _record(f"db{n}")
    assert double(n) == n * 2
"""


def _project(tmp_path: Path, *, extra_toml: str = "") -> Path:
    project = tmp_path / "project"
    (project / "src" / "pkg").mkdir(parents=True)
    (project / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "pkg" / "mod.py").write_text(_MODULE, encoding="utf-8")
    # Two ways the measuring paths could disagree: a module no test imports (coverage run
    # --source reports it at 0%), and a conftest importing the package before any test runs.
    (project / "src" / "pkg" / "unused.py").write_text("def never() -> int:\n    return 1\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "conftest.py").write_text("import pkg.mod  # noqa: F401\n", encoding="utf-8")
    (project / "tests" / "test_mod.py").write_text(_TESTS, encoding="utf-8")
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "pkg"\nversion = "0.1.0"\n\n[tool.coverage.run]\nbranch = true\n{extra_toml}',
        encoding="utf-8",
    )
    return project


def _run(project: Path, workers: str, monkeypatch: pytest.MonkeyPatch) -> tuple[int, dict[str, str]]:
    monkeypatch.setenv(WORKERS_ENV, workers)
    shutil.rmtree(project / "tests" / "marks", ignore_errors=True)
    rc = run_coverage_tests(project_dir=project, python=sys.executable, generate_xml=True, quiet=True)
    root = ET.parse(project / "coverage.xml").getroot()  # noqa: S314 - our own file
    return rc, {key: root.attrib[key] for key in ("lines-covered", "lines-valid", "branches-covered", "branches-valid")}


def _spans(project: Path) -> tuple[set[str], list[tuple[float, float]]]:
    workers: set[str] = set()
    db: list[tuple[float, float]] = []
    for mark in (project / "tests" / "marks").iterdir():
        pid, start, end = mark.read_text(encoding="utf-8").split()
        workers.add(pid)
        if mark.name.startswith("db"):
            db.append((float(start), float(end)))
    return workers, sorted(db)


@pytest.mark.os_agnostic
def test_a_parallel_run_measures_the_same_coverage_as_a_serial_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)

    serial_rc, serial = _run(project, "1", monkeypatch)
    serial_workers, _ = _spans(project)
    parallel_rc, parallel = _run(project, "3", monkeypatch)
    parallel_workers, _ = _spans(project)

    assert (serial_rc, parallel_rc) == (0, 0)
    # Process ids, not PYTEST_XDIST_WORKER: when this suite itself runs under xdist, the inner
    # serial pytest inherits the outer worker's name and would look like an xdist worker.
    assert len(serial_workers) == 1, "workers = 1 runs in one process"
    assert len(parallel_workers) > 1, parallel_workers
    assert not serial_workers & parallel_workers
    assert parallel == serial
    # unused.py is counted in both: 2 of its lines are valid and never run.
    assert int(serial["lines-valid"]) - int(serial["lines-covered"]) == 2, serial


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("addopts", "workers"),
    [
        # workers = 1 is the off switch, also against the project's own -n.
        ("-n 2", "1"),
        # pytest-cov switched off: coverage run cannot see the workers, so the run stays serial.
        ("-n 2 -p no:pytest_cov", "3"),
    ],
    ids=["workers-1", "no-pytest-cov"],
)
def test_an_n_the_project_passes_runs_in_one_process_when_bmk_runs_serially(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, addopts: str, workers: str
) -> None:
    plain = _project(tmp_path / "plain")
    owned = _project(tmp_path / "owned", extra_toml=f'\n[tool.pytest.ini_options]\naddopts = "{addopts}"\n')

    plain_rc, plain_cov = _run(plain, "1", monkeypatch)
    owned_rc, owned_cov = _run(owned, workers, monkeypatch)
    owned_workers, _ = _spans(owned)

    assert (plain_rc, owned_rc) == (0, 0)
    assert len(owned_workers) == 1, owned_workers
    assert owned_cov == plain_cov


@pytest.mark.os_agnostic
def test_tests_sharing_an_xdist_group_never_overlap_in_a_parallel_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)

    rc, _ = _run(project, "3", monkeypatch)
    _, db = _spans(project)

    assert rc == 0
    assert len(db) == 3
    assert all(end <= next_start for (_, end), (next_start, _) in pairwise(db)), db


# --- choosing the worker count ---------------------------------------------------


@pytest.fixture(scope="module")
def bare_python(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A real interpreter with no pytest plugins: a project that has not declared pytest-xdist."""
    venv = tmp_path_factory.mktemp("bare") / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    return str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


@pytest.mark.os_agnostic
def test_a_project_without_xdist_runs_serially_and_is_told_how_to_go_parallel(
    tmp_path: Path, bare_python: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Without the conftest's serial override, so the project setting "auto" is what gets planned.
    env = {key: value for key, value in os.environ.items() if key != WORKERS_ENV}

    workers = plan_test_workers("auto", python=bare_python, env=env, cwd=tmp_path).workers

    assert workers == "1"
    err = capsys.readouterr().err
    assert err.count("pytest-xdist") == 1, err


@pytest.mark.os_agnostic
def test_a_project_with_xdist_gets_the_count_it_asked_for(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workers = plan_test_workers(
        "auto", python=sys.executable, env={**os.environ, WORKERS_ENV: "5"}, cwd=tmp_path
    ).workers

    assert workers == "5"
    assert capsys.readouterr().err == ""


@pytest.mark.os_agnostic
def test_workers_one_never_hints(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A missing interpreter makes the probe answer UNKNOWN; serial must not depend on it.
    workers = plan_test_workers("1", python=str(tmp_path / "absent"), env={}, cwd=tmp_path).workers

    assert workers == "1"
    assert capsys.readouterr().err == ""


@pytest.mark.os_agnostic
def test_the_project_setting_is_read_from_scripts_test(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.scripts.test]\nworkers = 4\n", encoding="utf-8")

    assert CoverageConfig.from_pyproject(tmp_path).workers == "4"


@pytest.mark.os_agnostic
def test_the_default_setting_is_auto(tmp_path: Path) -> None:
    assert CoverageConfig.from_pyproject(tmp_path).workers == "auto"


@pytest.mark.os_agnostic
def test_a_nonsense_project_setting_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.scripts.test]\nworkers = 0\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="workers"):
        CoverageConfig.from_pyproject(tmp_path)


# --- the stage's own invocation --------------------------------------------------------

_HELPER = Path(_coverage_module.__file__)


def _stage(
    project: Path, workers: str, *, output_format: str = "text", **extra_env: str
) -> subprocess.CompletedProcess[str]:
    """Run the helper exactly as the pytest stage does: a subprocess under bmk's interpreter."""
    env = {**os.environ, WORKERS_ENV: workers, **extra_env}
    return subprocess.run(
        [
            sys.executable,
            str(_HELPER),
            "--run",
            "--no-upload",
            "--project-dir",
            str(project),
            "--python",
            sys.executable,
            "--output-format",
            output_format,
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.mark.os_agnostic
def test_a_parallel_run_below_the_floor_fails_like_a_serial_one_with_the_missing_lines(tmp_path: Path) -> None:
    project = _project(tmp_path, extra_toml="\n[tool.coverage.report]\nfail_under = 100\n")

    serial = _stage(project, "1")
    parallel = _stage(project, "3")

    assert serial.returncode == parallel.returncode == 2, (serial.stderr[-800:], parallel.stderr[-800:])
    assert "unused.py" in parallel.stdout, "the report naming the missing lines must still print"


@pytest.mark.os_agnostic
@pytest.mark.parametrize("workers", ["1", "3"], ids=["serial", "parallel"])
def test_a_floor_failure_in_json_mode_prints_the_missing_lines_and_says_it_is_the_floor(
    tmp_path: Path, workers: str
) -> None:
    # JSON is make test's default: the stage runner shows this output only because the stage failed.
    project = _project(tmp_path, extra_toml="\n[tool.coverage.report]\nfail_under = 100\n")

    result = _stage(project, workers, output_format="json")

    assert result.returncode == 2, result.stderr[-800:]
    assert "unused.py" in result.stdout, "the report naming the missing lines must reach the user"
    assert "fail_under = 100" in result.stderr
    assert "Tests failed" not in result.stderr, "every test passed; only the floor failed"


@pytest.mark.os_agnostic
def test_a_passing_json_run_prints_no_coverage_report(tmp_path: Path) -> None:
    result = _stage(_project(tmp_path), "1", output_format="json")

    assert result.returncode == 0, result.stderr[-800:]
    assert "TOTAL" not in result.stdout


@pytest.mark.os_agnostic
def test_plugin_autoload_off_runs_serially_and_passes(tmp_path: Path) -> None:
    project = _project(tmp_path)

    result = _stage(project, "3", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")

    assert result.returncode == 0, result.stdout[-800:] + result.stderr[-800:]
    workers, _ = _spans(project)
    assert len(workers) == 1


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("extra_env", "extra_toml", "named"),
    [
        ({WORKERS_ENV: "lots"}, "", WORKERS_ENV),
        ({}, "\n[tool.scripts.test]\nworkers = 0\n", "workers"),
    ],
    ids=["env", "pyproject"],
)
def test_a_bad_worker_setting_is_one_refusal_line_with_exit_2(
    tmp_path: Path, extra_env: dict[str, str], extra_toml: str, named: str
) -> None:
    project = _project(tmp_path, extra_toml=extra_toml)

    result = _stage(project, extra_env.get(WORKERS_ENV, "auto"))

    assert result.returncode == 2, result.stderr[-800:]
    assert "Traceback" not in result.stderr
    assert named in result.stderr
