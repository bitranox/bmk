"""CLI coverage command stories: codecov execution and command structure."""

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
def test_cli_codecov_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'codecov' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["codecov", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Upload coverage report to Codecov" in result.output


@pytest.mark.os_agnostic
def test_cli_coverage_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'coverage' alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["coverage", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'codecov'" in result.output


@pytest.mark.os_agnostic
def test_cli_cov_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'cov' short alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["cov", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'codecov'" in result.output


# =============================================================================
# Script not found tests
# =============================================================================


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Mock resolve_script_path that returns None."""
    return None


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", ["codecov", "coverage", "cov"])
def test_cli_cov_exits_with_file_not_found_when_script_missing(
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
def test_cli_cov_shows_error_message_when_script_missing(
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

    result: Result = cli_runner.invoke(cli_mod.cli, ["codecov"], obj=production_factory)

    assert "Error: Coverage script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


# =============================================================================
# Command prefix tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", ["codecov", "coverage", "cov"])
def test_cli_cov_uses_correct_command_prefix(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Coverage commands use correct command prefix for stagerunner."""
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
    monkeypatch.setattr("bmk.adapters.cli.commands.cov_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, [command], obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == "cov"


# =============================================================================
# Exit code propagation tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_cov_propagates_script_exit_code(
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
        "bmk.adapters.cli.commands.cov_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["codecov"], obj=production_factory)

    assert result.exit_code == 1


@pytest.mark.os_agnostic
def test_cli_cov_returns_success_when_script_succeeds(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI returns success when coverage script succeeds."""
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
        "bmk.adapters.cli.commands.cov_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["codecov"], obj=production_factory)

    assert result.exit_code == 0


# =============================================================================
# Alias equivalence tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize("alias_command", ["coverage", "cov"])
def test_cli_cov_aliases_invoke_same_implementation(
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
    monkeypatch.setattr("bmk.adapters.cli.commands.cov_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, [alias_command], obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == "cov"
