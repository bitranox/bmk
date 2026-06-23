"""CLI build command stories: command registration, script resolution, and execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Resolve function that always returns None."""
    return None


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_build_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'build' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["build", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Build Python wheel" in result.output


@pytest.mark.os_agnostic
def test_cli_bld_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'bld' alias is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["bld", "--help"], obj=production_factory)

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Script not found
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_build_exits_with_file_not_found_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit code is FILE_NOT_FOUND when script doesn't exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["build"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_build_shows_error_message_when_script_missing(
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

    result: Result = cli_runner.invoke(cli_mod.cli, ["build"], obj=production_factory)

    assert "Error: Build script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output
