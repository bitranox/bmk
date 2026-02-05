"""CLI commands for uploading coverage reports to Codecov.

Provides ``codecov``, ``coverage``, and ``cov`` commands that execute external
shell scripts via the stagerunner with local override support.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/cov_*.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/cov_*.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "cov"

Contents:
    * :func:`cli_codecov` - Coverage upload command.
    * :func:`cli_coverage` - Alias for ``cli_codecov``.
    * :func:`cli_cov` - Short alias for ``cli_codecov``.
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


def _run_cov() -> None:
    """Execute coverage upload via stagerunner.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = resolve_script_path(script_name, cwd)

    if script_path is None:
        click.echo(f"Error: Coverage script '{script_name}' not found", err=True)
        click.echo("Searched locations:", err=True)
        click.echo(f"  - {cwd / 'bmk_makescripts' / script_name}", err=True)
        bundled = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
        click.echo(f"  - {bundled}", err=True)
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    command_prefix = "cov"
    logger.debug("Executing coverage script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, (), command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command: codecov
# =============================================================================


@click.command("codecov", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_codecov() -> None:
    """Upload coverage report to Codecov.

    Uploads the coverage.xml report to Codecov using the official Codecov CLI.
    Requires CODECOV_TOKEN to be set in environment or .env file.

    Example:
        bmk codecov     # Upload coverage
        bmk coverage    # Alias
        bmk cov         # Short alias
    """
    with lib_log_rich.runtime.bind(job_id="cli-codecov"):
        logger.info("Uploading coverage to Codecov")
        _run_cov()


# =============================================================================
# Alias command: coverage
# =============================================================================


@click.command("coverage", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_coverage() -> None:
    """Upload coverage report (alias for 'codecov').

    See ``bmk codecov --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-codecov"):
        logger.info("Uploading coverage to Codecov (via 'coverage')")
        _run_cov()


# =============================================================================
# Short alias command: cov
# =============================================================================


@click.command("cov", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_cov() -> None:
    """Upload coverage report (short alias for 'codecov').

    See ``bmk codecov --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-codecov"):
        logger.info("Uploading coverage to Codecov (via 'cov')")
        _run_cov()


__all__ = ["cli_codecov", "cli_cov", "cli_coverage"]
