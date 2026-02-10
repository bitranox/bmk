"""CLI command for running the project CLI via uvx.

Provides ``run`` command that executes the project CLI through uvx with
automatic local dependency discovery. All arguments after ``run`` are
forwarded to the project CLI.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/_btx_stagerunner.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/_btx_stagerunner.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "run"

Contents:
    * :func:`cli_run` - Run the project CLI via uvx.
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


def _run_run(args: tuple[str, ...]) -> None:
    """Execute run via stagerunner.

    Args:
        args: Arguments to forward to the project CLI.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = resolve_script_path(script_name, cwd)

    if script_path is None:
        click.echo(f"Error: Run script '{script_name}' not found", err=True)
        click.echo("Searched locations:", err=True)
        click.echo(f"  - {cwd / 'bmk_makescripts' / script_name}", err=True)
        bundled = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
        click.echo(f"  - {bundled}", err=True)
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    command_prefix = "run"
    logger.debug("Executing run script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, args, command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("run", context_settings=_PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
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
