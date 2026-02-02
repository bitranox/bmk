"""CLI commit command stories: script execution and argument passing."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode


@pytest.mark.os_agnostic
def test_cli_commit_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'commit' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["commit", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "timestamped message" in result.output


@pytest.mark.os_agnostic
def test_cli_c_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'c' alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["c", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'commit'" in result.output


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Mock resolve_script_path that returns None."""
    return None


@pytest.mark.os_agnostic
def test_cli_commit_exits_with_file_not_found_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit code is FILE_NOT_FOUND when script doesn't exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.commit_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["commit", "test"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_commit_shows_error_message_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message shows searched locations when script not found."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.commit_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["commit", "test"], obj=production_factory)

    assert "Error: Commit script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


@pytest.mark.os_agnostic
def test_cli_commit_passes_message_arguments(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Message arguments are passed through to the script."""
    captured_args: list[tuple[Path, Path, tuple[str, ...], str]] = []

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...], *, command_prefix: str = "test") -> int:
        captured_args.append((script_path, cwd, extra_args, command_prefix))
        return 0

    script_path = tmp_path / "btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.commit_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.commit_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, ["commit", "fix", "typo", "in", "README"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][2] == ("fix", "typo", "in", "README")
    assert captured_args[0][3] == "commit"


@pytest.mark.os_agnostic
def test_cli_commit_uses_commit_prefix(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit command uses 'commit' as the command prefix for stagerunner."""
    captured_prefix: list[str] = []

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...], *, command_prefix: str = "test") -> int:
        captured_prefix.append(command_prefix)
        return 0

    script_path = tmp_path / "btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.commit_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.commit_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, ["commit", "test"], obj=production_factory)

    assert captured_prefix[0] == "commit"


@pytest.mark.os_agnostic
def test_cli_commit_propagates_script_exit_code(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Script's exit code is propagated as CLI exit code."""
    script_path = tmp_path / "btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\nexit 1")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...], *, command_prefix: str = "test") -> int:
        return 1  # Simulate nothing to commit

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.commit_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.commit_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["commit", "test"], obj=production_factory)

    assert result.exit_code == 1


@pytest.mark.os_agnostic
def test_cli_c_behaves_same_as_commit(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 'c' alias invokes the same underlying implementation."""
    captured_args: list[tuple[Path, Path, tuple[str, ...], str]] = []

    def mock_execute(script_path: Path, cwd: Path, extra_args: tuple[str, ...], *, command_prefix: str = "test") -> int:
        captured_args.append((script_path, cwd, extra_args, command_prefix))
        return 0

    script_path = tmp_path / "btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.commit_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.commit_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, ["c", "quick", "fix"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][2] == ("quick", "fix")
    assert captured_args[0][3] == "commit"
