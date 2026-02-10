"""CLI commands for cleaning build artifacts and cache directories.

Provides ``clean``, ``cln``, and ``cl`` commands that execute external shell
scripts via the stagerunner with local override support.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/clean_*.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/clean_*.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "clean"

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
from .test_cmd import execute_script, get_script_name

logger = logging.getLogger(__name__)


def _run_clean() -> None:
    """Execute clean via stagerunner.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Clean")

    command_prefix = "clean"
    logger.debug("Executing clean script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, (), command_prefix=command_prefix)

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


__all__ = ["cli_cl", "cli_cln", "cli_clean"]
