"""CLI test command stories: script resolution, execution, and argument passing."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.commands.test_cmd import (
    execute_script,
    get_script_name,
    resolve_script_path,
)
from bmk.adapters.cli.exit_codes import ExitCode


@pytest.mark.os_agnostic
def test_get_script_name_returns_sh_on_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_script_name returns _btx_stagerunner.sh on Linux/macOS."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert get_script_name() == "_btx_stagerunner.sh"


@pytest.mark.os_agnostic
def test_get_script_name_returns_ps1_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_script_name returns _btx_stagerunner.ps1 on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert get_script_name() == "_btx_stagerunner.ps1"


@pytest.mark.os_agnostic
def test_resolve_script_path_prefers_local_override(tmp_path: Path) -> None:
    """Local override in bmk_makescripts takes precedence over bundled."""
    local_dir = tmp_path / "bmk_makescripts"
    local_dir.mkdir()
    local_script = local_dir / "_btx_stagerunner.sh"
    local_script.write_text("#!/bin/bash\necho local")

    result = resolve_script_path("_btx_stagerunner.sh", tmp_path)

    assert result == local_script


@pytest.mark.os_agnostic
def test_resolve_script_path_falls_back_to_bundled(tmp_path: Path) -> None:
    """Falls back to bundled script when no local override exists."""
    result = resolve_script_path("_btx_stagerunner.sh", tmp_path)

    assert result is not None
    assert result.name == "_btx_stagerunner.sh"
    assert "makescripts" in str(result)
    assert result.is_file()


@pytest.mark.os_agnostic
def test_resolve_script_path_returns_none_when_not_found(tmp_path: Path) -> None:
    """Returns None when neither local nor bundled script exists."""
    result = resolve_script_path("nonexistent_script.sh", tmp_path)

    assert result is None


@pytest.mark.os_agnostic
def test_execute_script_uses_powershell_for_ps1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PowerShell scripts are invoked with powershell.exe."""
    captured_cmd: list[list[str]] = []
    captured_env: list[dict[str, str]] = []

    def mock_run(
        cmd: list[str], *, check: bool, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured_cmd.append(cmd)
        captured_env.append(env or {})
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    script_path = tmp_path / "_btx_stagerunner.ps1"
    script_path.write_text("# test")
    cwd = tmp_path / "project"

    execute_script(script_path, cwd, ("arg1", "arg2"))

    assert captured_cmd[0][0] == "powershell"
    assert "-ExecutionPolicy" in captured_cmd[0]
    assert "Bypass" in captured_cmd[0]
    assert "-File" in captured_cmd[0]
    assert str(script_path) in captured_cmd[0]
    assert "arg1" in captured_cmd[0]
    assert "arg2" in captured_cmd[0]
    assert captured_env[0].get("BMK_PROJECT_DIR") == str(cwd)
    assert captured_env[0].get("BMK_COMMAND_PREFIX") == "test"


@pytest.mark.os_agnostic
def test_execute_script_runs_shell_script_directly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Shell scripts are invoked directly with BMK_PROJECT_DIR and BMK_COMMAND_PREFIX env vars."""
    captured_cmd: list[list[str]] = []
    captured_env: list[dict[str, str]] = []

    def mock_run(
        cmd: list[str], *, check: bool, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        captured_cmd.append(cmd)
        captured_env.append(env or {})
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")
    cwd = tmp_path / "project"

    execute_script(script_path, cwd, ("--verbose",))

    assert captured_cmd[0][0] == str(script_path)
    assert captured_cmd[0][1] == "--verbose"
    assert captured_env[0].get("BMK_PROJECT_DIR") == str(cwd)
    assert captured_env[0].get("BMK_COMMAND_PREFIX") == "test"


@pytest.mark.os_agnostic
def test_execute_script_returns_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns the script's exit code."""

    def mock_run(
        cmd: list[str], *, check: bool, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, returncode=42)

    monkeypatch.setattr(subprocess, "run", mock_run)
    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\nexit 42")

    result = execute_script(script_path, script_path.parent, ())

    assert result == 42


@pytest.mark.os_agnostic
def test_cli_test_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'test' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["test", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Run the project test script" in result.output


@pytest.mark.os_agnostic
def test_cli_t_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 't' alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["t", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'test'" in result.output


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Mock resolve_script_path that returns None."""
    return None


@pytest.mark.os_agnostic
def test_cli_test_exits_with_file_not_found_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit code is FILE_NOT_FOUND when script doesn't exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["test"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_test_shows_error_message_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message shows searched locations when script not found."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["test"], obj=production_factory)

    assert "Error: Test script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


@pytest.mark.os_agnostic
def test_cli_test_passes_cwd_as_first_argument(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Current working directory is passed as first argument to script."""
    captured_args: list[tuple[Path, Path, tuple[str, ...]]] = []

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...]) -> int:
        captured_args.append((script_path, cwd, extra_args))
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.test_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, ["test"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][1] == tmp_path


@pytest.mark.os_agnostic
def test_cli_test_passes_extra_arguments(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra CLI arguments are passed through to the script."""
    captured_args: list[tuple[Path, Path, tuple[str, ...]]] = []

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...]) -> int:
        captured_args.append((script_path, cwd, extra_args))
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.test_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, ["test", "--verbose", "--coverage"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][2] == ("--verbose", "--coverage")


@pytest.mark.os_agnostic
def test_cli_test_propagates_script_exit_code(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Script's exit code is propagated as CLI exit code."""
    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\nexit 42")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...]) -> int:
        return 42

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["test"], obj=production_factory)

    assert result.exit_code == 42


@pytest.mark.os_agnostic
def test_cli_t_behaves_same_as_test(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 't' alias invokes the same underlying implementation."""
    captured_args: list[tuple[Path, Path, tuple[str, ...]]] = []

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...]) -> int:
        captured_args.append((script_path, cwd, extra_args))
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.test_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, ["t", "--fast"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][2] == ("--fast",)
