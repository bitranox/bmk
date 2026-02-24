"""CLI commands for running project test scripts.

Provides `test` and `t` commands that execute external shell scripts with
local override support. Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/test.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/test.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Command prefix for staged scripts
    * ``BMK_OVERRIDE_DIR`` - Per-project override directory (from config, if set)
    * ``BMK_PACKAGE_NAME`` - Package name override (from config, if set)
    * ``BMK_OUTPUT_FORMAT`` - Tool output format (``json`` or ``text``)

Contents:
    * :func:`cli_test` - Run the project test script.
    * :func:`cli_t` - Alias for ``cli_test``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import lib_log_rich.runtime
import rich_click as click

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from ..context import get_cli_context
from ._shared import execute_script, get_script_name

if TYPE_CHECKING:
    from lib_layered_config import Config

logger = logging.getLogger(__name__)


def _run_test(args: tuple[str, ...], config: Config, *, human: bool = False) -> None:
    """Shared implementation for test commands.

    Args:
        args: Arguments to pass through to the test script.
        config: Loaded layered configuration (with profile and overrides applied).
        human: Use human-readable text output instead of JSON.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Test")

    bmk_config = config.as_dict().get("bmk", {})

    logger.debug("Executing test script: %s", script_path)
    exit_code = execute_script(
        script_path,
        cwd,
        args,
        override_dir=bmk_config.get("override_dir", ""),
        package_name=bmk_config.get("package_name", ""),
        show_warnings=bmk_config.get("show_warnings", True),
        output_format="text" if human else os.environ.get("BMK_OUTPUT_FORMAT", "json"),
    )

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("test", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def cli_test(ctx: click.Context, human: bool, args: tuple[str, ...]) -> None:
    """Run the project test script.

    Executes test.sh (Linux/macOS) or test.ps1 (Windows) with the current
    working directory as the first argument, followed by any additional
    arguments passed to this command.

    Tool output defaults to JSON (machine-readable). Use --human for
    traditional text output.

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
    cli_ctx = get_cli_context(ctx)
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "test"}):
        logger.info("Executing test command - this will take some minutes")
        _run_test(args, cli_ctx.config, human=human)


@click.command("t", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def cli_t(ctx: click.Context, human: bool, args: tuple[str, ...]) -> None:
    """Run the project test script (alias for 'test').

    See ``bmk test --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_t)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    cli_ctx = get_cli_context(ctx)
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "t"}):
        logger.info("Executing test command - this will take some minutes")
        _run_test(args, cli_ctx.config, human=human)


__all__ = [
    "cli_t",
    "cli_test",
]
