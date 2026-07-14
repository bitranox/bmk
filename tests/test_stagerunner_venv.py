"""Tests for project venv resolution and provisioning."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmk.adapters.stagerunner.venv import (
    ensure_project_venv,
    is_venv,
    resolve_project_venv,
    venv_python,
)


def _uv(*args: str) -> int:
    """Run a uv command quietly, returning its exit code (or non-zero if absent)."""
    try:
        return subprocess.run(["uv", *args], capture_output=True, check=False).returncode
    except OSError:
        return 1


def _make_venv(path: Path) -> Path:
    """Create a directory that looks like a venv to the resolver."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyvenv.cfg").write_text("home = /usr\n")
    interpreter = venv_python(path)
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("")
    return path


# ---------------------------------------------------------------------------
# resolve_project_venv
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_resolve_project_venv_defaults_to_dot_venv(tmp_path: Path) -> None:
    """Without UV_PROJECT_ENVIRONMENT, the venv is <cwd>/.venv."""
    assert resolve_project_venv(tmp_path, {}) == tmp_path / ".venv"


@pytest.mark.os_agnostic
def test_resolve_project_venv_honours_relative_override(tmp_path: Path) -> None:
    """A relative UV_PROJECT_ENVIRONMENT resolves against the project dir.

    The bitranox softdev tree is shared between Linux and Windows; .venv is the
    Linux venv, so Windows points this at .venv-win to avoid rebuilding it.
    """
    env = {"UV_PROJECT_ENVIRONMENT": ".venv-win"}

    assert resolve_project_venv(tmp_path, env) == tmp_path / ".venv-win"


@pytest.mark.os_agnostic
def test_resolve_project_venv_honours_absolute_override(tmp_path: Path) -> None:
    """An absolute UV_PROJECT_ENVIRONMENT is used verbatim."""
    target = tmp_path / "elsewhere" / "env"
    env = {"UV_PROJECT_ENVIRONMENT": str(target)}

    assert resolve_project_venv(tmp_path, env) == target


@pytest.mark.os_agnostic
def test_resolve_project_venv_ignores_blank_override(tmp_path: Path) -> None:
    """A blank override falls back to .venv rather than the project dir itself."""
    assert resolve_project_venv(tmp_path, {"UV_PROJECT_ENVIRONMENT": "   "}) == tmp_path / ".venv"


# ---------------------------------------------------------------------------
# is_venv
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_is_venv_requires_pyvenv_cfg(tmp_path: Path) -> None:
    """A bare directory sharing the name is not a venv."""
    (tmp_path / ".venv").mkdir()

    assert is_venv(tmp_path / ".venv") is False


@pytest.mark.os_agnostic
def test_is_venv_accepts_a_real_venv(tmp_path: Path) -> None:
    """A directory with pyvenv.cfg is a venv."""
    assert is_venv(_make_venv(tmp_path / ".venv")) is True


@pytest.mark.os_agnostic
def test_is_venv_false_when_absent(tmp_path: Path) -> None:
    """A missing path is not a venv."""
    assert is_venv(tmp_path / "nope") is False


# ---------------------------------------------------------------------------
# ensure_project_venv
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_ensure_project_venv_skips_without_pyproject(tmp_path: Path) -> None:
    """A directory that is not a Python project gets no venv."""
    assert ensure_project_venv(tmp_path, {}) is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv._run", return_value=0)
def test_ensure_project_venv_syncs_an_existing_venv_without_recreating(mock_run: MagicMock, tmp_path: Path) -> None:
    """An existing venv is updated in place, never recreated.

    Recreating would change nothing about the path but would discard the env and,
    more importantly, `uv venv` must not run while tools are pinned at it.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")

    result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    commands = [call.args[0] for call in mock_run.call_args_list]
    assert not any(cmd[:2] == ["uv", "venv"] for cmd in commands), "must not recreate an existing venv"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv._run", return_value=0)
def test_ensure_project_venv_sync_is_exact_and_upgrading(mock_run: MagicMock, tmp_path: Path) -> None:
    """The sync passes both --exact and --upgrade.

    Neither flag alone makes the venv honest, and each covers a distinct way it
    can drift:

    * without --exact, a package the manifest no longer asks for lingers, and
      pip-audit reports CVEs against something the project does not resolve;
    * without --upgrade, uv keeps any installed version that still satisfies its
      constraint, so a stale *unconstrained* transitive (setuptools via pbr) stays
      on a vulnerable release even though a fresh resolution picks the fixed one.

    A constrained package hides the second gap (a version below its floor is
    upgraded regardless), which is why this asserts the flags rather than relying
    on a constrained example.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")

    ensure_project_venv(tmp_path, {})

    install = mock_run.call_args_list[0].args[0]
    assert install[:3] == ["uv", "pip", "install"]
    assert "--exact" in install
    assert "--upgrade" in install
    assert install[install.index("--python") + 1] == str(venv_python(tmp_path / ".venv"))


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv._run")
def test_ensure_project_venv_falls_back_when_no_dev_extra(mock_run: MagicMock, tmp_path: Path) -> None:
    """Falls back to `.` when the project has no [dev] extra.

    bmk itself has none: its tooling is declared as runtime dependencies.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")
    mock_run.side_effect = [1, 0]  # ".[dev]" fails, "." succeeds

    result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    targets = [call.args[0][-1] for call in mock_run.call_args_list]
    assert targets == [".[dev]", "."]


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv._run", return_value=1)
def test_ensure_project_venv_returns_none_when_sync_fails(_mock_run: MagicMock, tmp_path: Path) -> None:
    """A failed sync degrades to None rather than raising."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")

    assert ensure_project_venv(tmp_path, {}) is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv._run", return_value=1)
def test_ensure_project_venv_returns_none_when_creation_fails(_mock_run: MagicMock, tmp_path: Path) -> None:
    """A failed `uv venv` degrades to None rather than raising."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')

    assert ensure_project_venv(tmp_path, {}) is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv._run", return_value=0)
def test_ensure_project_venv_creates_at_the_override_path(mock_run: MagicMock, tmp_path: Path) -> None:
    """Creation targets the resolved path, not a hardcoded .venv."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    env = {"UV_PROJECT_ENVIRONMENT": ".venv-win"}

    ensure_project_venv(tmp_path, env)

    create = mock_run.call_args_list[0].args[0]
    assert create[:2] == ["uv", "venv"]
    assert create[2] == str(tmp_path / ".venv-win")


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_project_venv_repairs_a_drifted_venv(tmp_path: Path) -> None:
    """End to end: a stale package that still satisfies its constraint is upgraded.

    The regression this guards: --exact alone left such a package untouched, so an
    unconstrained transitive could sit on a vulnerable release indefinitely while
    the gates reported the venv as current.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "drift"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
        'dependencies = ["packaging"]\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    (tmp_path / "drift.py").write_text("")
    if _uv("venv", str(tmp_path / ".venv")) != 0:
        pytest.skip("uv could not create a venv here")
    python = str(venv_python(tmp_path / ".venv"))
    # An old but unconstrained version: it satisfies "packaging" as written.
    if _uv("pip", "install", "--python", python, "packaging==23.0") != 0:
        pytest.skip("uv could not install the drifted package (offline?)")

    if ensure_project_venv(tmp_path, {}) is None:
        pytest.skip("uv could not sync the venv here")

    result = subprocess.run(
        ["uv", "pip", "list", "--python", python, "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    installed = {p["name"]: p["version"] for p in json.loads(result.stdout)}
    assert installed["packaging"] != "23.0", "a stale satisfying version must be upgraded"


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_project_venv_creates_a_real_venv(tmp_path: Path) -> None:
    """End to end: provisions a usable venv for a minimal real project.

    Exercises uv for real, so it is local_only: CI need not have uv on PATH.
    """
    if not os.environ.get("PATH"):  # pragma: no cover - defensive
        pytest.skip("no PATH")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = []\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    (tmp_path / "demo.py").write_text("")

    result = ensure_project_venv(tmp_path, {})

    if result is None:  # uv unavailable or offline
        pytest.skip("uv could not provision a venv here")
    assert is_venv(result)
    assert venv_python(result).exists()
