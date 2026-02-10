"""Automation wrapper stories: every build script, a single stanza.

Verify that script modules correctly compose shell commands for
build, test, install, and development workflows without requiring
real subprocess execution.

Note:
    This module requires the ``scripts`` package to be on PYTHONPATH.
    Run with: ``PYTHONPATH=".:scripts" pytest tests/test_scripts.py -v``
    These tests are skipped in CI and normal pytest runs.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Protocol, TypedDict

import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch

# Skip entire module if scripts package is not available (not in PYTHONPATH)
pytest.importorskip("scripts", reason="scripts package not in PYTHONPATH; run with PYTHONPATH=.:scripts")


import scripts.test as test_script
from scripts import _test_steps, _utils, build, cli, dev, install, run_cli
from scripts._utils import RunResult

RunCommand = Sequence[str] | str
ModuleLike = ModuleType | SimpleNamespace


class RecordedOptions(TypedDict):
    """Execution options passed to the run stub."""

    check: bool
    capture: bool
    cwd: str | None
    env: Mapping[str, str] | None
    dry_run: bool


@dataclass(slots=True)
class RecordedRun:
    """Single invocation captured from a scripts command execution.

    Attributes:
        command: Command list or shell string passed to the automation runner.
        options: Keyword arguments controlling execution (capture, cwd, etc.).
    """

    command: RunCommand
    options: RecordedOptions


class RunStub(Protocol):
    """Protocol for the run function stub used in tests."""

    def __call__(
        self,
        cmd: RunCommand,
        *,
        check: bool = True,
        capture: bool = True,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        dry_run: bool = False,
    ) -> RunResult:
        """Execute or record a command invocation."""
        ...


def _remember_runs(history: list[RecordedRun]) -> RunStub:
    """Return a runner stub that appends every invocation to history.

    Tests need to inspect the commands executed by automation wrappers
    without launching real subprocesses.

    Args:
        history: Mutable list collecting RecordedRun entries.

    Returns:
        Callable mimicking scripts._utils.run.
    """

    def _run(
        cmd: RunCommand,
        *,
        check: bool = True,
        capture: bool = True,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        dry_run: bool = False,
    ) -> RunResult:
        history.append(
            RecordedRun(
                command=cmd,
                options={
                    "check": check,
                    "capture": capture,
                    "cwd": cwd,
                    "env": env,
                    "dry_run": dry_run,
                },
            )
        )
        return RunResult(0, "", "")

    return _run


def _commands_as_text(runs: list[RecordedRun]) -> list[str]:
    """Render every recorded command as a single string.

    Simplifies assertions that look for substrings inside the recorded
    commands.

    Args:
        runs: Sequence of recorded invocations.

    Returns:
        Normalised textual commands.
    """
    rendered: list[str] = []
    for run in runs:
        command = run.command
        if isinstance(command, str):
            rendered.append(command)
        else:
            rendered.append(" ".join(command))
    return rendered


def _first_command(runs: list[RecordedRun]) -> RunCommand:
    """Return the command associated with the first recorded run.

    Several tests only care about the inaugural command executed by the
    automation wrapper; this helper keeps that intent obvious.

    Args:
        runs: Recorded run list populated by _remember_runs.

    Returns:
        The first command issued.
    """
    return runs[0].command


@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_get_project_metadata_fields() -> None:
    """Verify get_project_metadata returns expected fields."""
    meta = _utils.get_project_metadata()
    assert meta.name == "bmk"
    assert meta.slug == "bmk"
    assert meta.import_package == "bmk"
    assert meta.coverage_source == "src/bmk"
    assert meta.github_tarball_url("1.2.3").endswith("/bitranox/bmk/archive/refs/tags/v1.2.3.tar.gz")
    assert meta.version
    assert meta.summary
    assert meta.author_name
    assert meta.metadata_module.as_posix().endswith("src/bmk/__init__conf__.py")


@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_build_script_uses_metadata(monkeypatch: MonkeyPatch) -> None:
    """Verify build script invokes python -m build."""
    recorded: list[RecordedRun] = []
    monkeypatch.setattr(build, "run", _remember_runs(recorded))
    runner = CliRunner()
    result = runner.invoke(cli.main, ["build"])
    assert result.exit_code == 0
    commands = _commands_as_text(recorded)
    assert any("python -m build" in cmd for cmd in commands)


@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_dev_script_installs_dev_extras(monkeypatch: MonkeyPatch) -> None:
    """Verify dev script installs package with dev extras."""
    recorded: list[RecordedRun] = []
    monkeypatch.setattr(dev, "run", _remember_runs(recorded))
    runner = CliRunner()
    result = runner.invoke(cli.main, ["dev"])
    assert result.exit_code == 0
    first_command = _first_command(recorded)
    assert isinstance(first_command, list)
    assert first_command == [sys.executable, "-m", "pip", "install", "-e", "."]


@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_install_script_installs_package(monkeypatch: MonkeyPatch) -> None:
    """Verify install script runs pip install -e."""
    recorded: list[RecordedRun] = []
    monkeypatch.setattr(install, "run", _remember_runs(recorded))
    runner = CliRunner()
    result = runner.invoke(cli.main, ["install"])
    assert result.exit_code == 0
    first_command = _first_command(recorded)
    assert isinstance(first_command, list)
    assert first_command == [sys.executable, "-m", "pip", "install", "-e", "."]


@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_run_cli_invokes_uvx_with_no_cache(monkeypatch: MonkeyPatch) -> None:
    """Verify run_cli invokes uvx with --no-cache and local dependencies."""
    recorded: list[RecordedRun] = []

    def fake_run(
        command: RunCommand,
        *,
        check: bool = True,
        capture: bool = True,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        dry_run: bool = False,
    ) -> RunResult:
        recorded.append(
            RecordedRun(
                command=command,
                options={"check": check, "capture": capture, "cwd": cwd, "env": env, "dry_run": dry_run},
            )
        )
        return RunResult(code=0, out="", err="")

    monkeypatch.setattr(run_cli, "run", fake_run)
    exit_code = run_cli.run_cli(["--help"])

    assert exit_code == 0
    assert len(recorded) == 1
    cmd = recorded[0].command
    assert isinstance(cmd, list)
    assert cmd[0] == "uvx"
    assert "--from" in cmd
    assert "--no-cache" in cmd
    assert run_cli.PROJECT.name in cmd


@pytest.mark.local_only
@pytest.mark.os_agnostic
def test_test_script_uses_pyproject_configuration(monkeypatch: MonkeyPatch) -> None:
    """Verify test script runs pytest with coverage from pyproject config."""
    recorded: list[RecordedRun] = []

    def _noop() -> None:
        return None

    def _always_false(_name: str) -> bool:
        return False

    monkeypatch.setattr(test_script, "bootstrap_dev", _noop)
    monkeypatch.setattr(_utils, "cmd_exists", _always_false)
    stub = _remember_runs(recorded)
    monkeypatch.setattr(test_script, "run", stub)
    monkeypatch.setattr(_test_steps, "run", stub)
    runner = CliRunner()
    result = runner.invoke(cli.main, ["test"])
    assert result.exit_code == 0
    pytest_commands: list[list[str]] = []
    for run in recorded:
        command = run.command
        if isinstance(command, str):
            continue
        command_list = list(command)
        if command_list[:3] == ["python", "-m", "pytest"]:
            pytest_commands.append(command_list)
    assert pytest_commands, "pytest not invoked"
    assert any(f"--cov={test_script.COVERAGE_TARGET}" in " ".join(sequence) for sequence in pytest_commands)
