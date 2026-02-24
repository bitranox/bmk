"""CLI commands for running integration tests only.

Provides ``testintegration``, ``testi``, and ``ti`` commands that execute
external shell scripts with local override support. Scripts are searched in
priority order:
1. Local override: ``<cwd>/bmk_makescripts/_btx_stagerunner.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/_btx_stagerunner.sh`` (or ``.ps1``)

The stage runner discovers and executes scripts matching ``test_integration_NN_*.sh``.

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "test_integration" for script discovery
    * ``BMK_OUTPUT_FORMAT`` - Tool output format (``json`` or ``text``)

Contents:
    * :func:`cli_testintegration` - Run integration tests only.
    * :func:`cli_testi` - Alias for ``cli_testintegration``.
    * :func:`cli_ti` - Shortest alias for ``cli_testintegration``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from ._shared import execute_script, get_script_name

logger = logging.getLogger(__name__)


def _run_test_integration(args: tuple[str, ...], *, human: bool = False) -> None:
    """Shared implementation for integration test commands.

    Args:
        args: Arguments to pass through to the test script.
        human: Use human-readable text output instead of JSON.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Test runner")

    logger.debug("Executing integration test script: %s", script_path)
    exit_code = execute_script(
        script_path,
        cwd,
        args,
        command_prefix="test_integration",
        output_format="text" if human else os.environ.get("BMK_OUTPUT_FORMAT", "json"),
    )

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("testintegration", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_testintegration(human: bool, args: tuple[str, ...]) -> None:
    """Run integration tests only (pytest -m integration).

    Executes _btx_stagerunner.sh (Linux/macOS) or _btx_stagerunner.ps1 (Windows)
    with BMK_COMMAND_PREFIX=test_integration, which discovers and runs scripts
    matching test_integration_NN_*.sh.

    Tool output defaults to JSON (machine-readable). Use --human for
    traditional text output.

    Script lookup order:
    1. <cwd>/bmk_makescripts/_btx_stagerunner.sh (local override)
    2. <package>/makescripts/_btx_stagerunner.sh (bundled default)

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_testintegration)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-integration", extra={"command": "testintegration"}):
        logger.info("Executing integration test command - this will take some minutes")
        _run_test_integration(args, human=human)


@click.command("testi", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_testi(human: bool, args: tuple[str, ...]) -> None:
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
        logger.info("Executing integration test command - this will take some minutes")
        _run_test_integration(args, human=human)


@click.command("ti", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_ti(human: bool, args: tuple[str, ...]) -> None:
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
        logger.info("Executing integration test command - this will take some minutes")
        _run_test_integration(args, human=human)


__all__ = ["cli_testintegration", "cli_testi", "cli_ti"]
