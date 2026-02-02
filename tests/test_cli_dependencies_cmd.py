"""CLI dependencies command stories: dependency check/update execution and command structure."""

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
def test_cli_dependencies_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'dependencies' command group is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["dependencies", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "update" in result.output
    assert "--update" in result.output or "-u" in result.output


@pytest.mark.os_agnostic
def test_cli_deps_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'deps' alias command group is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["deps", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'dependencies'" in result.output


@pytest.mark.os_agnostic
def test_cli_d_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'd' short alias command group is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["d", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'dependencies'" in result.output


# =============================================================================
# Subcommand existence tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("group", "subcommand", "expected_text"),
    [
        ("dependencies", "update", "Update"),
        ("dependencies", "u", "alias"),
        ("deps", "update", "Update"),
        ("deps", "u", "alias"),
        ("d", "update", "Update"),
        ("d", "u", "alias"),
    ],
)
def test_cli_dependencies_subcommands_exist(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    group: str,
    subcommand: str,
    expected_text: str,
) -> None:
    """Verify dependencies subcommands are registered with expected help text."""
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
        ("dependencies", None),
        ("dependencies", "update"),
        ("deps", None),
        ("deps", "u"),
        ("d", None),
        ("d", "update"),
    ],
)
def test_cli_dependencies_exits_with_file_not_found_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    subcommand: str | None,
) -> None:
    """Exit code is FILE_NOT_FOUND when script doesn't exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.dependencies_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    args = [group] if subcommand is None else [group, subcommand]
    result: Result = cli_runner.invoke(cli_mod.cli, args, obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_dependencies_shows_error_message_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message shows searched locations when script not found."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.dependencies_cmd.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["dependencies"], obj=production_factory)

    assert "Error: Dependencies script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


# =============================================================================
# Command prefix tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("group", "subcommand", "flag", "expected_prefix"),
    [
        ("dependencies", None, False, "deps"),
        ("dependencies", None, True, "deps_update"),  # -u flag
        ("dependencies", "update", False, "deps_update"),
        ("dependencies", "u", False, "deps_update"),
        ("deps", None, False, "deps"),
        ("deps", None, True, "deps_update"),  # -u flag
        ("deps", "update", False, "deps_update"),
        ("d", None, False, "deps"),
        ("d", "u", False, "deps_update"),
    ],
)
def test_cli_dependencies_uses_correct_command_prefix(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    subcommand: str | None,
    flag: bool,
    expected_prefix: str,
) -> None:
    """Dependencies commands use correct command prefix for stagerunner."""
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
        "bmk.adapters.cli.commands.dependencies_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.dependencies_cmd.execute_script", mock_execute)

    args = [group]
    if flag:
        args.append("-u")
    if subcommand is not None:
        args.append(subcommand)

    cli_runner.invoke(cli_mod.cli, args, obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == expected_prefix


# =============================================================================
# Exit code propagation tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_dependencies_propagates_script_exit_code(
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
        "bmk.adapters.cli.commands.dependencies_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.dependencies_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["dependencies"], obj=production_factory)

    assert result.exit_code == 1


@pytest.mark.os_agnostic
def test_cli_dependencies_returns_success_when_script_succeeds(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI returns success when dependencies script succeeds."""
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
        "bmk.adapters.cli.commands.dependencies_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.dependencies_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["dependencies"], obj=production_factory)

    assert result.exit_code == 0


# =============================================================================
# Alias equivalence tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("alias_group", "alias_cmd", "canonical_prefix"),
    [
        ("deps", None, "deps"),
        ("deps", "update", "deps_update"),
        ("deps", "u", "deps_update"),
        ("d", None, "deps"),
        ("d", "update", "deps_update"),
        ("d", "u", "deps_update"),
    ],
)
def test_cli_dependencies_aliases_invoke_same_implementation(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_group: str,
    alias_cmd: str | None,
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
        "bmk.adapters.cli.commands.dependencies_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.dependencies_cmd.execute_script", mock_execute)

    args = [alias_group] if alias_cmd is None else [alias_group, alias_cmd]
    cli_runner.invoke(cli_mod.cli, args, obj=production_factory)

    assert len(captured_prefix) == 1
    assert captured_prefix[0] == canonical_prefix


# =============================================================================
# Flag equivalence tests
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("group", "use_flag"),
    [
        ("dependencies", True),
        ("deps", True),
        ("d", True),
    ],
)
def test_cli_deps_update_flag_equivalent_to_subcommand(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    use_flag: bool,
) -> None:
    """The -u/--update flag produces same behavior as 'update' subcommand."""
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
        "bmk.adapters.cli.commands.dependencies_cmd.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr("bmk.adapters.cli.commands.dependencies_cmd.execute_script", mock_execute)

    # Test with flag
    cli_runner.invoke(cli_mod.cli, [group, "-u"], obj=production_factory)
    assert captured_prefix[-1] == "deps_update"

    # Test with subcommand
    cli_runner.invoke(cli_mod.cli, [group, "update"], obj=production_factory)
    assert captured_prefix[-1] == "deps_update"
