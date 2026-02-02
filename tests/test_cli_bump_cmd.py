"""CLI bump command stories: version bump execution and command group structure."""

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
def test_cli_bump_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'bump' command group is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["bump", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "major" in result.output
    assert "minor" in result.output
    assert "patch" in result.output


@pytest.mark.os_agnostic
def test_cli_bmp_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'bmp' alias command group is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["bmp", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'bump'" in result.output


@pytest.mark.os_agnostic
def test_cli_b_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'b' short alias command group is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["b", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'bump'" in result.output


# =============================================================================
# Subcommand existence tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("group", "subcommand", "expected_text"),
    [
        ("bump", "major", "X.0.0"),
        ("bump", "ma", "alias"),
        ("bump", "minor", "X.Y.0"),
        ("bump", "m", "alias"),
        ("bump", "patch", "X.Y.Z"),
        ("bump", "p", "alias"),
        ("bmp", "major", "X.0.0"),
        ("bmp", "ma", "alias"),
        ("b", "major", "X.0.0"),
        ("b", "m", "alias"),
    ],
)
def test_cli_bump_subcommands_exist(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    group: str,
    subcommand: str,
    expected_text: str,
) -> None:
    """Verify bump subcommands are registered with expected help text."""
    result: Result = cli_runner.invoke(cli_mod.cli, [group, subcommand, "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert expected_text in result.output


# =============================================================================
# Script not found tests
# =============================================================================


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Mock resolve_script_path that returns None."""
    return None


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("group", "subcommand"),
    [
        ("bump", "major"),
        ("bump", "minor"),
        ("bump", "patch"),
        ("bmp", "major"),
        ("b", "p"),
    ],
)
def test_cli_bump_exits_with_file_not_found_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    subcommand: str,
) -> None:
    """Exit code is FILE_NOT_FOUND when script doesn't exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.bump_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, [group, subcommand], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_bump_shows_error_message_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message shows searched locations when script not found."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.bump_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["bump", "patch"], obj=production_factory)

    assert "Error: Bump script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


# =============================================================================
# Command prefix tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("group", "subcommand", "expected_prefix"),
    [
        ("bump", "major", "bump_major"),
        ("bump", "ma", "bump_major"),
        ("bump", "minor", "bump_minor"),
        ("bump", "m", "bump_minor"),
        ("bump", "patch", "bump_patch"),
        ("bump", "p", "bump_patch"),
        ("bmp", "major", "bump_major"),
        ("b", "m", "bump_minor"),
    ],
)
def test_cli_bump_uses_correct_command_prefix(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    subcommand: str,
    expected_prefix: str,
) -> None:
    """Bump commands use correct command prefix for stagerunner."""
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
        "bmk.adapters.cli.commands.bump_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.bump_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, [group, subcommand], obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == expected_prefix


# =============================================================================
# Exit code propagation tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_bump_propagates_script_exit_code(
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
        "bmk.adapters.cli.commands.bump_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.bump_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["bump", "patch"], obj=production_factory)

    assert result.exit_code == 1


@pytest.mark.os_agnostic
def test_cli_bump_returns_success_when_script_succeeds(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI returns success when bump script succeeds."""
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
        "bmk.adapters.cli.commands.bump_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.bump_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["bump", "minor"], obj=production_factory)

    assert result.exit_code == 0


# =============================================================================
# Alias equivalence tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("alias_group", "alias_cmd", "canonical_prefix"),
    [
        ("bmp", "major", "bump_major"),
        ("bmp", "ma", "bump_major"),
        ("bmp", "minor", "bump_minor"),
        ("bmp", "m", "bump_minor"),
        ("bmp", "patch", "bump_patch"),
        ("bmp", "p", "bump_patch"),
        ("b", "major", "bump_major"),
        ("b", "ma", "bump_major"),
        ("b", "minor", "bump_minor"),
        ("b", "m", "bump_minor"),
        ("b", "patch", "bump_patch"),
        ("b", "p", "bump_patch"),
    ],
)
def test_cli_bump_aliases_invoke_same_implementation(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_group: str,
    alias_cmd: str,
    canonical_prefix: str,
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
        "bmk.adapters.cli.commands.bump_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.bump_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, [alias_group, alias_cmd], obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == canonical_prefix
