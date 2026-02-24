"""CLI commands for running tests, committing, and pushing to remote.

Provides ``push``, ``psh``, and ``p`` commands that execute external shell
scripts via the stagerunner with local override support.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/push_*.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/push_*.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "push"
    * ``BMK_GIT_REMOTE`` - Git remote (default: origin)
    * ``BMK_GIT_BRANCH`` - Git branch (default: current branch)
    * ``BMK_COMMIT_MESSAGE`` - Commit message (default: chores)

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
from ._shared import execute_script, get_script_name

logger = logging.getLogger(__name__)


def _run_push(message: tuple[str, ...]) -> None:
    """Execute push via stagerunner.

    Args:
        message: Commit message parts to join.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Push")

    command_prefix = "push"
    logger.debug("Executing push script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, message, command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command: push
# =============================================================================


@click.command("push", context_settings=CLICK_CONTEXT_SETTINGS)
@click.argument("message", nargs=-1)
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
        _run_push(message)


# =============================================================================
# Alias command: psh
# =============================================================================


@click.command("psh", context_settings=CLICK_CONTEXT_SETTINGS)
@click.argument("message", nargs=-1)
def cli_psh(message: tuple[str, ...]) -> None:
    """Run tests and push (alias for 'push').

    See ``bmk push --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-push"):
        logger.info("Running push pipeline - this will take some minutes")
        _run_push(message)


# =============================================================================
# Short alias command: p
# =============================================================================


@click.command("p", context_settings=CLICK_CONTEXT_SETTINGS)
@click.argument("message", nargs=-1)
def cli_push_p(message: tuple[str, ...]) -> None:
    """Run tests and push (short alias for 'push').

    See ``bmk push --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-push"):
        logger.info("Running push pipeline - this will take some minutes")
        _run_push(message)


__all__ = ["cli_psh", "cli_push", "cli_push_p"]
