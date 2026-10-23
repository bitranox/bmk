"""CLI commands for running project test scripts.

Provides `test` and `t` commands that run their pipeline via the Python stage runner.

Contents:
    * :func:`cli_test` - Run the project test script.
    * :func:`cli_t` - Alias for ``cli_test``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..config_load import require_config
from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from ..context import get_cli_context
from ..typed_click import argument, option
from ._shared import resolve_output_format, run_command

logger = logging.getLogger(__name__)


def _run_test(args: tuple[str, ...], *, human: bool = False) -> None:
    """Shared implementation for test commands.

    Args:
        args: Arguments forwarded to the pipeline's stages.
        human: Use human-readable text output instead of JSON.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """
    exit_code = run_command(
        Path.cwd(),
        args,
        command_prefix="test",
        output_format=resolve_output_format(human=human),
    )

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("test", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def cli_test(ctx: click.Context, human: bool, args: tuple[str, ...]) -> None:
    """Run the project test script.

    Tool output defaults to JSON (machine-readable). Use --human for
    traditional text output.


    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_test)
        >>> result.exit_code in (0, 2)  # 0 on success
        True
    """
    # Read only to stop with exit 78 when it failed to load; run_command reads [bmk] itself.
    require_config(ctx, get_cli_context(ctx))
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "test"}):
        logger.info("Executing test command - this will take some minutes")
        _run_test(args, human=human)


@click.command("t", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def cli_t(ctx: click.Context, human: bool, args: tuple[str, ...]) -> None:
    """Run the project test script (alias for 'test').

    See ``bmk test --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_t)
        >>> result.exit_code in (0, 2)  # 0 on success
        True
    """
    # Read only to stop with exit 78 when it failed to load; run_command reads [bmk] itself.
    require_config(ctx, get_cli_context(ctx))
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "t"}):
        logger.info("Executing test command - this will take some minutes")
        _run_test(args, human=human)


__all__ = [
    "cli_t",
    "cli_test",
]
