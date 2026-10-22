"""Tests for project venv resolution and provisioning."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from uv_stub import (
    ESC,
    LOCK_MARKER,
    PIP_MARKER,
    SYNC_COLOURED,
    SYNC_FILLER_LINES,
    SYNC_LAST_FILLER,
    SYNC_MARKER,
    VENV_MARKER,
)

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
    from collections.abc import Callable
    from pathlib import Path

    from uv_stub import StubUv


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


# Every provisioning test drives the REAL module through a stub `uv` first on PATH (the `stub_uv`
# fixture, tests/conftest.py + tests/uv_stub.py) and asserts on what reached the process boundary.
# Patching venv.py's own runners proved only that bmk called its own function, and stopped covering
# a runner the moment a change routed around it (OPEN-WORK [210]).

# uv offers a newer 3.12 patch, so install/upgrade have work to do; when it offers none they are
# skipped (see test_stagerunner_venv_python.py, bmk OPEN-WORK [102]).
_NEWER_3_12_ON_OFFER = (
    '[{"version": "3.12.16", "version_parts": {"major": 3, "minor": 12, "patch": 16}, '
    '"implementation": "cpython", "path": null}]'
)


@pytest.mark.os_posix
def test_ensure_at_creates_the_named_venv_on_the_named_minor(tmp_path: Path, stub_uv: StubUv) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv-3.12"
    stub_uv.install(offered_json=_NEWER_3_12_ON_OFFER)

    result = ensure_project_venv_at(tmp_path, target, "3.12")

    assert result == target
    cmds = stub_uv.commands()
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "--python" in create and "3.12" in create and str(target) in create
    assert ["uv", "python", "install", "3.12"] in cmds
    assert ["uv", "python", "upgrade", "3.12"] in cmds
    sync = next(c for c in cmds if c[:2] == ["uv", "sync"])
    assert sync[sync.index("--python") + 1] == "3.12", "the sync asks for the same minor the create did"


@pytest.mark.os_posix
def test_ensure_at_can_leave_uv_s_python_store_alone(tmp_path: Path, stub_uv: StubUv) -> None:
    """test-all prepares every minor serially, then its cells must not install again.

    A cell whose prep did not converge (offline, python-downloads = never) would otherwise run
    install/upgrade in parallel with its siblings' syncs: the alias rewrite of bmk OPEN-WORK [102].
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv-3.12"
    stub_uv.install(offered_json=_NEWER_3_12_ON_OFFER)

    result = ensure_project_venv_at(tmp_path, target, "3.12", install_python=False)

    assert result == target
    cmds = stub_uv.commands()
    assert not any(c[:2] == ["uv", "python"] and c[2] in ("install", "upgrade") for c in cmds)
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "3.12" in create, "the cell still pins its own minor"


@pytest.mark.os_posix
def test_a_test_all_cell_never_installs_a_python(tmp_path: Path, stub_uv: StubUv) -> None:
    """The cell itself must pass install_python=False; main() already prepared every minor."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    # every uv call fails, so the cell stops at ERROR before it would run pytest in a venv
    stub_uv.install(
        venv_rc=1,
        python_rc=1,
        lock_rc=1,
        sync_rc=1,
        pip_install_rc={".[dev]": 1, ".": 1},
        offered_json=_NEWER_3_12_ON_OFFER,
    )

    result = _matrix._run_cell(tmp_path, "3.12", quiet=True)

    assert result.status is CellStatus.ERROR
    cmds = stub_uv.commands()
    assert any(c[:2] == ["uv", "venv"] for c in cmds), "the cell must have reached provisioning"
    assert not any(c[:2] == ["uv", "python"] for c in cmds)


# --- the venv is built FROM uv.lock (user decision 2026-10-12, review M3 of 064688b) ---------------
# `uv pip install --upgrade` keeps an installed release newer than the [tool.uv] cooldown (measured:
# ruff 0.17.0 stayed), so make test checked a different tree from the one uv.lock pins and CI installs.


@pytest.mark.os_posix
def test_the_project_is_locked_and_the_venv_synced_from_the_lock(
    tmp_path: Path, stub_uv: StubUv, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv-3.12"
    # An IDE's venv in the caller's shell: it must not reach the sync, or uv warns and may prefer it.
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "ide-venv"))

    assert ensure_project_venv_at(tmp_path, target, "3.12") == target

    cmds = stub_uv.commands()
    assert cmds.index(["uv", "lock"]) < next(i for i, c in enumerate(cmds) if c[:2] == ["uv", "sync"])
    assert not any(c[:3] == ["uv", "pip", "install"] for c in cmds)
    [sync_call] = [c for c in stub_uv.calls() if c.argv[:2] == ("uv", "sync")]
    assert "--locked" in sync_call.argv
    # uv sync targets the project environment, so the matrix venv is named through the env.
    assert sync_call.project_environment == str(target)
    assert not sync_call.virtual_env_set


@pytest.mark.os_posix
@pytest.mark.parametrize(
    ("extras", "expected"), [("", []), ('[project.optional-dependencies]\ndev = ["pytest"]\n', ["--extra", "dev"])]
)
def test_the_dev_extra_is_synced_only_when_the_project_declares_it(
    tmp_path: Path, stub_uv: StubUv, extras: str, expected: list[str]
) -> None:
    # uv refuses an undeclared extra outright (exit 2), unlike pip's warning.
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "demo"\n{extras}')

    ensure_project_venv_at(tmp_path, tmp_path / ".venv", None)

    sync = next(c for c in stub_uv.commands() if c[:2] == ["uv", "sync"])
    assert [a for a in sync if a in ("--extra", "dev")] == expected


@pytest.mark.os_posix
def test_without_a_lock_the_venv_falls_back_to_the_manifest_and_says_so(
    tmp_path: Path, stub_uv: StubUv, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    stub_uv.install(lock_rc=1)

    assert ensure_project_venv_at(tmp_path, tmp_path / ".venv", None) == tmp_path / ".venv"

    cmds = stub_uv.commands()
    assert any(c[:3] == ["uv", "pip", "install"] for c in cmds)
    assert not any(c[:2] == ["uv", "sync"] for c in cmds)
    assert "uv lock" in capsys.readouterr().err


@pytest.mark.os_posix
def test_a_failed_sync_from_a_good_lock_is_not_papered_over_by_the_manifest_install(
    tmp_path: Path, stub_uv: StubUv, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    stub_uv.install(sync_rc=1)

    assert ensure_project_venv_at(tmp_path, tmp_path / ".venv", None) is None

    assert not any(c[:3] == ["uv", "pip", "install"] for c in stub_uv.commands())
    assert "uv sync" in capsys.readouterr().err


# --- a failed `uv sync` keeps uv's own reason (bmk OPEN-WORK [19]) ------------------------------------
# The sync used to run with stderr discarded in JSON mode and only hinted at a text-mode re-run, which
# then passed: the intermittent 3.10 test-all failure never left its cause behind.

# What the stub's `uv sync` leaves behind before it exits 1, and the state the failure line must name.
_SYNC_AFTERMATH = {
    "venv": ":",
    "directory without pyvenv.cfg": 'rm -f "$UV_PROJECT_ENVIRONMENT/pyvenv.cfg"',
    "empty directory": 'rm -rf "$UV_PROJECT_ENVIRONMENT" && mkdir "$UV_PROJECT_ENVIRONMENT"',
    "absent": 'rm -rf "$UV_PROJECT_ENVIRONMENT"',
}


@pytest.fixture
def stub_uv_project(tmp_path: Path, stub_uv: StubUv) -> Path:
    """A project dir beside the stub ``uv``, so the stub's own files are never inside the project."""
    _ = stub_uv  # requested for its PATH and lock-dir setup
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    return project


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
@pytest.mark.parametrize("state", list(_SYNC_AFTERMATH))
@pytest.mark.parametrize("quiet", [True, False], ids=["json-mode", "text-mode"])
def test_a_failed_sync_prints_uv_s_own_error_and_the_venv_it_left(
    stub_uv_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str], state: str, quiet: bool
) -> None:
    stub_uv.install(sync_rc=1, sync_aftermath=_SYNC_AFTERMATH[state])
    venv = stub_uv_project / ".venv-3.10"

    assert ensure_project_venv_at(stub_uv_project, venv, None, quiet=quiet) is None

    err = capfd.readouterr().err
    assert err.count(SYNC_MARKER) == 1, "uv's reason is shown exactly once, in either output mode"
    assert f"uv sync from uv.lock failed for .venv-3.10 (exit 1; venv afterwards: {state})" in err
    assert "BMK_OUTPUT_FORMAT=text" not in err, "a re-run is what loses the evidence"


class _WriteRecorder(io.StringIO):
    """A ``sys.stderr`` stand-in that keeps every ``write`` call apart, to tell one write from several.

    Parallel test-all cells share the process stderr, so a failure block only stays readable when
    it arrives in one write; separate prints can interleave with a sibling cell's lines.
    """

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[str] = []

    def write(self, s: str, /) -> int:
        self.writes.append(s)
        return super().write(s)


def _failure_header(state: str) -> str:
    return f"[venv] uv sync from uv.lock failed for .venv-3.10 (exit 1; venv afterwards: {state})"


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
def test_a_quiet_failed_sync_writes_all_of_uv_s_stderr_as_one_plain_block(
    stub_uv_project: Path, stub_uv: StubUv, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_uv.install(sync_rc=1)
    recorder = _WriteRecorder()
    monkeypatch.setattr(sys, "stderr", recorder)

    assert ensure_project_venv_at(stub_uv_project, stub_uv_project / ".venv-3.10", None, quiet=True) is None

    blocks = [w for w in recorder.writes if _failure_header("venv") in w]
    assert len(blocks) == 1, f"the failure is reported once, as one write: {recorder.writes!r}"
    lines = blocks[0].splitlines()
    assert lines[0] == _failure_header("venv") + ":", "in JSON mode uv's stderr follows the header"
    assert f"    error: {SYNC_MARKER}" in lines, "uv's FIRST line, its error, rides in the header's write: no tail cap"
    assert f"    {SYNC_LAST_FILLER}" in lines, "uv's last line arrives in the same write as the header"
    assert len(lines) == 1 + 2 + SYNC_FILLER_LINES, "every line uv wrote, each on its own line"
    assert ESC not in recorder.getvalue(), "no escape byte reaches a CI log"
    assert f"    {SYNC_COLOURED}" in lines, "a coloured line is kept, its colour codes removed"


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
def test_a_text_mode_failed_sync_streams_uv_live_and_adds_a_bare_header(
    stub_uv_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_uv.install(sync_rc=1)
    recorder = _WriteRecorder()
    monkeypatch.setattr(sys, "stderr", recorder)

    assert ensure_project_venv_at(stub_uv_project, stub_uv_project / ".venv-3.10", None, quiet=False) is None

    # uv inherits the terminal's stderr, so its lines reach fd 2 directly while it runs; anything
    # bmk prints goes through sys.stderr, the recorder.
    live = capfd.readouterr().err
    assert live.count(f"error: {SYNC_MARKER}") == 1, "uv's output streams live, straight from uv"
    assert SYNC_LAST_FILLER in live
    echoed = recorder.getvalue()
    assert SYNC_MARKER not in echoed, "bmk does not print uv's lines a second time"
    assert _failure_header("venv") in echoed.splitlines(), "no trailing colon: uv's output is above it"


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
def test_a_successful_quiet_sync_prints_nothing(stub_uv_project: Path, capfd: pytest.CaptureFixture[str]) -> None:
    venv = stub_uv_project / ".venv"

    assert ensure_project_venv_at(stub_uv_project, venv, None, quiet=True) == venv

    assert capfd.readouterr().err == ""


# --- every other provisioning failure keeps uv's reason too (bmk OPEN-WORK [220]) -------------------
# `uv venv`, `uv lock` and the manifest fallback ran with stderr discarded in JSON mode, so a failed
# provisioning said at most "uv lock failed" and never why. Each now reports like the sync does.

_VENV_RC = 3
_LOCK_RC = 3
_PIP_DEV_RC = 4
_PIP_LAST_RC = 5


def _lock_failure_line(project: Path) -> str:
    return f"[venv] uv lock failed in {project} (exit {_LOCK_RC}); provisioning .venv from pyproject.toml instead"


_PIP_FAILURE_HEADER = f"[venv] uv pip install (fallback from pyproject.toml) failed for .venv (exit {_PIP_LAST_RC}; venv afterwards: venv)"


def _venv_failure_header(rc: int) -> str:
    return f"[venv] uv venv failed for .venv (exit {rc}; venv afterwards: absent)"


# Per scenario: how the stub fails, and whether provisioning still succeeds (only a failed lock
# leaves the manifest fallback to succeed).
_FAILURES: dict[str, tuple[Callable[[StubUv], None], bool]] = {
    "uv-venv": (lambda stub: stub.install(venv_rc=_VENV_RC), False),
    "uv-venv-exit-0-but-no-venv": (lambda stub: stub.install(venv_creates=False), False),
    "uv-lock": (lambda stub: stub.install(lock_rc=_LOCK_RC), True),
    "fallback-install": (
        lambda stub: stub.install(lock_rc=_LOCK_RC, pip_install_rc={".[dev]": _PIP_DEV_RC, ".": _PIP_LAST_RC}),
        False,
    ),
}


def _expected_reports(scenario: str, project: Path) -> list[tuple[str, list[str]]]:
    """Every report bmk must print for ``scenario``, in order: (header, the stderr lines uv printed)."""
    lock = (_lock_failure_line(project), [f"error: {LOCK_MARKER}"])
    no_reason: list[str] = []
    reports: dict[str, list[tuple[str, list[str]]]] = {
        "uv-venv": [(_venv_failure_header(_VENV_RC), [f"error: {VENV_MARKER}"])],
        "uv-venv-exit-0-but-no-venv": [(_venv_failure_header(0), no_reason)],
        "uv-lock": [lock],
        # Only the LAST target's reason: ".[dev]" failing first is the expected route to ".".
        "fallback-install": [lock, (_PIP_FAILURE_HEADER, [f"error: {PIP_MARKER} ."])],
    }
    return reports[scenario]


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
@pytest.mark.parametrize("scenario", list(_FAILURES))
def test_a_quiet_provisioning_failure_writes_its_header_and_uv_s_reason_as_one_block_each(
    stub_uv_project: Path,
    stub_uv: StubUv,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    fail, provisions = _FAILURES[scenario]
    fail(stub_uv)
    recorder = _WriteRecorder()
    monkeypatch.setattr(sys, "stderr", recorder)
    venv = stub_uv_project / ".venv"

    result = ensure_project_venv_at(stub_uv_project, venv, None, quiet=True)

    assert result == (venv if provisions else None)
    expected = [
        f"{header}:\n" + "".join(f"    {line}\n" for line in lines) if lines else f"{header}\n"
        for header, lines in _expected_reports(scenario, stub_uv_project)
    ]
    assert recorder.writes == expected, "each failure is one write: its header, a colon, and uv's lines"
    assert capfd.readouterr().err == "", "uv's own stderr reaches the output only inside bmk's report"


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
@pytest.mark.parametrize("scenario", list(_FAILURES))
def test_a_text_mode_provisioning_failure_streams_uv_live_and_adds_bare_headers(
    stub_uv_project: Path,
    stub_uv: StubUv,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    fail, provisions = _FAILURES[scenario]
    fail(stub_uv)
    recorder = _WriteRecorder()
    monkeypatch.setattr(sys, "stderr", recorder)
    venv = stub_uv_project / ".venv"

    result = ensure_project_venv_at(stub_uv_project, venv, None, quiet=False)

    assert result == (venv if provisions else None)
    reports = _expected_reports(scenario, stub_uv_project)
    assert recorder.getvalue() == "".join(f"{header}\n" for header, _ in reports), (
        "no trailing colon and no copy of uv's lines: uv's output is already above the header"
    )
    live = capfd.readouterr().err.splitlines()
    for _, lines in reports:
        for line in lines:
            assert live.count(line) == 1, f"uv's {line!r} streams live, straight from uv, once"


# uv sync may remove the venv and recreate it from the --python interpreter's sys._base_executable.
# On CPython <= 3.10 that is the venv's own bin/python, deleted by then, so a --python pointing INTO
# the venv left an empty directory (bmk OPEN-WORK [19]). A known minor is asked for by name instead.
@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="the stub uv is a POSIX shell script")
@pytest.mark.parametrize(
    ("minor", "venv_name"), [("3.10", ".venv-3.10"), (None, ".venv")], ids=["minor-known", "no-minor"]
)
def test_the_sync_asks_uv_for_the_minor_never_the_interpreter_inside_the_venv(
    stub_uv_project: Path, stub_uv: StubUv, minor: str | None, venv_name: str
) -> None:
    venv = stub_uv_project / venv_name

    assert ensure_project_venv_at(stub_uv_project, venv, minor, quiet=True, install_python=False) == venv

    argv = next(c for c in stub_uv.commands() if c[:2] == ["uv", "sync"])
    expected = minor if minor else str(venv_python(venv))
    assert argv[argv.index("--python") + 1] == expected


@pytest.mark.os_posix
def test_ensure_at_without_a_minor_omits_the_python_pin(tmp_path: Path, stub_uv: StubUv) -> None:
    """minor=None (no classifiers) -> uv picks the interpreter; the default-venv path."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv"

    ensure_project_venv_at(tmp_path, target, None)

    cmds = stub_uv.commands()
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "--python" not in create
    assert not any(c[:3] == ["uv", "python", "install"] for c in cmds), "no minor -> nothing to install"


@pytest.mark.os_posix
def test_ensure_project_venv_delegates_to_ensure_at(tmp_path: Path, stub_uv: StubUv) -> None:
    """ensure_project_venv is now a thin caller: default path, desired (highest) minor."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nclassifiers = ["Programming Language :: Python :: 3.13"]\n'
    )

    result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    create = next(c for c in stub_uv.commands() if c[:2] == ["uv", "venv"])
    assert "3.13" in create and str(tmp_path / ".venv") in create


# ---------------------------------------------------------------------------
# ensure_project_venv
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_ensure_project_venv_skips_without_pyproject(tmp_path: Path) -> None:
    """A directory that is not a Python project gets no venv."""
    assert ensure_project_venv(tmp_path, {}) is None


@pytest.mark.os_posix
def test_ensure_project_venv_syncs_an_existing_venv_without_recreating(tmp_path: Path, stub_uv: StubUv) -> None:
    """An existing venv is updated in place, never recreated.

    Recreating would change nothing about the path but would discard the env and,
    more importantly, `uv venv` must not run while tools are pinned at it.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")

    result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    commands = stub_uv.commands()
    assert any(cmd[:2] == ["uv", "sync"] for cmd in commands), "the existing venv is still synced"
    assert not any(cmd[:2] == ["uv", "venv"] for cmd in commands), "must not recreate an existing venv"


@pytest.mark.os_posix
def test_ensure_project_venv_sync_is_exact_and_upgrading(tmp_path: Path, stub_uv: StubUv) -> None:
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
    stub_uv.install(lock_rc=1)

    ensure_project_venv(tmp_path, {})

    install = next(c for c in stub_uv.commands() if c[:3] == ["uv", "pip", "install"])
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


@pytest.mark.os_posix
def test_run_passes_uv_env_without_virtual_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stub_uv: StubUv
) -> None:
    """_run hands uv an explicit environment with VIRTUAL_ENV stripped."""
    from bmk.adapters.stagerunner import venv as venv_mod

    monkeypatch.setenv("VIRTUAL_ENV", "/home/user/ide-venv")
    venv_mod._run(["uv", "venv", str(tmp_path / ".venv")], tmp_path, quiet=True)
    # The control: an explicit env that keeps VIRTUAL_ENV must show up as set, or the stub
    # could not see the variable at all and the assertion below would hold for any _run.
    venv_mod._run(["uv", "venv", str(tmp_path / ".venv-control")], tmp_path, quiet=True, env=dict(os.environ))

    stripped, control = stub_uv.calls()
    assert not stripped.virtual_env_set
    assert control.virtual_env_set


@pytest.mark.os_posix
def test_ensure_project_venv_falls_back_when_no_dev_extra(tmp_path: Path, stub_uv: StubUv) -> None:
    """Falls back to `.` when the project has no [dev] extra.

    bmk itself has none: its tooling is declared as runtime dependencies.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")
    stub_uv.install(lock_rc=1, pip_install_rc={".[dev]": 1})  # no lock can be made, ".[dev]" fails, "." succeeds

    result = ensure_project_venv(tmp_path, {})

    assert result == tmp_path / ".venv"
    targets = [c[-1] for c in stub_uv.commands() if c[:3] == ["uv", "pip", "install"]]
    assert targets == [".[dev]", "."]


@pytest.mark.os_posix
def test_ensure_project_venv_returns_none_when_sync_fails(tmp_path: Path, stub_uv: StubUv) -> None:
    """A failed sync degrades to None rather than raising."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    _make_venv(tmp_path / ".venv")
    stub_uv.install(lock_rc=1, sync_rc=1, pip_install_rc={".[dev]": 1, ".": 1})

    assert ensure_project_venv(tmp_path, {}) is None
    targets = [c[-1] for c in stub_uv.commands() if c[:3] == ["uv", "pip", "install"]]
    assert targets == [".[dev]", "."], "None comes from every install target failing, not an early exit"


@pytest.mark.os_posix
def test_ensure_project_venv_returns_none_when_creation_fails(tmp_path: Path, stub_uv: StubUv) -> None:
    """A failed `uv venv` degrades to None rather than raising."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    stub_uv.install(venv_rc=1, lock_rc=1, sync_rc=1, pip_install_rc={".[dev]": 1, ".": 1})

    assert ensure_project_venv(tmp_path, {}) is None
    cmds = stub_uv.commands()
    assert any(c[:2] == ["uv", "venv"] for c in cmds), "None comes from the failed create"
    assert not any(c[:2] in (["uv", "lock"], ["uv", "sync"]) for c in cmds), "nothing runs after a failed create"


@pytest.mark.os_posix
def test_ensure_project_venv_creates_at_the_override_path(tmp_path: Path, stub_uv: StubUv) -> None:
    """Creation targets the resolved path, not a hardcoded .venv."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    env = {"UV_PROJECT_ENVIRONMENT": ".venv-win"}

    ensure_project_venv(tmp_path, env)

    create = stub_uv.commands()[0]
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
