"""CLI command for running the project CLI via uvx.

Provides ``run`` command that executes the project CLI through uvx with
automatic local dependency discovery. All arguments after ``run`` are
forwarded to the project CLI.



Contents:
    * :func:`cli_run` - Run the project CLI via uvx.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from ..typed_click import argument
from ._shared import run_command

logger = logging.getLogger(__name__)


def _run_run(args: tuple[str, ...]) -> None:
    """Execute run via the stage runner.

    Args:
        args: Arguments to forward to the project CLI.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """

    cwd = Path.cwd()

    command_prefix = "run"
    exit_code = run_command(cwd, args, command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("run", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_run(args: tuple[str, ...]) -> None:
    """Run the project CLI via uvx with local dependency discovery.

    Invokes the project CLI through uvx using the local development version.
    Discovers sibling directories matching declared dependencies and includes
    them automatically. All arguments are forwarded to the project CLI.

    Example:
        bmk run --help        # Show project CLI help
        bmk run info          # Run the project's info command
        bmk run --version     # Show project version
    """
    with lib_log_rich.runtime.bind(job_id="cli-run", extra={"command": "run"}):
        logger.info("Executing run command")
        _run_run(args)


__all__ = ["cli_run"]
