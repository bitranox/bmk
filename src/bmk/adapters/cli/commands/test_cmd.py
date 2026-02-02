"""CLI commands for running project test scripts.

Provides `test` and `t` commands that execute external shell scripts with
local override support. Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/test.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/test.sh`` (or ``.ps1``)

Contents:
    * :func:`cli_test` - Run the project test script.
    * :func:`cli_t` - Alias for ``cli_test``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ..exit_codes import ExitCode

logger = logging.getLogger(__name__)

# Context settings for pass-through commands that accept arbitrary arguments.
# ignore_unknown_options: Allows --flags to be passed through to the script
# allow_extra_args: Allows extra positional arguments
# allow_interspersed_args: Allows mixing options and arguments
_PASSTHROUGH_CONTEXT_SETTINGS = {
    **CLICK_CONTEXT_SETTINGS,
    "ignore_unknown_options": True,
    "allow_extra_args": True,
    "allow_interspersed_args": False,
}


def get_script_name() -> str:
    """Return OS-appropriate script name.

    Returns:
        ``test.ps1`` on Windows, ``test.sh`` otherwise.
    """
    return "test.ps1" if sys.platform == "win32" else "test.sh"


def resolve_script_path(script_name: str, cwd: Path) -> Path | None:
    """Find script in local override or bundled location.

    Args:
        script_name: Name of the script file (e.g., ``test.sh``).
        cwd: Current working directory to check for local override.

    Returns:
        Path to the script if found, None otherwise.
    """
    local_script = cwd / "bmk_makescripts" / script_name
    if local_script.is_file():
        return local_script

    # Path from test_cmd.py up to bmk package: commands -> cli -> adapters -> bmk
    bundled_script = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
    if bundled_script.is_file():
        return bundled_script

    return None


def execute_script(script_path: Path, cwd: Path, extra_args: tuple[str, ...]) -> int:
    """Execute script with cwd as first argument.

    Args:
        script_path: Path to the script to execute.
        cwd: Current working directory (passed as first argument to script).
        extra_args: Additional arguments to pass to the script.

    Returns:
        Exit code from the script execution.
    """
    if script_path.suffix == ".ps1":
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            str(cwd),
            *extra_args,
        ]
    else:
        cmd = [str(script_path), str(cwd), *extra_args]

    result = subprocess.run(cmd, check=False)  # noqa: S603
    return result.returncode


def _run_test(args: tuple[str, ...]) -> None:
    """Shared implementation for test commands.

    Args:
        args: Arguments to pass through to the test script.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = resolve_script_path(script_name, cwd)

    if script_path is None:
        click.echo(f"Error: Test script '{script_name}' not found", err=True)
        click.echo("Searched locations:", err=True)
        click.echo(f"  - {cwd / 'bmk_makescripts' / script_name}", err=True)
        bundled = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
        click.echo(f"  - {bundled}", err=True)
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    logger.debug("Executing test script: %s", script_path)
    exit_code = execute_script(script_path, cwd, args)

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("test", context_settings=_PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_test(args: tuple[str, ...]) -> None:
    """Run the project test script.

    Executes test.sh (Linux/macOS) or test.ps1 (Windows) with the current
    working directory as the first argument, followed by any additional
    arguments passed to this command.

    Script lookup order:
    1. <cwd>/bmk_makescripts/test.sh (local override)
    2. <package>/makescripts/test.sh (bundled default)

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_test)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "test"}):
        logger.info("Executing test command")
        _run_test(args)


@click.command("t", context_settings=_PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_t(args: tuple[str, ...]) -> None:
    """Run the project test script (alias for 'test').

    See ``bmk test --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_t)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "t"}):
        logger.info("Executing test command (via alias 't')")
        _run_test(args)


__all__ = ["cli_t", "cli_test", "execute_script", "get_script_name", "resolve_script_path"]
