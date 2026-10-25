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

import io
import shutil
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING
from venv import EnvBuilder

import pytest

from bmk.adapters.stagerunner.venv import (
    ensure_project_venv_at,
    lock_project_reporting,
    sync_lock_path,
    uv_lock_guard_path,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from uv_stub import StubUv

#: Long enough that a slow machine does not fail the control, short enough that the
#: contended case does not stall the suite.
_SHORT_WAIT = "1"


def _project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    return tmp_path


@pytest.fixture
def lock_holder() -> Iterator[Callable[[Path], None]]:
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
        # Close the pipe too, or its file object is collected later as an unraisable ResourceWarning.
        if proc.stdout is not None:
            proc.stdout.close()


# The installed CPython 3.12 the rebuild check is told about, one patch ahead of the venv's.
#: What uv answers when asked which 3.12 it would build a venv on.
_UV_BUILDS_ON_3_12 = "3.12.9"


def _venv_on_an_older_patch(venv: Path) -> Path:
    """A venv whose interpreter answers 3.12.1, with a marker file that only a rebuild removes.

    The interpreter is a script, since bmk asks the venv's OWN python for its version: a rebuild is
    then decided by the real ``discard_venv_on_wrong_python``, and its effect is visible on disk.
    It answers in the probe's shape, ``<implementation> <X.Y.Z> <free-threaded 0|1>``.
    """
    python = venv / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\necho cpython 3.12.1 0\n", encoding="utf-8")
    python.chmod(0o755)
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    marker = venv / "survives-only-without-a-rebuild"
    marker.write_text("", encoding="utf-8")
    return marker


@pytest.mark.os_posix
def test_a_sync_refuses_loudly_rather_than_running_under_another_bmk(
    tmp_path: Path,
    stub_uv: StubUv,
    lock_holder: Callable[[Path], None],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With the lock held elsewhere, provisioning must not mutate the venv."""
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    lock_holder(sync_lock_path(venv))

    result = ensure_project_venv_at(project, venv, None, quiet=False)

    assert result is None, "must not report success while another bmk holds the venv"
    assert stub_uv.calls() == [], "must not touch the venv while another bmk holds it"
    assert not venv.exists()
    assert "lock" in capsys.readouterr().err.lower(), "a refusal must say why, not fail silently"


@pytest.mark.os_posix
def test_a_timed_out_uv_lock_reports_no_exit_code_and_no_reason_because_uv_never_ran(
    tmp_path: Path,
    stub_uv: StubUv,
    lock_holder: Callable[[Path], None],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Another bmk holding the project's ``uv lock`` keeps its own message, with nothing invented after it."""
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    lock_holder(uv_lock_guard_path(project))

    assert ensure_project_venv_at(project, venv, None, quiet=True) == venv, "the manifest fallback still provisions"

    assert not any(c[:2] == ["uv", "lock"] for c in stub_uv.commands())
    assert capfd.readouterr().err == (
        f"[venv] another bmk is still locking {project}; waited {_SHORT_WAIT}s and gave up\n"
        f"[venv] uv lock failed in {project}; provisioning .venv from pyproject.toml instead\n"
    )


@pytest.mark.os_posix
def test_the_lock_contention_notice_reaches_the_stream_it_is_given(
    tmp_path: Path,
    stub_uv: StubUv,
    lock_holder: Callable[[Path], None],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The deps_update stage passes its sink: in JSON mode a line on stderr goes past its report."""
    project = _project(tmp_path)
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    lock_holder(uv_lock_guard_path(project))
    out = io.StringIO()

    assert not lock_project_reporting(project, quiet=True, upgrade=True, stream=out)

    assert not stub_uv.commands()
    assert out.getvalue() == f"[venv] another bmk is still locking {project}; waited {_SHORT_WAIT}s and gave up\n"
    assert capfd.readouterr().err == ""


@pytest.mark.os_posix
def test_a_sync_proceeds_when_nobody_holds_the_lock(
    tmp_path: Path, stub_uv: StubUv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: with no contention the lock is invisible and provisioning works.

    Without this, the test above passes for any reason that makes provisioning fail.
    """
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)

    result = ensure_project_venv_at(project, venv, None, quiet=True)

    assert result == venv
    assert any(c[:2] == ["uv", "sync"] for c in stub_uv.commands())


@pytest.mark.os_posix
def test_the_venv_rebuild_is_guarded_too_not_just_the_install(
    tmp_path: Path, stub_uv: StubUv, lock_holder: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interpreter change ``rmtree``s the whole venv - the widest window there is.

    Guarding only the ``uv pip install`` would leave a concurrent gate's entire
    interpreter deleted underneath it. Mutation-testing found this unasserted: moving
    ``discard_venv_on_wrong_python`` back outside the lock kept every other test green.
    """
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    marker = _venv_on_an_older_patch(venv)
    stub_uv.install(found_version=_UV_BUILDS_ON_3_12)
    lock_holder(sync_lock_path(venv))

    ensure_project_venv_at(project, venv, "3.12", quiet=True, install_python=False)

    assert marker.exists(), "the rebuild must not run while another bmk holds the venv"
    assert stub_uv.calls() == [], "not even the rebuild's own question to uv may run under the held lock"


@pytest.mark.os_posix
def test_the_rebuild_does_run_when_the_lock_is_free(
    tmp_path: Path, stub_uv: StubUv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control for the test above: uncontended, the same venv IS rebuilt.

    Without it, that test would pass if the rebuild were simply deleted.
    """
    project = _project(tmp_path)
    venv = project / ".venv"
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    marker = _venv_on_an_older_patch(venv)
    stub_uv.install(found_version=_UV_BUILDS_ON_3_12)

    ensure_project_venv_at(project, venv, "3.12", quiet=True, install_python=False)

    assert not marker.exists(), "a venv on the wrong patch is removed"
    cmds = stub_uv.commands()
    asked = cmds.index(["uv", "python", "find", "--system", "--no-python-downloads", "--show-version", "3.12"])
    assert cmds.index(["uv", "venv", "--python", "3.12", str(venv)]) > asked, "and recreated on the minor"


# The four tests below are the cross-platform twins of the stub-driven ones above. The stub uv
# is a POSIX shell script, which Windows cannot launch as ``uv``, and Windows file locking is a
# different primitive from POSIX's - so the lock guarantee needs proof there too. Each one
# decides its assertion BEFORE provisioning would reach uv, and runs with no uv on PATH at all.
# A missing uv is silent (``run_uv`` maps it to exit 1), so "uv was not called" cannot be the
# observation here; instead each test watches a side effect bmk itself performs under the lock,
# in pure Python, before its first uv call, and each refusal test has a control proving that
# side effect does fire once the lock is free.

#: A manifest bmk edits under the lock: with an ``exclude`` of its own, pyright loses its
#: ``**/.*`` default, so provisioning appends the venv to it (``ensure_venv_typecheck_excluded``).
_MANIFEST_BMK_EXTENDS = '[project]\nname = "demo"\n\n[tool.pyright]\nexclude = ["build"]\n'


def _without_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put an empty directory on PATH, so no uv can answer, and keep the locks under tmp_path."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("BMK_VENV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setenv("BMK_VENV_LOCK_TIMEOUT", _SHORT_WAIT)
    assert shutil.which("uv") is None, "a uv on PATH would let provisioning past the point under test"


def _project_with_an_existing_venv(tmp_path: Path) -> tuple[Path, Path]:
    """A project whose venv already exists, so provisioning skips ``uv venv`` and edits the manifest.

    ``pyvenv.cfg`` is all ``is_venv`` asks for; with no minor the rebuild check never runs the
    venv's interpreter, so none is needed.
    """
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text(_MANIFEST_BMK_EXTENDS, encoding="utf-8")
    venv = project / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    return project, venv


def _real_venv_that_records_each_start(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A real stdlib venv whose interpreter appends to a record file every time it starts.

    The rebuild check asks the venv's OWN interpreter for its version, and it does so even when
    uv could not answer; a ``.pth`` line runs at every interpreter start, so the record file is
    the trace of that question, on any OS, without patching anything in bmk.
    """
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    venv = project / ".venv"
    # Symlinks on POSIX, as `python -m venv` makes them. A copy is unusable when this suite itself
    # runs in a venv on CPython 3.10: there sys._base_executable is the outer venv's python, so the
    # copy's pyvenv.cfg home names that venv's bin, which holds no stdlib, and the copied
    # interpreter dies at startup before any .pth runs.
    EnvBuilder(with_pip=False, symlinks=sys.platform != "win32").create(str(venv))
    record = tmp_path / "venv-python-started"
    site_packages = next(venv.glob("**/site-packages"))
    (site_packages / "zz_record_start.pth").write_text(
        f"import os; f = open({str(record)!r}, 'a'); f.write('started '); f.close()\n", encoding="utf-8"
    )
    return project, venv, record


@pytest.mark.os_agnostic
def test_without_uv_a_held_lock_still_refuses_before_touching_the_project(
    tmp_path: Path,
    lock_holder: Callable[[Path], None],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cross-platform: under another process's lock, provisioning edits nothing and says why."""
    _without_uv(tmp_path, monkeypatch)
    project, venv = _project_with_an_existing_venv(tmp_path)
    lock_holder(sync_lock_path(venv))

    result = ensure_project_venv_at(project, venv, None, quiet=False)

    assert result is None, "must not report success while another bmk holds the venv"
    assert (project / "pyproject.toml").read_text(encoding="utf-8") == _MANIFEST_BMK_EXTENDS, (
        "the manifest was edited, so provisioning ran under another bmk's lock"
    )
    assert "another bmk is still provisioning" in capsys.readouterr().err, "a refusal must say why"


@pytest.mark.os_agnostic
def test_without_uv_a_free_lock_lets_provisioning_edit_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control for the test above: uncontended, the same setup DOES edit the manifest.

    Without it, that test would pass if provisioning never reached the manifest at all. The
    result is not asserted: with no uv the sync fails, and that is not what this checks.
    """
    _without_uv(tmp_path, monkeypatch)
    project, venv = _project_with_an_existing_venv(tmp_path)

    ensure_project_venv_at(project, venv, None, quiet=True)

    assert ".venv" in (project / "pyproject.toml").read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_without_uv_a_held_lock_still_guards_the_rebuild_check(
    tmp_path: Path, lock_holder: Callable[[Path], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-platform: the rebuild check, which can ``rmtree`` the venv, waits for the lock too.

    The rebuild itself needs uv to name the installed patch, so this cannot show a venv
    surviving a rebuild. It shows the check never STARTS: under the held lock the venv's
    interpreter is never asked for its version, which the check does before anything else that
    could run without uv.
    """
    _without_uv(tmp_path, monkeypatch)
    project, venv, record = _real_venv_that_records_each_start(tmp_path)
    lock_holder(sync_lock_path(venv))

    ensure_project_venv_at(project, venv, "3.12", quiet=True, install_python=False)

    assert not record.exists(), "the rebuild check ran while another bmk held the venv"


@pytest.mark.os_agnostic
def test_without_uv_a_free_lock_runs_the_rebuild_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control for the test above: uncontended, the rebuild check asks the venv's interpreter.

    Without it, that test would pass if the check were deleted, or if the record never worked.
    """
    _without_uv(tmp_path, monkeypatch)
    project, venv, record = _real_venv_that_records_each_start(tmp_path)

    ensure_project_venv_at(project, venv, "3.12", quiet=True, install_python=False)

    assert record.exists(), "the rebuild check must ask the venv's interpreter for its version"


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
