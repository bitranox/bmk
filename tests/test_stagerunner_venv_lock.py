"""The venv sync is guarded against a concurrent bmk in another process.

Measured on the unguarded code, driving the real ``ensure_project_venv_at`` from two
separate processes at once: on a COLD start (venv absent) one of the two returned a
provisioning failure in 5 of 8 rounds. That does not crash - ``ensure_project_venv``
never raises, by design, and degrades to bmk's own interpreter - so the losing gate
silently type-checks, audits and tests a DIFFERENT environment than the project's,
with nothing in its output saying so.

A second sync that finds nothing to do is a no-op (measured: the dependency never
vanished across 418 samples), which is why the fix is a lock and not a skip-stamp:
serialising costs about 0.4s in the contended case and preserves ``--upgrade``'s job
of moving stale unconstrained transitives, which a stamp keyed on the manifest would
silently defeat.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmk.adapters.stagerunner.venv import ensure_project_venv_at, sync_lock_path

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Long enough that a slow machine does not fail the control, short enough that the
#: contended case does not stall the suite.
_SHORT_WAIT = "1"


def _make_venv(path: Path) -> None:
    """Materialize the minimum that makes ``is_venv`` true."""
    bindir = path / ("Scripts" if sys.platform == "win32" else "bin")
    bindir.mkdir(parents=True, exist_ok=True)
    exe = bindir / ("python.exe" if sys.platform == "win32" else "python")
    exe.write_text("", encoding="utf-8")
    (path / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")


def _run_that_creates_venv_on_uv_venv() -> MagicMock:
    def side_effect(argv: list[str], _cwd: Path, *, quiet: bool = True) -> int:
        _ = quiet
        if argv[:2] == ["uv", "venv"]:
            _make_venv(Path(argv[-1]))
        return 0

    return MagicMock(side_effect=side_effect)


def _project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    return tmp_path


@pytest.fixture
def lock_holder() -> Iterator[object]:
    """Hold a bmk venv lock from a genuinely separate process.

    A separate process, not a thread: the guarantee under test is cross-PROCESS, and a
    same-process thread would exercise whatever reentrancy the lock library happens to
    have rather than the thing that actually fails in the field.
    """
    procs: list[subprocess.Popen[str]] = []

    def hold(path: Path) -> None:
        code = textwrap.dedent(f"""
            import sys, time
            from filelock import FileLock
            lock = FileLock(r"{path}")
            lock.acquire()
            print("held", flush=True)
            time.sleep(120)
        """)
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        procs.append(proc)
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "held", "holder never acquired the lock"

    yield hold
    for proc in procs:
        proc.kill()
        proc.wait(timeout=10)


@pytest.mark.os_agnostic
def test_a_sync_refuses_loudly_rather_than_running_under_another_bmk(
    tmp_path: Path, lock_holder: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With the lock held elsewhere, provisioning must not mutate the venv."""
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    lock_holder(sync_lock_path(venv))  # type: ignore[operator]
    mock_run = _run_that_creates_venv_on_uv_venv()

    with patch("bmk.adapters.stagerunner.venv._run", mock_run):
        result = ensure_project_venv_at(project, venv, None, quiet=False)

    assert result is None, "must not report success while another bmk holds the venv"
    assert mock_run.call_count == 0, "must not touch the venv while another bmk holds it"
    assert "lock" in capsys.readouterr().err.lower(), "a refusal must say why, not fail silently"


@pytest.mark.os_agnostic
def test_a_sync_proceeds_when_nobody_holds_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: with no contention the lock is invisible and provisioning works.

    Without this, the test above passes for any reason that makes provisioning fail.
    """
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    mock_run = _run_that_creates_venv_on_uv_venv()

    with patch("bmk.adapters.stagerunner.venv._run", mock_run):
        result = ensure_project_venv_at(project, venv, None, quiet=True)

    assert result == venv
    assert mock_run.call_count > 0


@pytest.mark.os_agnostic
def test_the_venv_rebuild_is_guarded_too_not_just_the_install(
    tmp_path: Path, lock_holder: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interpreter change ``rmtree``s the whole venv - the widest window there is.

    Guarding only the ``uv pip install`` would leave a concurrent gate's entire
    interpreter deleted underneath it. Mutation-testing found this unasserted: moving
    ``_discard_venv_on_wrong_python`` back outside the lock kept every other test green.
    """
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    discard = MagicMock()
    monkeypatch.setattr("bmk.adapters.stagerunner.venv._discard_venv_on_wrong_python", discard)
    lock_holder(sync_lock_path(venv))  # type: ignore[operator]

    with patch("bmk.adapters.stagerunner.venv._run", _run_that_creates_venv_on_uv_venv()):
        ensure_project_venv_at(project, venv, None, quiet=True)

    assert discard.call_count == 0, "the rebuild must not run while another bmk holds the venv"


@pytest.mark.os_agnostic
def test_the_rebuild_does_run_when_the_lock_is_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control for the test above: uncontended, the rebuild check still happens.

    Without it, that test would pass if the rebuild were simply deleted.
    """
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    discard = MagicMock()
    monkeypatch.setattr("bmk.adapters.stagerunner.venv._discard_venv_on_wrong_python", discard)

    with patch("bmk.adapters.stagerunner.venv._run", _run_that_creates_venv_on_uv_venv()):
        ensure_project_venv_at(project, venv, None, quiet=True)

    assert discard.call_count == 1


@pytest.mark.os_agnostic
def test_the_lock_lives_outside_the_project_so_it_cannot_pollute_git_status(tmp_path: Path) -> None:
    """The lock must not be a file inside the user's repository.

    An earlier attempt put it beside the venv as ``.venv.lock`` on the assumption that
    the existing ``.venv*`` ignore rule covered it. It does not: ``_append_to_gitignore``
    writes every entry with a trailing slash, so those rules match DIRECTORIES only, and
    the lock showed up untracked in ``git status``. Asserting the NAME would have kept
    passing through that bug; asserting the LOCATION is what actually holds the line.
    """
    project = tmp_path / "proj"
    (project / ".venv").mkdir(parents=True)
    lock = sync_lock_path(project / ".venv")

    assert not lock.is_relative_to(project), f"lock must not live in the project: {lock}"


@pytest.mark.os_agnostic
def test_each_venv_gets_its_own_lock(tmp_path: Path) -> None:
    """The matrix runs a cell per version; they must not serialise against each other."""
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv-3.12").mkdir()
    (tmp_path / ".venv-3.13").mkdir()

    locks = {sync_lock_path(tmp_path / name) for name in (".venv", ".venv-3.12", ".venv-3.13")}

    assert len(locks) == 3, "distinct venvs sharing one lock would serialise the whole matrix"
