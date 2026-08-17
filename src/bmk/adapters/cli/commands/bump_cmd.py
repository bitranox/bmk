"""CLI commands for version bumping.

Provides `bump`, `bmp`, and `b` command groups with `major`/`ma`, `minor`/`m`,
and `patch`/`p` subcommands. Each executes external shell scripts via the
the Python stage runner.



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
from ._shared import run_command

logger = logging.getLogger(__name__)


def _run_bump(bump_type: str) -> None:
    """Execute version bump via the stage runner.

    Args:
        bump_type: Type of version bump: "major", "minor", or "patch".

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """

    cwd = Path.cwd()

    command_prefix = f"bump_{bump_type}"
    exit_code = run_command(cwd, (), command_prefix=command_prefix)

    if exit_code != 0:
        raise SystemExit(exit_code)


# =============================================================================
# Subcommand definitions (shared across all bump groups)
# =============================================================================

_SUBCOMMAND_SPECS: tuple[tuple[str, str, str, bool], ...] = (
    ("major", "major", "Bump major version (X.0.0).", False),
    ("ma", "major", "Bump major version (alias for 'major').", True),
    ("minor", "minor", "Bump minor version (X.Y.0).", False),
    ("m", "minor", "Bump minor version (alias for 'minor').", True),
    ("patch", "patch", "Bump patch version (X.Y.Z).", False),
    ("p", "patch", "Bump patch version (alias for 'patch').", True),
)


def _make_bump_subcommand(
    name: str,
    bump_type: str,
    help_text: str,
    *,
    is_alias: bool,
) -> click.Command:
    """Create a Click command for a specific bump action.

    Args:
        name: CLI subcommand name (e.g. "major", "ma").
        bump_type: Version part to bump ("major", "minor", or "patch").
        help_text: Help string displayed by ``--help``.
        is_alias: Whether this is an alias (used in log messages).
    """
    alias_suffix = f" (via alias '{name}')" if is_alias else ""

    @click.command(name, context_settings=CLICK_CONTEXT_SETTINGS)
    def _cmd() -> None:
        with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": bump_type}):
            logger.info("Bumping %s version%s", bump_type, alias_suffix)
            _run_bump(bump_type)

    _cmd.help = help_text
    return _cmd


def _make_bump_group(name: str, help_text: str) -> click.Group:
    """Create a bump command group and register all subcommands on it.

    Args:
        name: CLI group name (e.g. "bump", "bmp", "b").
        help_text: Help string displayed by ``--help``.
    """

    @click.group(name, context_settings=CLICK_CONTEXT_SETTINGS)
    def _group() -> None:
        pass

    _group.help = help_text

    for cmd_name, bump_type, cmd_help, is_alias in _SUBCOMMAND_SPECS:
        _group.add_command(_make_bump_subcommand(cmd_name, bump_type, cmd_help, is_alias=is_alias))

    return _group


# =============================================================================
# Command groups
# =============================================================================

cli_bump: click.Group = _make_bump_group(
    "bump",
    "Bump project version (major, minor, or patch).\n\n"
    "Updates version in pyproject.toml and CHANGELOG.md. A non-final version "
    "(a pre-release or dev release) is FINALIZED rather than stepped past, so the "
    "release it was rehearsing stays reachable.\n\n"
    "Example:\n"
    "    bmk bump major      # 1.3.0 -> 2.0.0\n"
    "    bmk bump minor      # 1.3.0 -> 1.4.0\n"
    "    bmk bump patch      # 1.3.0 -> 1.3.1\n"
    "    bmk bump patch      # 1.3.0b2 -> 1.3.0   (finalized, not 1.3.1)",
)

cli_bmp: click.Group = _make_bump_group(
    "bmp",
    "Bump project version (alias for 'bump').\n\nSee ``bmk bump --help`` for full documentation.",
)

cli_b: click.Group = _make_bump_group(
    "b",
    "Bump project version (short alias for 'bump').\n\nSee ``bmk bump --help`` for full documentation.",
)


__all__ = ["cli_b", "cli_bmp", "cli_bump"]
