"""CLI commands for cleaning build artifacts and cache directories.

Provides ``clean``, ``cln``, and ``cl`` commands that run their pipeline via the Python stage runner.

Contents:
    * :func:`cli_clean` - Clean command.
    * :func:`cli_cln` - Alias for ``cli_clean``.
    * :func:`cli_cl` - Short alias for ``cli_clean``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ._shared import run_command

logger = logging.getLogger(__name__)


def _run_clean() -> None:
    """Run the clean pipeline.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """

    cwd = Path.cwd()

    command_prefix = "clean"
    exit_code = run_command(cwd, (), command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command: clean
# =============================================================================


@click.command("clean", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_clean() -> None:
    """Clean build artifacts and cache directories.

    Removes common build artifacts, cache directories, and temporary files
    from the project. Reads patterns from pyproject.toml [tool.clean].patterns
    or uses built-in defaults.

    Example:
        bmk clean     # Clean build artifacts
        bmk cln       # Alias
        bmk cl        # Short alias
    """
    with lib_log_rich.runtime.bind(job_id="cli-clean"):
        logger.info("Cleaning build artifacts")
        _run_clean()


# =============================================================================
# Alias command: cln
# =============================================================================


@click.command("cln", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_cln() -> None:
    """Clean build artifacts (alias for 'clean').

    See ``bmk clean --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-clean"):
        logger.info("Cleaning build artifacts (via 'cln')")
        _run_clean()


# =============================================================================
# Short alias command: cl
# =============================================================================


@click.command("cl", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_cl() -> None:
    """Clean build artifacts (short alias for 'clean').

    See ``bmk clean --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-clean"):
        logger.info("Cleaning build artifacts (via 'cl')")
        _run_clean()


__all__ = ["cli_cl", "cli_clean", "cli_cln"]
