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
from typing import NamedTuple

import lib_log_rich.runtime
import rich_click as click

from bmk.domain.enums import BumpPart

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import get_current_context
from ._shared import run_command

logger = logging.getLogger(__name__)


def _run_bump(part: BumpPart) -> None:
    """Execute version bump via the stage runner.

    Args:
        part: Version component to bump.

    Raises:
        click.exceptions.Exit: With FILE_NOT_FOUND (2) if no pipeline is defined,
            or the pipeline's exit code on failure.
    """

    cwd = Path.cwd()

    # ``.value``, never the member itself: f-string formatting of a ``(str, Enum)`` member
    # yields the value on Python 3.10 but ``BumpPart.MAJOR`` on 3.11+.
    command_prefix = f"bump_{part.value}"
    exit_code = run_command(cwd, (), command_prefix=command_prefix)

    if exit_code != 0:
        get_current_context().exit(exit_code)


# =============================================================================
# Subcommand definitions (shared across all bump groups)
# =============================================================================


class _BumpSpec(NamedTuple):
    """One bump subcommand: its CLI name, the part it bumps, and its help text.

    Attributes:
        name: CLI subcommand name (e.g. "major", "ma").
        part: Version component the subcommand bumps.
        help: Help string displayed by ``--help``.
        is_alias: Whether the name is a short alias (used in log messages).
    """

    name: str
    part: BumpPart
    help: str
    is_alias: bool


_SUBCOMMAND_SPECS: tuple[_BumpSpec, ...] = (
    _BumpSpec("major", BumpPart.MAJOR, "Bump major version (X.0.0).", is_alias=False),
    _BumpSpec("ma", BumpPart.MAJOR, "Bump major version (alias for 'major').", is_alias=True),
    _BumpSpec("minor", BumpPart.MINOR, "Bump minor version (X.Y.0).", is_alias=False),
    _BumpSpec("m", BumpPart.MINOR, "Bump minor version (alias for 'minor').", is_alias=True),
    _BumpSpec("patch", BumpPart.PATCH, "Bump patch version (X.Y.Z).", is_alias=False),
    _BumpSpec("p", BumpPart.PATCH, "Bump patch version (alias for 'patch').", is_alias=True),
)


def _make_bump_subcommand(spec: _BumpSpec) -> click.Command:
    """Create a Click command for a specific bump action.

    Args:
        spec: The subcommand's name, bumped part, help text and alias flag.
    """
    alias_suffix = f" (via alias '{spec.name}')" if spec.is_alias else ""
    part = spec.part

    @click.command(spec.name, context_settings=CLICK_CONTEXT_SETTINGS)
    def _cmd() -> None:
        # The log record and its structured field carry the wire string, as they did before
        # the part was typed: ``%s`` of a member would render ``BumpPart.MAJOR``.
        with lib_log_rich.runtime.bind(job_id="cli-bump", extra={"type": part.value}):
            logger.info("Bumping %s version%s", part.value, alias_suffix)
            _run_bump(part)

    _cmd.help = spec.help
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

    for spec in _SUBCOMMAND_SPECS:
        _group.add_command(_make_bump_subcommand(spec))

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
