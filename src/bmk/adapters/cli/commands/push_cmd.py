"""CLI commands for running tests, committing, and pushing to remote.

Provides ``push``, ``psh``, and ``p`` commands that run their pipeline via the Python stage runner.

Contents:
    * :func:`cli_push` - Push command.
    * :func:`cli_psh` - Alias for ``cli_push``.
    * :func:`cli_p` - Short alias for ``cli_push``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import argument
from ._shared import run_command

logger = logging.getLogger(__name__)


def run_push(message: tuple[str, ...]) -> None:
    """Execute push via the stage runner.

    Args:
        message: Commit message parts to join.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """

    cwd = Path.cwd()

    command_prefix = "push"
    exit_code = run_command(cwd, message, command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command: push
# =============================================================================


@click.command("push", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("message", nargs=-1)
def cli_push(message: tuple[str, ...]) -> None:
    """Run tests, commit changes, and push to remote.

    Updates dependencies, runs the test suite, commits all changes with a
    timestamped message, and pushes to the remote repository.

    MESSAGE is the commit message (default: "chores").

    Environment variables:
        BMK_GIT_REMOTE: Git remote (default: origin)
        BMK_GIT_BRANCH: Git branch (default: current branch)

    Example:
        bmk push                    # Commit with default message
        bmk push "fix bug"          # Commit with custom message
        bmk psh                     # Alias
        bmk p                       # Short alias
    """
    with lib_log_rich.runtime.bind(job_id="cli-push"):
        logger.info("Running push pipeline - this will take some minutes")
        run_push(message)


# =============================================================================
# Alias command: psh
# =============================================================================


@click.command("psh", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("message", nargs=-1)
def cli_psh(message: tuple[str, ...]) -> None:
    """Run tests and push (alias for 'push').

    See ``bmk push --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-push"):
        logger.info("Running push pipeline - this will take some minutes")
        run_push(message)


# =============================================================================
# Short alias command: p
# =============================================================================


@click.command("p", context_settings=CLICK_CONTEXT_SETTINGS)
@argument("message", nargs=-1)
def cli_push_p(message: tuple[str, ...]) -> None:
    """Run tests and push (short alias for 'push').

    See ``bmk push --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-push"):
        logger.info("Running push pipeline - this will take some minutes")
        run_push(message)


__all__ = ["cli_psh", "cli_push", "cli_push_p"]
