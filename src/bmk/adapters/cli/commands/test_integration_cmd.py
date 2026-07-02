"""CLI commands for running integration tests only.

Provides ``testintegration``, ``testi``, and ``ti`` commands that run the
``test_integration`` pipeline via the Python stage runner.

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
from ..typed_click import argument, option
from ._shared import run_command

logger = logging.getLogger(__name__)


def _run_test_integration(args: tuple[str, ...], *, human: bool = False) -> None:
    """Shared implementation for integration test commands.

    Args:
        args: Arguments forwarded to the pipeline's stages.
        human: Use human-readable text output instead of JSON.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """
    cwd = Path.cwd()
    exit_code = run_command(
        cwd,
        args,
        command_prefix="test_integration",
        output_format="text" if human else os.environ.get("BMK_OUTPUT_FORMAT", "json"),
    )

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("testintegration", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_testintegration(human: bool, args: tuple[str, ...]) -> None:
    """Run integration tests only (pytest -m integration).

    Tool output defaults to JSON (machine-readable). Use --human for
    traditional text output.


    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_testintegration)
        >>> result.exit_code in (0, 2)  # 0 on success
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-integration", extra={"command": "testintegration"}):
        logger.info("Executing integration test command - this will take some minutes")
        _run_test_integration(args, human=human)


@click.command("testi", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_testi(human: bool, args: tuple[str, ...]) -> None:
    """Run integration tests only (alias for 'testintegration').

    See ``bmk testintegration --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_testi)
        >>> result.exit_code in (0, 2)  # 0 on success
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-integration", extra={"command": "testi"}):
        logger.info("Executing integration test command - this will take some minutes")
        _run_test_integration(args, human=human)


@click.command("ti", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_ti(human: bool, args: tuple[str, ...]) -> None:
    """Run integration tests only (alias for 'testintegration').

    See ``bmk testintegration --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_ti)
        >>> result.exit_code in (0, 2)  # 0 on success
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-integration", extra={"command": "ti"}):
        logger.info("Executing integration test command - this will take some minutes")
        _run_test_integration(args, human=human)


__all__ = ["cli_testintegration", "cli_testi", "cli_ti"]
