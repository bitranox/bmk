"""CLI commands for building Python wheel and sdist artifacts.

Provides ``build`` and ``bld`` commands that run their pipeline via the Python stage runner.

Contents:
    * :func:`cli_build` - Build command.
    * :func:`cli_bld` - Alias for ``cli_build``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ._shared import run_command

logger = logging.getLogger(__name__)


def _run_build() -> None:
    """Execute build via the stage runner.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """

    cwd = Path.cwd()

    command_prefix = "bld"
    exit_code = run_command(cwd, (), command_prefix=command_prefix)

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
