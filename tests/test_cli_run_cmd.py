"""CLI run command stories: command registration, script resolution, and execution."""

from __future__ import annotations

import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_run_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'run' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["run", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Run the project CLI" in result.output


# ---------------------------------------------------------------------------
# Script not found
# ---------------------------------------------------------------------------


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Resolve function that always returns None."""
    return None


@pytest.mark.os_agnostic
def test_cli_run_exits_with_file_not_found_when_script_missing(
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

    result: Result = cli_runner.invoke(cli_mod.cli, ["run"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_run_shows_error_message_when_script_missing(
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

    result: Result = cli_runner.invoke(cli_mod.cli, ["run"], obj=production_factory)

    assert "Error: Run script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


# ---------------------------------------------------------------------------
# Execution with real scripts
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_cli_run_executes_script_with_run_command_prefix(
    tmp_path: Path,
    clear_config_cache: None,
) -> None:
    """run command sets BMK_COMMAND_PREFIX=run in subprocess."""
    from bmk.adapters.cli.commands.test_cmd import execute_script

    output_file = tmp_path / "env_output.txt"
    script = tmp_path / "capture_env.sh"
    script.write_text(
        f'#!/bin/bash\necho "$BMK_COMMAND_PREFIX" > "{output_file}"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    execute_script(script, tmp_path, (), command_prefix="run")

    assert output_file.read_text().strip() == "run"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_cli_run_forwards_extra_arguments(
    tmp_path: Path,
    clear_config_cache: None,
) -> None:
    """Extra arguments are passed through to the script."""
    from bmk.adapters.cli.commands.test_cmd import execute_script

    output_file = tmp_path / "args_output.txt"
    script = tmp_path / "capture_args.sh"
    script.write_text(
        f'#!/bin/bash\necho "$@" > "{output_file}"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    execute_script(script, tmp_path, ("--help", "--version"), command_prefix="run")

    assert output_file.read_text().strip() == "--help --version"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_cli_run_propagates_nonzero_exit_code(
    tmp_path: Path,
    clear_config_cache: None,
) -> None:
    """Non-zero exit code from script is returned."""
    from bmk.adapters.cli.commands.test_cmd import execute_script

    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/bash\nexit 7\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    result = execute_script(script, tmp_path, (), command_prefix="run")

    assert result == 7
