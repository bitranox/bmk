"""CLI commands for git commit with timestamp prefix.

Provides `commit` and `c` commands that execute external shell scripts via
the stagerunner with local override support. Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/commit_*.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/commit_*.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "commit" for script discovery

Contents:
    * :func:`cli_commit` - Create a git commit with timestamped message.
    * :func:`cli_c` - Alias for ``cli_commit``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from ._shared import execute_script, get_script_name

logger = logging.getLogger(__name__)


def _run_commit(args: tuple[str, ...]) -> None:
    """Shared implementation for commit commands.

    Args:
        args: Message parts to pass to the commit script.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Commit")

    logger.debug("Executing commit script: %s", script_path)
    exit_code = execute_script(script_path, cwd, args, command_prefix="commit")

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("commit", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("message", nargs=-1, type=click.UNPROCESSED)
def cli_commit(message: tuple[str, ...]) -> None:
    """Create a git commit with timestamped message.

    All arguments are joined to form the commit message, which is
    automatically prefixed with the current local timestamp in
    'YYYY-MM-DD HH:MM:SS - ' format.

    If no message is provided, you will be prompted to enter one.

    Script lookup order (via stagerunner):
    1. <cwd>/bmk_makescripts/commit_*.sh (local override)
    2. <package>/makescripts/commit_*.sh (bundled default)

    Example:
        bmk commit fix typo in README
        # Creates commit with message: "2024-01-15 14:30:45 - fix typo in README"

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_commit)
        >>> result.exit_code in (0, 1, 2, 128)  # 0 success, 1 nothing to commit, 2 not found, 128 not a repo
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-commit", extra={"command": "commit"}):
        logger.info("Executing commit command")
        _run_commit(message)


@click.command("c", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("message", nargs=-1, type=click.UNPROCESSED)
def cli_c(message: tuple[str, ...]) -> None:
    """Create a git commit with timestamped message (alias for 'commit').

    See ``bmk commit --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_c)
        >>> result.exit_code in (0, 1, 2, 128)  # 0 success, 1 nothing to commit, 2 not found, 128 not a repo
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-commit", extra={"command": "c"}):
        logger.info("Executing commit command (via alias 'c')")
        _run_commit(message)


__all__ = ["cli_c", "cli_commit"]
