"""CLI commands for version bumping.

Provides `bump`, `bmp`, and `b` command groups with `major`/`ma`, `minor`/`m`,
and `patch`/`p` subcommands. Each executes external shell scripts via the
stagerunner with local override support.

Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/bump_{type}_*.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/bump_{type}_*.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Set to "bump_{major|minor|patch}" for script discovery

Contents:
    * :func:`cli_bump` - Version bump command group.
    * :func:`cli_bmp` - Alias for ``cli_bump``.
    * :func:`cli_b` - Short alias for ``cli_bump``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ..exit_codes import ExitCode
from .test_cmd import execute_script, get_script_name, resolve_script_path

logger = logging.getLogger(__name__)


def _run_bump(bump_type: str) -> None:
    """Execute version bump via stagerunner.

    Args:
        bump_type: Type of version bump: "major", "minor", or "patch".

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = resolve_script_path(script_name, cwd)

    if script_path is None:
        click.echo(f"Error: Bump script '{script_name}' not found", err=True)
        click.echo("Searched locations:", err=True)
        click.echo(f"  - {cwd / 'bmk_makescripts' / script_name}", err=True)
        bundled = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
        click.echo(f"  - {bundled}", err=True)
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    command_prefix = f"bump_{bump_type}"
    logger.debug("Executing bump script: %s with prefix %s", script_path, command_prefix)
    exit_code = execute_script(script_path, cwd, (), command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Main command group: bump
# =============================================================================


@click.group("bump", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_bump() -> None:
    """Bump project version (major, minor, or patch).

    Updates version in pyproject.toml and CHANGELOG.md.

    Example:
        bmk bump major      # 1.3.0 -> 2.0.0
        bmk bump minor      # 1.3.0 -> 1.4.0
        bmk bump patch      # 1.3.0 -> 1.3.1
    """


@cli_bump.command("major")
def bump_cmd_major() -> None:
    """Bump major version (X.0.0).

    Increments the major version number and resets minor and patch to 0.
    Example: 1.3.5 -> 2.0.0

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(bump_cmd_major)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "major"}):
        logger.info("Bumping major version")
        _run_bump("major")


@cli_bump.command("ma")
def bump_cmd_ma() -> None:
    """Bump major version (alias for 'major').

    See ``bmk bump major --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(bump_cmd_ma)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "major"}):
        logger.info("Bumping major version (via alias 'ma')")
        _run_bump("major")


@cli_bump.command("minor")
def bump_cmd_minor() -> None:
    """Bump minor version (X.Y.0).

    Increments the minor version number and resets patch to 0.
    Example: 1.3.5 -> 1.4.0

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(bump_cmd_minor)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "minor"}):
        logger.info("Bumping minor version")
        _run_bump("minor")


@cli_bump.command("m")
def bump_cmd_m() -> None:
    """Bump minor version (alias for 'minor').

    See ``bmk bump minor --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(bump_cmd_m)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "minor"}):
        logger.info("Bumping minor version (via alias 'm')")
        _run_bump("minor")


@cli_bump.command("patch")
def bump_cmd_patch() -> None:
    """Bump patch version (X.Y.Z).

    Increments the patch version number.
    Example: 1.3.5 -> 1.3.6

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(bump_cmd_patch)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "patch"}):
        logger.info("Bumping patch version")
        _run_bump("patch")


@cli_bump.command("p")
def bump_cmd_p() -> None:
    """Bump patch version (alias for 'patch').

    See ``bmk bump patch --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(bump_cmd_p)
        >>> result.exit_code in (0, 1, 2)
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "patch"}):
        logger.info("Bumping patch version (via alias 'p')")
        _run_bump("patch")


# =============================================================================
# Alias command group: bmp
# =============================================================================


@click.group("bmp", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_bmp() -> None:
    """Bump project version (alias for 'bump').

    See ``bmk bump --help`` for full documentation.
    """


@cli_bmp.command("major")
def bmp_cmd_major() -> None:
    """Bump major version (X.0.0)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "major"}):
        logger.info("Bumping major version (via 'bmp')")
        _run_bump("major")


@cli_bmp.command("ma")
def bmp_cmd_ma() -> None:
    """Bump major version (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "major"}):
        logger.info("Bumping major version (via 'bmp ma')")
        _run_bump("major")


@cli_bmp.command("minor")
def bmp_cmd_minor() -> None:
    """Bump minor version (X.Y.0)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "minor"}):
        logger.info("Bumping minor version (via 'bmp')")
        _run_bump("minor")


@cli_bmp.command("m")
def bmp_cmd_m() -> None:
    """Bump minor version (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "minor"}):
        logger.info("Bumping minor version (via 'bmp m')")
        _run_bump("minor")


@cli_bmp.command("patch")
def bmp_cmd_patch() -> None:
    """Bump patch version (X.Y.Z)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "patch"}):
        logger.info("Bumping patch version (via 'bmp')")
        _run_bump("patch")


@cli_bmp.command("p")
def bmp_cmd_p() -> None:
    """Bump patch version (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "patch"}):
        logger.info("Bumping patch version (via 'bmp p')")
        _run_bump("patch")


# =============================================================================
# Short alias command group: b
# =============================================================================


@click.group("b", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_b() -> None:
    """Bump project version (short alias for 'bump').

    See ``bmk bump --help`` for full documentation.
    """


@cli_b.command("major")
def b_cmd_major() -> None:
    """Bump major version (X.0.0)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "major"}):
        logger.info("Bumping major version (via 'b')")
        _run_bump("major")


@cli_b.command("ma")
def b_cmd_ma() -> None:
    """Bump major version (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "major"}):
        logger.info("Bumping major version (via 'b ma')")
        _run_bump("major")


@cli_b.command("minor")
def b_cmd_minor() -> None:
    """Bump minor version (X.Y.0)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "minor"}):
        logger.info("Bumping minor version (via 'b')")
        _run_bump("minor")


@cli_b.command("m")
def b_cmd_m() -> None:
    """Bump minor version (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "minor"}):
        logger.info("Bumping minor version (via 'b m')")
        _run_bump("minor")


@cli_b.command("patch")
def b_cmd_patch() -> None:
    """Bump patch version (X.Y.Z)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "patch"}):
        logger.info("Bumping patch version (via 'b')")
        _run_bump("patch")


@cli_b.command("p")
def b_cmd_p() -> None:
    """Bump patch version (alias)."""
    with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": "patch"}):
        logger.info("Bumping patch version (via 'b p')")
        _run_bump("patch")


__all__ = ["cli_b", "cli_bmp", "cli_bump"]
