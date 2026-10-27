"""Parallel pytest: the worker setting, the xdist probe, and the arguments they turn into.

The probe runs a REAL interpreter and lets pytest read a REAL configuration: bmk's own venv has
both plugins, a bare venv has neither, and each scratch project's ``pytest.ini`` or the environment
says what the run will see. Nothing is patched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner.helpers._parallel import (
    WORKERS_ENV,
    ParallelSupport,
    PytestPlugins,
    normalise_workers,
    probe_parallel,
    resolve_test_workers,
    split_workers,
    xdist_args,
)
from bmk.domain.errors import RefusalError

if TYPE_CHECKING:
    from pathlib import Path

# --- the setting ---------------------------------------------------------------


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("raw", "expected"), [("auto", "auto"), ("AUTO", "auto"), (4, "4"), ("4", "4"), (1, "1")])
def test_a_worker_count_is_auto_or_a_positive_number(raw: object, expected: str) -> None:
    assert normalise_workers(raw) == expected


@pytest.mark.os_agnostic
@pytest.mark.parametrize("raw", [0, -2, "0", "many", "", True, 2.5, None])
def test_anything_else_is_refused(raw: object) -> None:
    with pytest.raises(ValueError, match="workers"):
        normalise_workers(raw)


@pytest.mark.os_agnostic
def test_the_environment_beats_the_project_setting() -> None:
    assert resolve_test_workers("auto", env={WORKERS_ENV: "1"}) == "1"
    assert resolve_test_workers("3", env={}) == "3"
    assert resolve_test_workers("3", env={WORKERS_ENV: "  "}) == "3"


@pytest.mark.os_agnostic
def test_a_bad_environment_value_is_a_refusal_naming_the_variable() -> None:
    with pytest.raises(RefusalError, match=WORKERS_ENV):
        resolve_test_workers("auto", env={WORKERS_ENV: "lots"})


# --- the arguments ---------------------------------------------------------------


@pytest.mark.os_agnostic
def test_one_worker_means_no_xdist_arguments_at_all() -> None:
    assert xdist_args("1", project=PytestPlugins()) == []


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("xdist_loaded", "project_workers", "expected"),
    [
        (True, True, ["-n", "0"]),
        (True, False, []),
        # Without xdist loaded pytest rejects -n, and the project cannot be passing one.
        (False, True, []),
        (False, False, []),
    ],
)
def test_one_worker_overrides_an_n_the_project_passes_itself(
    *, xdist_loaded: bool, project_workers: bool, expected: list[str]
) -> None:
    # workers = 1 means one process, also against `-n` in the project's addopts: the last -n on
    # the command line wins, and -n 0 makes xdist run nothing in parallel.
    plugins = PytestPlugins(xdist_installed=xdist_loaded, xdist_loaded=xdist_loaded, project_workers=project_workers)

    assert xdist_args("1", project=plugins) == expected


@pytest.mark.os_agnostic
def test_parallel_runs_keep_each_xdist_group_on_one_worker() -> None:
    # loadgroup sends every test marked @pytest.mark.xdist_group("<name>") to the same worker,
    # one after another: the way a project keeps its test database out of the parallel part.
    assert xdist_args("auto", project=PytestPlugins()) == ["-n", "auto", "--dist", "loadgroup"]
    assert xdist_args("6", project=PytestPlugins()) == ["-n", "6", "--dist", "loadgroup"]


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("workers", "cells", "cpus", "expected"),
    [
        ("auto", 4, 16, "4"),  # the CPUs are shared between the cells running at once
        ("auto", 6, 16, "2"),
        ("auto", 20, 16, "1"),  # never below one
        ("auto", 3, None, "1"),  # unknown CPU count: stay serial rather than guess
        ("3", 4, 16, "3"),  # an explicit count is the project's own decision
    ],
)
def test_test_all_splits_auto_workers_between_the_cells(
    workers: str, cells: int, cpus: int | None, expected: str
) -> None:
    assert split_workers(workers, cells=cells, cpus=cpus) == expected


# --- the probe: what the project's own pytest loads ----------------------------------
#
# The probe runs pytest's real configuration in the project's interpreter and directory, so it sees
# what the run will see: plugin autoload switched off, a plugin blocked in addopts, an -n or --dist
# the project already passes. bmk's own venv has pytest, pytest-xdist and pytest-cov installed.


def _project(tmp_path: Path, pytest_ini: str = "") -> Path:
    project = tmp_path / "project"
    project.mkdir()
    table = f"\n[tool.pytest.ini_options]\n{pytest_ini}\n" if pytest_ini else ""
    (project / "pyproject.toml").write_text(f'[project]\nname = "p"\nversion = "0"\n{table}', encoding="utf-8")
    return project


def _env(**extra: str) -> dict[str, str]:
    # The whole environment, not a fresh dict: Windows needs SystemRoot to start any child at all.
    return {**os.environ, **extra}


@pytest.fixture(scope="module")
def bare_python(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A real interpreter with nothing installed: a project that never declared any pytest plugin."""
    venv = tmp_path_factory.mktemp("bare") / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    return str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


@pytest.mark.os_agnostic
def test_a_venv_with_both_plugins_is_ready(tmp_path: Path) -> None:
    plugins = probe_parallel(sys.executable, env=_env(), cwd=_project(tmp_path))

    assert plugins.support is ParallelSupport.READY
    assert not plugins.project_workers
    assert not plugins.project_dist


@pytest.mark.os_agnostic
def test_a_venv_without_xdist_says_so_and_names_the_package(tmp_path: Path, bare_python: str) -> None:
    plugins = probe_parallel(bare_python, env=_env(), cwd=_project(tmp_path))

    assert plugins.support is ParallelSupport.NO_XDIST
    assert plugins.missing == "pytest-xdist"


@pytest.mark.os_agnostic
def test_xdist_installed_but_autoload_off_is_disabled_not_ready(tmp_path: Path) -> None:
    plugins = probe_parallel(sys.executable, env=_env(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"), cwd=_project(tmp_path))

    assert plugins.support is ParallelSupport.DISABLED
    assert plugins.missing is None, "installed but switched off: nothing to add"


@pytest.mark.os_agnostic
def test_xdist_blocked_in_the_project_addopts_is_disabled(tmp_path: Path) -> None:
    project = _project(tmp_path, 'addopts = "-p no:xdist"')

    assert probe_parallel(sys.executable, env=_env(), cwd=project).support is ParallelSupport.DISABLED


@pytest.mark.os_agnostic
def test_an_n_the_project_already_passes_is_left_to_the_project(tmp_path: Path) -> None:
    plugins = probe_parallel(sys.executable, env=_env(), cwd=_project(tmp_path, 'addopts = "-n 2"'))

    assert plugins.project_workers
    assert xdist_args("4", project=plugins) == []


@pytest.mark.os_agnostic
def test_a_dist_mode_the_project_chose_is_kept(tmp_path: Path) -> None:
    plugins = probe_parallel(sys.executable, env=_env(), cwd=_project(tmp_path, 'addopts = "--dist loadfile"'))

    assert plugins.project_dist
    assert xdist_args("4", project=plugins) == ["-n", "4"]


@pytest.mark.os_agnostic
def test_an_interpreter_that_cannot_run_is_unknown_not_missing_a_plugin(tmp_path: Path) -> None:
    plugins = probe_parallel(str(tmp_path / "no-python"), env={}, cwd=tmp_path)

    assert plugins.support is ParallelSupport.UNKNOWN
    assert plugins.missing is None


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("facts", "support", "missing"),
    [
        ({"xdist_installed": True, "xdist_loaded": True, "cov_installed": True, "cov_loaded": True}, "READY", None),
        ({"xdist_installed": True, "xdist_loaded": True}, "XDIST_ONLY", "pytest-cov"),
        ({"xdist_installed": True, "xdist_loaded": True, "cov_installed": True}, "XDIST_ONLY", None),
        ({"cov_installed": True, "cov_loaded": True}, "NO_XDIST", "pytest-xdist"),
        ({"xdist_installed": True}, "DISABLED", None),
    ],
)
def test_the_facts_decide_the_support_and_the_hint(facts: dict[str, bool], support: str, missing: str | None) -> None:
    plugins = PytestPlugins(**facts)

    assert plugins.support is ParallelSupport[support]
    assert plugins.missing == missing
