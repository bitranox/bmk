"""Tests for project venv resolution and provisioning."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmk.adapters.stagerunner.venv import (
    ensure_project_venv,
    ensure_project_venv_at,
    ensure_venv_ignored,
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
# ensure_project_venv_at - provisioning at an explicit path on an explicit minor
# (the matrix building block; `test-all` calls it once per declared version)
# ---------------------------------------------------------------------------


def _run_that_creates_venv_on_uv_venv() -> MagicMock:
    """A `_run` mock that materializes the venv when it sees `uv venv <path>`.

    Without this the create path returns None (is_venv stays False under a pure mock),
    so the install/sync argv is never reached. The side effect makes the flow realistic.
    """

    def side_effect(argv: list[str], _cwd: Path, *, quiet: bool = True) -> int:
        _ = quiet  # matches _run's real signature; the code calls quiet=...
        if argv[:2] == ["uv", "venv"]:
            _make_venv(Path(argv[-1]))
        return 0

    mock = MagicMock(side_effect=side_effect)
    return mock


@pytest.mark.os_agnostic
def test_ensure_at_creates_the_named_venv_on_the_named_minor(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv-3.12"
    mock_run = _run_that_creates_venv_on_uv_venv()

    with patch("bmk.adapters.stagerunner.venv._run", mock_run):
        result = ensure_project_venv_at(tmp_path, target, "3.12")

    assert result == target
    cmds = [c.args[0] for c in mock_run.call_args_list]
    create = next(c for c in cmds if c[:2] == ["uv", "venv"])
    assert "--python" in create and "3.12" in create and str(target) in create
    assert ["uv", "python", "install", "3.12"] in cmds
    assert ["uv", "python", "upgrade", "3.12"] in cmds
    install = next(c for c in cmds if c[:3] == ["uv", "pip", "install"])
    assert str(venv_python(target)) in install


@pytest.mark.os_agnostic
def test_ensure_at_without_a_minor_omits_the_python_pin(tmp_path: Path) -> None:
    """minor=None (no classifiers) -> uv picks the interpreter; the default-venv path."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    target = tmp_path / ".venv"
    mock_run = _run_that_creates_venv_on_uv_venv()

    with patch("bmk.adapters.stagerunner.venv._run", mock_run):
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

    with patch("bmk.adapters.stagerunner.venv._run", mock_run):
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
