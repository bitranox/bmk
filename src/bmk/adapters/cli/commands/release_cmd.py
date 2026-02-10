"""CLI commands for creating git tags and GitHub releases.

Provides ``release``, ``rel``, and ``r`` commands that execute external shell
scripts via the stagerunner with local override support.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/_btx_stagerunner.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/_btx_stagerunner.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "rel"

Contents:
    * :func:`cli_release` - Release command.
    * :func:`cli_rel` - Alias for ``cli_release``.
    * :func:`cli_r` - Short alias for ``cli_release``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from .test_cmd import execute_script, get_script_name

logger = logging.getLogger(__name__)


def _run_release(args: tuple[str, ...]) -> None:
    """Execute release via stagerunner.

    Args:
        args: Arguments to forward to the release script.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Release")

    command_prefix = "rel"
    logger.debug("Executing release script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, args, command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command: release
# =============================================================================


@click.command("release", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_release(args: tuple[str, ...]) -> None:
    """Create a versioned release with git tag and GitHub release.

    Reads the version from pyproject.toml, creates an annotated git tag,
    pushes to the remote, and optionally creates a GitHub release via gh CLI.

    Example:
        bmk release       # Create release from current version
        bmk rel           # Alias
        bmk r             # Short alias
    """
    with lib_log_rich.runtime.bind(job_id="cli-release"):
        logger.info("Creating release")
        _run_release(args)


# =============================================================================
# Alias command: rel
# =============================================================================


@click.command("rel", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_rel(args: tuple[str, ...]) -> None:
    """Create a release (alias for 'release').

    See ``bmk release --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-release"):
        logger.info("Creating release (via 'rel')")
        _run_release(args)


# =============================================================================
# Short alias command: r
# =============================================================================


@click.command("r", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_r(args: tuple[str, ...]) -> None:
    """Create a release (short alias for 'release').

    See ``bmk release --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-release"):
        logger.info("Creating release (via 'r')")
        _run_release(args)


__all__ = ["cli_r", "cli_rel", "cli_release"]
