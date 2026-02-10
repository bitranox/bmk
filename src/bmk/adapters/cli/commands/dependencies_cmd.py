"""CLI commands for dependency checking and updating.

Provides `dependencies`, `deps`, and `d` command groups with `update`/`u`
subcommands. Each executes external shell scripts via the stagerunner with
local override support.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/dependencies_*.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/dependencies_*.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "dependencies" or "deps_update"

Contents:
    * :func:`cli_dependencies` - Dependency management command group.
    * :func:`cli_deps` - Alias for ``cli_dependencies``.
    * :func:`cli_d` - Short alias for ``cli_dependencies``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from .test_cmd import execute_script, get_script_name

logger = logging.getLogger(__name__)


def _run_dependencies(action: str) -> None:
    """Execute dependency check/update via stagerunner.

    Args:
        action: Empty string for check, "update" for update.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Dependencies")

    command_prefix = f"deps_{action}" if action else "deps"
    logger.debug("Executing dependencies script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, (), command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command group: dependencies
# =============================================================================


@click.group("dependencies", invoke_without_command=True, context_settings=CLICK_CONTEXT_SETTINGS)
@click.option("-u", "--update", is_flag=True, help="Update outdated dependencies")
@click.pass_context
def cli_dependencies(ctx: click.Context, update: bool) -> None:
    """Check and manage project dependencies.

    Compares dependencies in pyproject.toml against latest PyPI versions.

    Example:
        bmk dependencies           # Check for outdated dependencies
        bmk dependencies update    # Update outdated dependencies
        bmk deps -u                # Update using flag shorthand
    """
    if ctx.invoked_subcommand is None:
        with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update" if update else "check"}):
            if update:
                logger.info("Updating dependencies")
                _run_dependencies("update")
            else:
                logger.info("Checking dependencies")
                _run_dependencies("")


@cli_dependencies.command("update")
def dependencies_cmd_update() -> None:
    """Update outdated dependencies to latest versions.

    Reads pyproject.toml, checks for newer versions on PyPI, and updates
    dependency specifications in-place.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(dependencies_cmd_update)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update"}):
        logger.info("Updating dependencies")
        _run_dependencies("update")


@cli_dependencies.command("u")
def dependencies_cmd_u() -> None:
    """Update outdated dependencies (alias for 'update').

    See ``bmk dependencies update --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(dependencies_cmd_u)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update"}):
        logger.info("Updating dependencies (via alias 'u')")
        _run_dependencies("update")


# =============================================================================
# Alias command group: deps
# =============================================================================


@click.group("deps", invoke_without_command=True, context_settings=CLICK_CONTEXT_SETTINGS)
@click.option("-u", "--update", is_flag=True, help="Update outdated dependencies")
@click.pass_context
def cli_deps(ctx: click.Context, update: bool) -> None:
    """Check and manage project dependencies (alias for 'dependencies').

    See ``bmk dependencies --help`` for full documentation.
    """
    if ctx.invoked_subcommand is None:
        with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update" if update else "check"}):
            if update:
                logger.info("Updating dependencies (via 'deps')")
                _run_dependencies("update")
            else:
                logger.info("Checking dependencies (via 'deps')")
                _run_dependencies("")


@cli_deps.command("update")
def deps_cmd_update() -> None:
    """Update outdated dependencies to latest versions."""
    with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update"}):
        logger.info("Updating dependencies (via 'deps')")
        _run_dependencies("update")


@cli_deps.command("u")
def deps_cmd_u() -> None:
    """Update outdated dependencies (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update"}):
        logger.info("Updating dependencies (via 'deps u')")
        _run_dependencies("update")


# =============================================================================
# Short alias command group: d
# =============================================================================


@click.group("d", invoke_without_command=True, context_settings=CLICK_CONTEXT_SETTINGS)
@click.option("-u", "--update", is_flag=True, help="Update outdated dependencies")
@click.pass_context
def cli_d(ctx: click.Context, update: bool) -> None:
    """Check and manage project dependencies (short alias for 'dependencies').

    See ``bmk dependencies --help`` for full documentation.
    """
    if ctx.invoked_subcommand is None:
        with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update" if update else "check"}):
            if update:
                logger.info("Updating dependencies (via 'd')")
                _run_dependencies("update")
            else:
                logger.info("Checking dependencies (via 'd')")
                _run_dependencies("")


@cli_d.command("update")
def d_cmd_update() -> None:
    """Update outdated dependencies to latest versions."""
    with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update"}):
        logger.info("Updating dependencies (via 'd')")
        _run_dependencies("update")


@cli_d.command("u")
def d_cmd_u() -> None:
    """Update outdated dependencies (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-dependencies", extra={"action": "update"}):
        logger.info("Updating dependencies (via 'd u')")
        _run_dependencies("update")


__all__ = ["cli_d", "cli_deps", "cli_dependencies"]
