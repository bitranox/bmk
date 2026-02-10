"""CLI commands for building Python wheel and sdist artifacts.

Provides ``build``, ``bld``, and ``b`` commands that execute external shell
scripts via the stagerunner with local override support.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/bld_*.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/bld_*.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "bld"

Contents:
    * :func:`cli_build` - Build command.
    * :func:`cli_bld` - Alias for ``cli_build``.
    * :func:`cli_b` - Short alias for ``cli_build``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from .test_cmd import execute_script, get_script_name

logger = logging.getLogger(__name__)


def _run_build() -> None:
    """Execute build via stagerunner.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Build")

    command_prefix = "bld"
    logger.debug("Executing build script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, (), command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command: build
# =============================================================================


@click.command("build", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_build() -> None:
    """Build Python wheel and sdist artifacts.

    Builds distribution artifacts for PyPI using ``python -m build``.
    The dist/ directory is cleaned before building to avoid stale artifacts.

    Example:
        bmk build     # Build wheel and sdist
        bmk bld       # Alias
    """
    with lib_log_rich.runtime.bind(job_id="cli-build"):
        logger.info("Building Python artifacts")
        _run_build()


# =============================================================================
# Alias command: bld
# =============================================================================


@click.command("bld", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_bld() -> None:
    """Build Python artifacts (alias for 'build').

    See ``bmk build --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-build"):
        logger.info("Building Python artifacts (via 'bld')")
        _run_build()


__all__ = ["cli_bld", "cli_build"]
