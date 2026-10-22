"""End to end: a 3.10 matrix venv that ``uv sync`` recreates comes back whole, against the REAL uv.

``uv sync`` removes and recreates an existing venv when its ``pyvenv.cfg`` ``version_info`` differs
from what the interpreter reports - the state an old uv's venv is in once the minor alias moves to a
new patch. It recreates it from the ``--python`` interpreter's ``sys._base_executable``, and on
CPython <= 3.10 a venv reports its OWN ``bin/python`` there, already deleted at that point: asked for
that path, uv fails with ``failed to canonicalize path`` and leaves an empty directory (bmk OPEN-WORK
[19]). uv's interpreter cache can hide this, so the cache is test-owned and cleared before the sync.

The state is built by hand, never by moving an alias: only ``version_info`` is rewritten to an older
patch than the interpreter reports. uv's shared Python store is only read (``install_python=False``,
no downloads), and everything written lives under ``tmp_path``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.venv import ensure_project_venv_at, venv_python

_MINOR = "3.10"

_PYPROJECT = """\
[project]
name = "recreate-demo"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []
"""

_VERSION_INFO = re.compile(r"^version_info = .*$", re.MULTILINE)

pytestmark = [
    pytest.mark.os_agnostic,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed"),
]


def _python_says(python: Path, code: str) -> str:
    """What ``python -c code`` prints, stripped; empty when it cannot run."""
    try:
        done = subprocess.run([str(python), "-c", code], capture_output=True, text=True, encoding="utf-8", check=False)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


@pytest.fixture
def offline_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A dependency-free project, with uv offline, never downloading, and its cache and the venv locks under tmp_path."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("BMK_VENV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    found = subprocess.run(["uv", "python", "find", _MINOR], capture_output=True, check=False)
    if found.returncode != 0:
        pytest.skip(f"uv finds no CPython {_MINOR} offline (`uv python find {_MINOR}` exit {found.returncode})")
    return project


def _age_version_info(venv: Path, interpreter_version: str) -> str:
    """Make ``pyvenv.cfg`` claim an older patch than the interpreter, as an old uv's venv does after a patch move.

    Returns the aged ``version_info`` line, so the caller can check uv's recreate replaced it.
    """
    major, minor, patch = (int(part) for part in interpreter_version.split("."))
    if patch == 0:
        pytest.skip(f"the venv's interpreter is {interpreter_version}: there is no older patch to claim")
    cfg = venv / "pyvenv.cfg"
    aged = f"version_info = {major}.{minor}.{patch - 1}"
    text, count = _VERSION_INFO.subn(aged, cfg.read_text(encoding="utf-8"))
    assert count == 1, f"one version_info line expected in {cfg}"
    cfg.write_text(text, encoding="utf-8")
    return aged


def test_a_310_venv_that_uv_sync_recreates_is_rebuilt_whole(
    offline_project: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    venv = offline_project / f".venv-{_MINOR}"
    assert ensure_project_venv_at(offline_project, venv, _MINOR, install_python=False) == venv
    python = venv_python(venv)
    base = _python_says(python, "import sys; print(sys._base_executable)")
    if not base or not Path(base).is_relative_to(venv):
        pytest.skip(
            f"precondition absent: this CPython {_MINOR} venv reports sys._base_executable {base!r}, "
            "outside the venv, so uv's recreate never asks for a deleted interpreter here"
        )
    version = _python_says(python, "import platform; print(platform.python_version())")
    aged = _age_version_info(venv, version)
    shutil.rmtree(tmp_path / "uv-cache")
    capfd.readouterr()

    assert ensure_project_venv_at(offline_project, venv, _MINOR, install_python=False) == venv

    err = capfd.readouterr().err
    assert "[venv] uv sync from uv.lock failed" not in err, err
    assert _python_says(venv_python(venv), "import platform; print(platform.python_version())") == version
    # The aged line surviving would mean uv never recreated the venv, so this test would pass on the
    # unfixed code too (a uv that stops recreating, or a second matching interpreter on the runner).
    assert aged not in (venv / "pyvenv.cfg").read_text(encoding="utf-8"), "uv sync did not recreate the venv"


def test_a_310_venv_without_a_declared_minor_that_uv_sync_recreates_is_rebuilt_whole(
    offline_project: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No classifier (``minor=None``): the sync must still ask uv for a minor, never the venv's own interpreter.

    ``UV_PYTHON`` makes uv's default choice a 3.10, so ``uv venv`` with no ``--python`` builds the
    venv the trap needs; the request bmk then sends ``uv sync`` is what decides whether the recreate
    survives.
    """
    monkeypatch.setenv("UV_PYTHON", _MINOR)
    venv = offline_project / ".venv"
    assert ensure_project_venv_at(offline_project, venv, None, install_python=False) == venv
    python = venv_python(venv)
    version = _python_says(python, "import platform; print(platform.python_version())")
    if not version.startswith(f"{_MINOR}."):
        pytest.skip(f"UV_PYTHON={_MINOR} did not give uv venv a {_MINOR} interpreter (got {version!r})")
    base = _python_says(python, "import sys; print(sys._base_executable)")
    if not base or not Path(base).is_relative_to(venv):
        pytest.skip(
            f"precondition absent: this CPython {_MINOR} venv reports sys._base_executable {base!r}, "
            "outside the venv, so uv's recreate never asks for a deleted interpreter here"
        )
    aged = _age_version_info(venv, version)
    shutil.rmtree(tmp_path / "uv-cache")
    capfd.readouterr()

    assert ensure_project_venv_at(offline_project, venv, None, install_python=False) == venv

    err = capfd.readouterr().err
    assert "[venv] uv sync from uv.lock failed" not in err, err
    assert _python_says(venv_python(venv), "import platform; print(platform.python_version())") == version
    assert aged not in (venv / "pyvenv.cfg").read_text(encoding="utf-8"), "uv sync did not recreate the venv"
