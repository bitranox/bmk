"""CLI commands for running integration tests only.

Provides ``testintegration``, ``testi``, and ``ti`` commands that execute
external shell scripts with local override support. Scripts are searched in
priority order:
1. Local override: ``<cwd>/bmk_makescripts/btx_stagerunner.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/btx_stagerunner.sh`` (or ``.ps1``)

The stage runner discovers and executes scripts matching ``test_integration_NN_*.sh``.

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "test_integration" for script discovery

Contents:
    * :func:`cli_testintegration` - Run integration tests only.
    * :func:`cli_testi` - Alias for ``cli_testintegration``.
    * :func:`cli_ti` - Shortest alias for ``cli_testintegration``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ..exit_codes import ExitCode
from .test_cmd import execute_script, get_script_name, resolve_script_path

logger = logging.getLogger(__name__)

_PASSTHROUGH_CONTEXT_SETTINGS = {
    **CLICK_CONTEXT_SETTINGS,
    "ignore_unknown_options": True,
    "allow_extra_args": True,
    "allow_interspersed_args": False,
}


def _run_test_integration(args: tuple[str, ...]) -> None:
    """Shared implementation for integration test commands.

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
        click.echo(f"Error: Test runner script '{script_name}' not found", err=True)
        click.echo("Searched locations:", err=True)
        click.echo(f"  - {cwd / 'bmk_makescripts' / script_name}", err=True)
        bundled = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
        click.echo(f"  - {bundled}", err=True)
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    logger.debug("Executing integration test script: %s", script_path)
    exit_code = execute_script(script_path, cwd, args, command_prefix="test_integration")

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("testintegration", context_settings=_PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_testintegration(args: tuple[str, ...]) -> None:
    """Run integration tests only (pytest -m integration).

    Executes btx_stagerunner.sh (Linux/macOS) or btx_stagerunner.ps1 (Windows)
    with BMK_COMMAND_PREFIX=test_integration, which discovers and runs scripts
    matching test_integration_NN_*.sh.

    Script lookup order:
    1. <cwd>/bmk_makescripts/btx_stagerunner.sh (local override)
    2. <package>/makescripts/btx_stagerunner.sh (bundled default)

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_testintegration)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-integration", extra={"command": "testintegration"}):
        logger.info("Executing integration test command")
        _run_test_integration(args)


@click.command("testi", context_settings=_PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_testi(args: tuple[str, ...]) -> None:
    """Run integration tests only (alias for 'testintegration').

    See ``bmk testintegration --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_testi)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-integration", extra={"command": "testi"}):
        logger.info("Executing integration test command (via alias 'testi')")
        _run_test_integration(args)


@click.command("ti", context_settings=_PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_ti(args: tuple[str, ...]) -> None:
    """Run integration tests only (alias for 'testintegration').

    See ``bmk testintegration --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_ti)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-integration", extra={"command": "ti"}):
        logger.info("Executing integration test command (via alias 'ti')")
        _run_test_integration(args)


__all__ = ["cli_testintegration", "cli_testi", "cli_ti"]
