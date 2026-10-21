"""Tests for project venv resolution and provisioning."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmk.adapters.stagerunner.helpers import _matrix
from bmk.adapters.stagerunner.helpers._matrix import CellStatus
from bmk.adapters.stagerunner.venv import (
    _lock_argv,
    _refresh_refused,
    ensure_project_venv,
    ensure_project_venv_at,
    ensure_venv_ignored,
    is_venv,
    lock_project,
    resolve_project_venv,
    venv_python,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping


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
# ensure_project_venv_at - provisioning at an explicit path on an explicit minor
# (the matrix building block; `test-all` calls it once per declared version)
# ---------------------------------------------------------------------------


def _run_that_creates_venv_on_uv_venv(*, lock_rc: int = 0, sync_rc: int = 0) -> MagicMock:
    """A `_run` mock that materializes the venv when it sees `uv venv <path>`.

    Without this the create path returns None (is_venv stays False under a pure mock),
    so the install/sync argv is never reached. The side effect makes the flow realistic.
    ``lock_rc`` / ``sync_rc`` are what ``uv lock`` / ``uv sync`` answer.
    """

    def side_effect(argv: list[str], _cwd: Path, *, quiet: bool = True, env: object = None) -> int:
        _ = quiet, env  # matches _run's real signature
        if argv[:2] == ["uv", "venv"]:
            _make_venv(Path(argv[-1]))
        if argv[:2] == ["uv", "lock"]:
            return lock_rc
        if argv[:2] == ["uv", "sync"]:
            return sync_rc
        return 0

    mock = MagicMock(side_effect=side_effect)
    return mock


def _commands(mock_run: MagicMock) -> list[list[str]]:
    return [c.args[0] for c in mock_run.call_args_list]


@contextmanager
def _faked_uv(run: MagicMock) -> Generator[MagicMock, None, None]:
    """Patch both of venv.py's uv runners with ``run``, the one fake a test inspects.

    ``uv sync`` goes through ``_run_keeping_stderr`` (its stderr is reported on failure), every
    other provisioning call through ``_run``; routing both into ``run`` keeps a single command
    list, and keeps a mock-based test from reaching the real uv for the sync.
    """

    def keeping_stderr(
        argv: list[str], cwd: Path, *, quiet: bool, env: Mapping[str, str] | None = None
    ) -> tuple[int, str]:
        return run(argv, cwd, quiet=quiet, env=env), ""

    with (
        patch("bmk.adapters.stagerunner.venv._run", run),
        patch("bmk.adapters.stagerunner.venv._run_keeping_stderr", keeping_stderr),
    ):
        yield run


@pytest.mark.os_agnostic
def test_ensure_at_creates_the_named_venv_on_the_named_minor(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv-3.12"
    mock_run = _run_that_creates_venv_on_uv_venv()

    # uv offers a newer 3.12 patch, so install/upgrade have work to do; when it offers none
    # they are skipped (see test_stagerunner_venv_python.py, bmk OPEN-WORK [102]).
    newer_on_offer = (
        '[{"version": "3.12.16", "version_parts": {"major": 3, "minor": 12, "patch": 16}, '
        '"implementation": "cpython", "path": null}]'
    )
    with (
        _faked_uv(mock_run),
        patch("bmk.adapters.stagerunner.venv._run_capture", return_value=newer_on_offer),
    ):
        result = ensure_project_venv_at(tmp_path, target, "3.12")

    assert result == target
    cmds = [c.args[0] for c in mock_run.call_args_list]
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "--python" in create and "3.12" in create and str(target) in create
    assert ["uv", "python", "install", "3.12"] in cmds
    assert ["uv", "python", "upgrade", "3.12"] in cmds
    sync = next(c for c in cmds if c[:2] == ["uv", "sync"])
    assert sync[sync.index("--python") + 1] == str(venv_python(target))


@pytest.mark.os_agnostic
def test_ensure_at_can_leave_uv_s_python_store_alone(tmp_path: Path) -> None:
    """test-all prepares every minor serially, then its cells must not install again.

    A cell whose prep did not converge (offline, python-downloads = never) would otherwise run
    install/upgrade in parallel with its siblings' syncs: the alias rewrite of bmk OPEN-WORK [102].
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv-3.12"
    mock_run = _run_that_creates_venv_on_uv_venv()
    newer_on_offer = (
        '[{"version": "3.12.16", "version_parts": {"major": 3, "minor": 12, "patch": 16}, '
        '"implementation": "cpython", "path": null}]'
    )
    with (
        _faked_uv(mock_run),
        patch("bmk.adapters.stagerunner.venv._run_capture", return_value=newer_on_offer),
    ):
        result = ensure_project_venv_at(tmp_path, target, "3.12", install_python=False)

    assert result == target
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert not any(c[:2] == ["uv", "python"] and c[2] in ("install", "upgrade") for c in cmds)
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "3.12" in create, "the cell still pins its own minor"


@pytest.mark.os_agnostic
def test_a_test_all_cell_never_installs_a_python(tmp_path: Path) -> None:
    """The cell itself must pass install_python=False; main() already prepared every minor."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    newer_on_offer = (
        '[{"version": "3.12.16", "version_parts": {"major": 3, "minor": 12, "patch": 16}, '
        '"implementation": "cpython", "path": null}]'
    )
    # every uv call fails, so the cell stops at ERROR before it would run pytest in a venv
    mock_run = MagicMock(return_value=1)
    with (
        _faked_uv(mock_run),
        patch("bmk.adapters.stagerunner.venv._run_capture", return_value=newer_on_offer),
    ):
        result = _matrix._run_cell(tmp_path, "3.12", quiet=True)

    assert result.status is CellStatus.ERROR
    cmds = [c.args[0] for c in mock_run.call_args_list]
    assert any(c[:2] == ["uv", "venv"] for c in cmds), "the cell must have reached provisioning"
    assert not any(c[:2] == ["uv", "python"] for c in cmds)


# --- the venv is built FROM uv.lock (user decision 2026-10-12, review M3 of 064688b) ---------------
# `uv pip install --upgrade` keeps an installed release newer than the [tool.uv] cooldown (measured:
# ruff 0.17.0 stayed), so make test checked a different tree from the one uv.lock pins and CI installs.


@pytest.mark.os_agnostic
def test_the_project_is_locked_and_the_venv_synced_from_the_lock(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv-3.12"
    mock_run = _run_that_creates_venv_on_uv_venv()

    with _faked_uv(mock_run):
        assert ensure_project_venv_at(tmp_path, target, "3.12") == target

    cmds = _commands(mock_run)
    assert cmds.index(["uv", "lock"]) < next(i for i, c in enumerate(cmds) if c[:2] == ["uv", "sync"])
    assert not any(c[:3] == ["uv", "pip", "install"] for c in cmds)
    [sync_call] = [c for c in mock_run.call_args_list if c.args[0][:2] == ["uv", "sync"]]
    assert "--locked" in sync_call.args[0]
    # uv sync targets the project environment, so the matrix venv is named through the env.
    assert sync_call.kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(target)
    assert "VIRTUAL_ENV" not in sync_call.kwargs["env"]


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("extras", "expected"), [("", []), ('[project.optional-dependencies]\ndev = ["pytest"]\n', ["--extra", "dev"])]
)
def test_the_dev_extra_is_synced_only_when_the_project_declares_it(
    tmp_path: Path, extras: str, expected: list[str]
) -> None:
    # uv refuses an undeclared extra outright (exit 2), unlike pip's warning.
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "demo"\n{extras}')
    mock_run = _run_that_creates_venv_on_uv_venv()

    with _faked_uv(mock_run):
        ensure_project_venv_at(tmp_path, tmp_path / ".venv", None)

    sync = next(c for c in _commands(mock_run) if c[:2] == ["uv", "sync"])
    assert [a for a in sync if a in ("--extra", "dev")] == expected


@pytest.mark.os_agnostic
def test_without_a_lock_the_venv_falls_back_to_the_manifest_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    mock_run = _run_that_creates_venv_on_uv_venv(lock_rc=1)

    with _faked_uv(mock_run):
        assert ensure_project_venv_at(tmp_path, tmp_path / ".venv", None) == tmp_path / ".venv"

    cmds = _commands(mock_run)
    assert any(c[:3] == ["uv", "pip", "install"] for c in cmds)
    assert not any(c[:2] == ["uv", "sync"] for c in cmds)
    assert "uv lock" in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_a_failed_sync_from_a_good_lock_is_not_papered_over_by_the_manifest_install(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    mock_run = _run_that_creates_venv_on_uv_venv(sync_rc=1)

    with _faked_uv(mock_run):
        assert ensure_project_venv_at(tmp_path, tmp_path / ".venv", None) is None

    assert not any(c[:3] == ["uv", "pip", "install"] for c in _commands(mock_run))
    assert "uv sync" in capsys.readouterr().err


# --- a failed `uv sync` keeps uv's own reason (bmk OPEN-WORK [19]) ------------------------------------
# The sync used to run with stderr discarded in JSON mode and only hinted at a text-mode re-run, which
# then passed: the intermittent 3.10 test-all failure never left its cause behind. The seam is the
# external edge, a stub `uv` executable first on PATH, so the real module runs the real subprocess.

_SYNC_MARKER = "stub-uv-sync-error-7f3a"

# What the stub's `uv sync` leaves behind before it exits 1, and the state the failure line must name.
_SYNC_AFTERMATH = {
    "venv": ":",
    "directory without pyvenv.cfg": 'rm -f "$UV_PROJECT_ENVIRONMENT/pyvenv.cfg"',
    "empty directory": 'rm -rf "$UV_PROJECT_ENVIRONMENT" && mkdir "$UV_PROJECT_ENVIRONMENT"',
    "absent": 'rm -rf "$UV_PROJECT_ENVIRONMENT"',
}


def _install_stub_uv(bin_dir: Path, *, sync_rc: int, aftermath: str = ":") -> None:
    """Write a POSIX ``uv`` that answers every subcommand provisioning reaches.

    ``uv venv <path>`` makes a venv-shaped directory, ``uv lock`` and ``uv python ...`` succeed
    (``list`` answers an empty JSON list), and ``uv sync`` runs ``aftermath`` against
    ``UV_PROJECT_ENVIRONMENT``, prints :data:`_SYNC_MARKER` on stderr and exits ``sync_rc``.
    The sync refuses (exit 97) a target outside ``bin_dir``'s parent, so a ``rm -rf`` aftermath
    can never reach an inherited ``UV_PROJECT_ENVIRONMENT`` if bmk stopped passing its own.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "uv"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  venv)\n"
        "    for last; do :; done\n"
        '    mkdir -p "$last/bin" && echo "home = /usr" > "$last/pyvenv.cfg" && : > "$last/bin/python"\n'
        "    exit 0 ;;\n"
        "  python)\n"
        '    [ "$2" = list ] && echo "[]"\n'
        "    exit 0 ;;\n"
        "  lock) exit 0 ;;\n"
        "  sync)\n"
        f'    case "$UV_PROJECT_ENVIRONMENT" in "{bin_dir.parent}"/*) ;; *) exit 97 ;; esac\n'
        f"    {aftermath}\n"
        '    echo "Resolved 3 packages" >&2\n'
        f'    echo "error: {_SYNC_MARKER}" >&2\n'
        f"    exit {sync_rc} ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)


@pytest.fixture
def stub_uv_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project dir with the stub ``uv`` first on PATH and the venv locks kept under tmp_path."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("BMK_VENV_LOCK_DIR", str(tmp_path / "locks"))
    return project


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
@pytest.mark.parametrize("state", list(_SYNC_AFTERMATH))
@pytest.mark.parametrize("quiet", [True, False], ids=["json-mode", "text-mode"])
def test_a_failed_sync_prints_uv_s_own_error_and_the_venv_it_left(
    stub_uv_project: Path, capfd: pytest.CaptureFixture[str], state: str, quiet: bool
) -> None:
    _install_stub_uv(stub_uv_project.parent / "bin", sync_rc=1, aftermath=_SYNC_AFTERMATH[state])
    venv = stub_uv_project / ".venv-3.10"

    assert ensure_project_venv_at(stub_uv_project, venv, None, quiet=quiet) is None

    err = capfd.readouterr().err
    assert err.count(_SYNC_MARKER) == 1, "uv's reason is shown exactly once, in either output mode"
    assert f"uv sync from uv.lock failed for .venv-3.10 (exit 1; venv afterwards: {state})" in err
    assert "BMK_OUTPUT_FORMAT=text" not in err, "a re-run is what loses the evidence"


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
def test_a_successful_quiet_sync_prints_nothing(stub_uv_project: Path, capfd: pytest.CaptureFixture[str]) -> None:
    _install_stub_uv(stub_uv_project.parent / "bin", sync_rc=0)
    venv = stub_uv_project / ".venv"

    assert ensure_project_venv_at(stub_uv_project, venv, None, quiet=True) == venv

    assert capfd.readouterr().err == ""


@pytest.mark.os_agnostic
def test_ensure_at_without_a_minor_omits_the_python_pin(tmp_path: Path) -> None:
    """minor=None (no classifiers) -> uv picks the interpreter; the default-venv path."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv"
    mock_run = _run_that_creates_venv_on_uv_venv()

    with _faked_uv(mock_run):
        ensure_project_venv_at(tmp_path, target, None)

    cmds = [c.args[0] for c in mock_run.call_args_list]
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "--python" not in create
    assert not any(c[:3] == ["uv", "python", "install"] for c in cmds), "no minor -> nothing to install"


@pytest.mark.os_agnostic
def test_ensure_project_venv_delegates_to_ensure_at(tmp_path: Path) -> None:
    """ensure_project_venv is now a thin caller: default path, desired (highest) minor."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nclassifiers = ["Programming Language :: Python :: 3.13"]\n'
    )
    mock_run = _run_that_creates_venv_on_uv_venv()

    with _faked_uv(mock_run):
        result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    cmds = [c.args[0] for c in mock_run.call_args_list]
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "3.13" in create and str(tmp_path / ".venv") in create


# ---------------------------------------------------------------------------
# ensure_project_venv
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_ensure_project_venv_skips_without_pyproject(tmp_path: Path) -> None:
    """A directory that is not a Python project gets no venv."""
    assert ensure_project_venv(tmp_path, {}) is None


@pytest.mark.os_agnostic
def test_ensure_project_venv_syncs_an_existing_venv_without_recreating(tmp_path: Path) -> None:
    """An existing venv is updated in place, never recreated.

    Recreating would change nothing about the path but would discard the env and,
    more importantly, `uv venv` must not run while tools are pinned at it.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")

    with _faked_uv(MagicMock(return_value=0)) as mock_run:
        result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    commands = [call.args[0] for call in mock_run.call_args_list]
    assert not any(cmd[:2] == ["uv", "venv"] for cmd in commands), "must not recreate an existing venv"


@pytest.mark.os_agnostic
def test_ensure_project_venv_sync_is_exact_and_upgrading(tmp_path: Path) -> None:
    """Without a lock, the manifest install passes both --exact and --upgrade.

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
    mock_run = _run_that_creates_venv_on_uv_venv(lock_rc=1)

    with _faked_uv(mock_run):
        ensure_project_venv(tmp_path, {})

    install = next(c for c in _commands(mock_run) if c[:3] == ["uv", "pip", "install"])
    assert "--exact" in install
    assert "--upgrade" in install
    assert install[install.index("--python") + 1] == str(venv_python(tmp_path / ".venv"))


@pytest.mark.os_agnostic
def test_uv_env_drops_virtual_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provisioning uv calls must not inherit an active VIRTUAL_ENV.

    Provisioning runs before the pipeline pins VIRTUAL_ENV at the project venv, so a uv
    call here would otherwise inherit the caller's shell venv (an IDE's, say) and uv prints
    a "does not match the project environment path ... will be ignored" warning on every
    call. Everything else in the environment is preserved.
    """
    from bmk.adapters.stagerunner.venv import _uv_env

    monkeypatch.setenv("VIRTUAL_ENV", "/home/user/ide-venv")
    monkeypatch.setenv("BMK_PROBE_MARKER", "keep-me")
    env = _uv_env()
    assert "VIRTUAL_ENV" not in env
    assert env["BMK_PROBE_MARKER"] == "keep-me"


@pytest.mark.os_agnostic
def test_run_passes_uv_env_without_virtual_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_run hands uv an explicit environment with VIRTUAL_ENV stripped."""
    from bmk.adapters.stagerunner import venv as venv_mod

    monkeypatch.setenv("VIRTUAL_ENV", "/home/user/ide-venv")
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(venv_mod.subprocess, "run", fake_run)
    venv_mod._run(["uv", "venv", str(tmp_path / ".venv")], tmp_path, quiet=True)

    env = captured["env"]
    assert isinstance(env, dict)
    assert "VIRTUAL_ENV" not in env


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv._run")
def test_ensure_project_venv_falls_back_when_no_dev_extra(mock_run: MagicMock, tmp_path: Path) -> None:
    """Falls back to `.` when the project has no [dev] extra.

    bmk itself has none: its tooling is declared as runtime dependencies.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")
    mock_run.side_effect = [1, 1, 0]  # no lock can be made, ".[dev]" fails, "." succeeds

    result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    targets = [call.args[0][-1] for call in mock_run.call_args_list if call.args[0][:3] == ["uv", "pip", "install"]]
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


# ---------------------------------------------------------------------------
# ensure_venv_ignored - keep the venv bmk creates out of git
# ---------------------------------------------------------------------------


def _git_repo(path: Path) -> bool:
    """Init a throwaway git repo at ``path``; False if git is unavailable."""
    if _run_git(path, "init", "-q") != 0:
        return False
    _run_git(path, "config", "user.email", "t@example.invalid")
    _run_git(path, "config", "user.name", "t")
    return True


def _run_git(cwd: Path, *args: str) -> int:
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, check=False).returncode
    except OSError:
        return 1


@pytest.mark.os_agnostic
def test_ensure_venv_ignored_is_a_noop_outside_a_git_repo(tmp_path: Path) -> None:
    """A non-git directory gets no .gitignore invented for it."""
    ensure_venv_ignored(tmp_path, tmp_path / ".venv")

    assert not (tmp_path / ".gitignore").exists()


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_adds_one_venv_glob(tmp_path: Path) -> None:
    """One `.venv*/` glob covers .venv, .venv-win, .venv-bmk AND every .venv-<minor>.

    A single glob is what makes the version matrix work: `test-all` creates .venv-3.10 ..
    .venv-3.14 and none of them needs its own line.
    """
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")

    ensure_venv_ignored(tmp_path, tmp_path / ".venv")

    content = (tmp_path / ".gitignore").read_text()
    assert ".venv*/" in content


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_glob_covers_matrix_and_siblings(tmp_path: Path) -> None:
    """After the glob is written, git itself ignores every venv name we care about."""
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")

    ensure_venv_ignored(tmp_path, tmp_path / ".venv")

    for name in (".venv", ".venv-win", ".venv-bmk", ".venv-3.10", ".venv-3.14"):
        code = subprocess.run(
            ["git", "-C", str(tmp_path), "check-ignore", "-q", "--", f"{name}/"], check=False
        ).returncode
        assert code == 0, f"{name}/ must be ignored by the .venv* glob"


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_is_idempotent(tmp_path: Path) -> None:
    """Repeated runs, for different matrix venvs, keep exactly one glob line.

    The presence check probes a synthetic name only the glob covers, so an existing
    `.venv*/` is recognised however the individual venv is named.
    """
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")

    ensure_venv_ignored(tmp_path, tmp_path / ".venv")
    ensure_venv_ignored(tmp_path, tmp_path / ".venv-3.10")
    ensure_venv_ignored(tmp_path, tmp_path / ".venv-3.14")

    assert (tmp_path / ".gitignore").read_text().count(".venv*/") == 1


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_declares_the_glob_not_uvs_self_ignore(tmp_path: Path) -> None:
    """uv's own nested .gitignore (`*`) does not count as the repo declaring the venv.

    `uv venv` writes `*` INSIDE every venv, so a venv reports as ignored by its own file.
    That is uv hiding its artifact, not the repo declaring it - taking it as declared would
    leave the matrix venvs uncovered.
    """
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / ".gitignore").write_text("*\n")  # what `uv venv` does

    ensure_venv_ignored(tmp_path, venv)

    assert ".venv*/" in (tmp_path / ".gitignore").read_text()


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_respects_an_existing_glob(tmp_path: Path) -> None:
    """An existing `.venv*` rule is left exactly as it is - not duplicated."""
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")
    (tmp_path / ".gitignore").write_text(".venv*\n")

    ensure_venv_ignored(tmp_path, tmp_path / ".venv")

    assert (tmp_path / ".gitignore").read_text() == ".venv*\n"


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_adds_the_glob_alongside_a_stale_literal(tmp_path: Path) -> None:
    """A repo with only the old literal `.venv/` gains the glob, so matrix venvs are covered.

    Old bmk wrote literal names; the literal does NOT cover .venv-3.14, so the glob must be
    added. The stale literal is left in place (bmk does not rewrite the user's file).
    """
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")
    (tmp_path / ".gitignore").write_text(".venv/\n")

    ensure_venv_ignored(tmp_path, tmp_path / ".venv-3.14")

    content = (tmp_path / ".gitignore").read_text()
    assert ".venv*/" in content


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_untracks_a_tracked_venv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A tracked venv is dropped from the index but kept on disk.

    With an exact sync rewriting its contents every run, a tracked venv would
    show thousands of modified files on every command and any commit would sweep
    them in.
    """
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")
    venv = tmp_path / ".venv"
    (venv / "lib").mkdir(parents=True)
    (venv / "lib" / "thing.py").write_text("x = 1\n")
    assert _run_git(tmp_path, "add", "-f", ".venv") == 0
    assert _run_git(tmp_path, "commit", "-q", "-m", "track a venv") == 0

    ensure_venv_ignored(tmp_path, venv)

    result = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", ".venv"], capture_output=True, text=True, check=False
    )
    assert result.stdout.strip() == "", "the venv must no longer be tracked"
    assert (venv / "lib" / "thing.py").exists(), "the files must stay on disk"
    assert "untracked" in capsys.readouterr().out


@pytest.mark.os_agnostic
@pytest.mark.local_only
def test_ensure_venv_ignored_announces_the_untrack_even_when_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The untrack is never silent.

    It stages deletions in the user's index and `push` commits automatically, so
    this must be visible regardless of the JSON/quiet output mode.
    """
    if not _git_repo(tmp_path):
        pytest.skip("git unavailable")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "f.txt").write_text("x")
    _run_git(tmp_path, "add", "-f", ".venv")
    _run_git(tmp_path, "commit", "-q", "-m", "t")

    ensure_project_venv(tmp_path, {}, quiet=True)  # no pyproject -> returns early
    ensure_venv_ignored(tmp_path, venv)

    assert "[bmk] untracked" in capsys.readouterr().out


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


# --- own packages are refreshed when the lock is upgraded (bmk OPEN-WORK [103]) ----------------------
# PyPI serves the simple index with Cache-Control max-age=600 and uv honours it, so for ten minutes
# after one of OUR packages is released, `uv lock --upgrade` still resolves the previous version and
# the own floor (which rises only to what the lock resolves) silently stays. Measured 2026-10-12:
# `uv lock --upgrade-package lib-cli-exit-tools` kept 2.4.0; adding --refresh-package got 2.4.1.


def _project_with_exemptions(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n\n[tool.uv]\nexclude-newer = "1 day"\n'
        'exclude-newer-package = {lib-cli-exit-tools = false, rtoml = "2026-10-12T00:17:16Z", lib-log-rich = false}\n',
        encoding="utf-8",
    )


@pytest.mark.os_agnostic
def test_an_upgrade_lock_refreshes_every_exempt_own_package(tmp_path: Path) -> None:
    _project_with_exemptions(tmp_path)

    argv = _lock_argv(tmp_path, upgrade=True)

    refreshed = [argv[i + 1] for i, a in enumerate(argv) if a == "--refresh-package"]
    assert sorted(refreshed) == ["lib-cli-exit-tools", "lib-log-rich"]
    assert argv[:3] == ["uv", "lock", "--upgrade"]


@pytest.mark.os_agnostic
def test_a_plain_lock_refreshes_nothing(tmp_path: Path) -> None:
    _project_with_exemptions(tmp_path)

    assert _lock_argv(tmp_path, upgrade=False) == ["uv", "lock"]


# uv 0.13.0's own words when it rejects the refresh flag itself, measured 2026-10-13: offline from the
# environment, from pyproject/uv.toml, from the command line, and a name clap refuses to parse.
_REFRESH_REFUSALS = [
    "error: the argument `UV_OFFLINE` (environment variable) cannot be used with `--refresh`\n",
    "error: the argument `offline` (workspace configuration) cannot be used with `--refresh`\n",
    "error: the argument `--offline` cannot be used with `--refresh`\n",
    "error: invalid value 'not a name!' for '--refresh-package <REFRESH_PACKAGE>': Not a valid package or extra name\n",
]


@pytest.mark.os_agnostic
@pytest.mark.parametrize("stderr", _REFRESH_REFUSALS)
def test_uv_refusing_the_refresh_flag_itself_earns_the_plain_retry(stderr: str) -> None:
    assert _refresh_refused(2, stderr)


@pytest.mark.os_agnostic
def test_a_coloured_refusal_is_still_a_refused_refresh() -> None:
    """FORCE_COLOR / CLICOLOR_FORCE put escape codes INSIDE the words uv refuses with (measured).

    ``--color never`` does not help: under CLICOLOR_FORCE clap's parse error for a bad name stays coloured.
    """
    offline = (
        "error: the argument `UV_OFFLINE` (environment variable) cannot be used with \x1b[32m`--refresh`\x1b[39m\n"
    )
    bad_name = "\x1b[1m\x1b[31merror:\x1b[0m invalid value '\x1b[33mbad!\x1b[0m' for '\x1b[1m\x1b[36m--refresh-package\x1b[0m'\n"
    assert _refresh_refused(2, offline)
    assert _refresh_refused(2, bad_name)


@pytest.mark.os_agnostic
def test_a_real_lock_failure_on_exit_2_is_not_read_as_a_refused_refresh() -> None:
    """Exit 2 is uv's general error status, not a usage-error code (third review of 58394fe).

    Measured: an unreachable index and a malformed pyproject.toml both exit 2 with and without the
    refresh. Retrying those without it runs the failure twice, blames "offline", and when only the
    refresh's revalidation failed, locks from the max-age=600 cache: the own floor stays put again.
    """
    unreachable = (
        "Using CPython 3.15.0\n"
        "error: Failed to fetch: http://127.0.0.1:9/simple/idna/\n"
        "  cause: tcp connect error\n"
        "  cause: Connection refused (os error 111)\n"
    )
    assert not _refresh_refused(2, unreachable)


@pytest.mark.os_agnostic
def test_a_refusal_text_under_any_other_exit_code_is_not_a_refused_refresh() -> None:
    assert not _refresh_refused(1, _REFRESH_REFUSALS[0])


def _project_behind_a_dead_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\nrequires-python = ">=3.10"\ndependencies = ["idna"]\n\n'
        "[tool.uv]\nexclude-newer-package = {idna = false}\n\n"
        '[[tool.uv.index]]\nname = "dead"\nurl = "http://127.0.0.1:9/simple"\ndefault = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cold-cache"))
    monkeypatch.setenv("UV_HTTP_RETRIES", "0")
    monkeypatch.delenv("UV_OFFLINE", raising=False)


@pytest.mark.os_agnostic
def test_an_unreachable_index_fails_the_upgrade_lock_without_blaming_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _project_behind_a_dead_index(tmp_path, monkeypatch)

    assert not lock_project(tmp_path, upgrade=True)

    assert "refused --refresh-package" not in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_a_failing_upgrade_lock_still_shows_uv_s_reason_when_not_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    _project_behind_a_dead_index(tmp_path, monkeypatch)

    assert not lock_project(tmp_path, quiet=False, upgrade=True)

    assert "127.0.0.1:9" in capfd.readouterr().err


@pytest.mark.os_agnostic
@pytest.mark.parametrize("colour", [{}, {"FORCE_COLOR": "1", "CLICOLOR_FORCE": "1"}], ids=["plain", "forced-colour"])
def test_offline_upgrade_lock_succeeds_for_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], colour: dict[str, str]
) -> None:
    """The liveness half of the pair above: offline, uv refuses the refresh and the plain lock runs.

    Forced colour is set explicitly: the suite's autouse fixture removes FORCE_COLOR, which hid it.
    """
    for name, value in colour.items():
        monkeypatch.setenv(name, value)
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\nrequires-python = ">=3.10"\ndependencies = []\n\n'
        "[tool.uv]\nexclude-newer-package = {lib-cli-exit-tools = false}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("UV_OFFLINE", "1")

    assert lock_project(tmp_path, upgrade=True)
    assert (tmp_path / "uv.lock").is_file()
    assert "refused --refresh-package" in capsys.readouterr().err
