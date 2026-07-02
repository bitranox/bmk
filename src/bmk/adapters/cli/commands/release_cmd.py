"""CLI commands for creating git tags and GitHub releases.

Provides ``release``, ``rel``, and ``r`` commands that run their pipeline via the Python stage runner.

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
from ..typed_click import argument
from ._shared import run_command

logger = logging.getLogger(__name__)


def run_release(args: tuple[str, ...]) -> None:
    """Execute release via the stage runner.

    Args:
        args: Arguments to forward to the release script.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """

    cwd = Path.cwd()

    command_prefix = "rel"
    exit_code = run_command(cwd, args, command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command: release
# =============================================================================


@click.command("release", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@argument("args", nargs=-1, type=click.UNPROCESSED)
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
        run_release(args)


# =============================================================================
# Alias command: rel
# =============================================================================


@click.command("rel", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_rel(args: tuple[str, ...]) -> None:
    """Create a release (alias for 'release').

    See ``bmk release --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-release"):
        logger.info("Creating release (via 'rel')")
        run_release(args)


# =============================================================================
# Short alias command: r
# =============================================================================


@click.command("r", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_r(args: tuple[str, ...]) -> None:
    """Create a release (short alias for 'release').

    See ``bmk release --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-release"):
        logger.info("Creating release (via 'r')")
        run_release(args)


__all__ = ["cli_r", "cli_rel", "cli_release"]
