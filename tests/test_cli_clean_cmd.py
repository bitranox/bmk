"""CLI clean command stories: clean execution and command structure."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode

# =============================================================================
# Command existence tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_clean_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'clean' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["clean", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Clean build artifacts" in result.output


@pytest.mark.os_agnostic
def test_cli_cln_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'cln' alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["cln", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'clean'" in result.output


@pytest.mark.os_agnostic
def test_cli_cl_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'cl' short alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["cl", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'clean'" in result.output


# =============================================================================
# Script not found tests
# =============================================================================


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Mock resolve_script_path that returns None."""
    return None


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", ["clean", "cln", "cl"])
def test_cli_clean_exits_with_file_not_found_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Exit code is FILE_NOT_FOUND when script doesn't exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, [command], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_clean_shows_error_message_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message shows searched locations when script not found."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["clean"], obj=production_factory)

    assert "Error: Clean script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


# =============================================================================
# Command prefix tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", ["clean", "cln", "cl"])
def test_cli_clean_uses_correct_command_prefix(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Clean commands use correct command prefix for stagerunner."""
    captured_prefix: list[str] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
    ) -> int:
        captured_prefix.append(command_prefix)
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.clean_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, [command], obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == "clean"


# =============================================================================
# Exit code propagation tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_clean_propagates_script_exit_code(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Script's exit code is propagated as CLI exit code."""
    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\nexit 1")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
    ) -> int:
        return 1  # Simulate failure

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.clean_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["clean"], obj=production_factory)

    assert result.exit_code == 1


@pytest.mark.os_agnostic
def test_cli_clean_returns_success_when_script_succeeds(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI returns success when clean script succeeds."""
    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\nexit 0")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
    ) -> int:
        return 0

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.clean_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["clean"], obj=production_factory)

    assert result.exit_code == 0


# =============================================================================
# Alias equivalence tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize("alias_command", ["cln", "cl"])
def test_cli_clean_aliases_invoke_same_implementation(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_command: str,
) -> None:
    """Alias commands invoke the same underlying implementation with correct prefix."""
    captured_prefix: list[str] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
    ) -> int:
        captured_prefix.append(command_prefix)
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.clean_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, [alias_command], obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == "clean"
