"""CLI command for running custom pipelines.

Provides the ``custom`` command that runs a user-defined pipeline named by its
first argument (e.g. ``deploy``). Custom pipelines are defined declaratively
under ``[tool.bmk.pipelines.<name>]`` in ``pyproject.toml`` or in
``bmk_makescripts/stages.toml``.

Contents:
    * :func:`cli_custom` - Run a custom pipeline by name.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import lib_log_rich.runtime
import rich_click as click

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from ..context import get_cli_context
from ..typed_click import argument
from ._shared import run_command

if TYPE_CHECKING:
    from lib_layered_config import Config

_RE_COMMAND_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

logger = logging.getLogger(__name__)


def validate_command_name(name: str) -> None:
    """Reject command names containing glob metacharacters or path separators.

    Only ASCII alphanumeric characters, hyphens, and underscores are allowed.
    The name must start with an alphanumeric character.

    Args:
        name: Command name to validate.

    Raises:
        click.BadParameter: If the name contains unsafe characters.
    """
    if not _RE_COMMAND_NAME.match(name):
        msg = (
            f"Invalid command name '{name}'. "
            "Only letters, digits, hyphens, and underscores are allowed "
            "(must start with a letter or digit)."
        )
        raise click.BadParameter(msg, param_hint="'COMMAND_NAME'")


def _run_custom(command_name: str, args: tuple[str, ...], config: Config) -> None:
    """Validate the name and run the named custom pipeline.

    Args:
        command_name: User-supplied pipeline name.
        args: Arguments to forward to the pipeline's stages.
        config: Loaded layered configuration (with profile and overrides applied).

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined for the
            name, or the pipeline's exit code on failure.
    """
    validate_command_name(command_name)
    cwd = Path.cwd()

    exit_code = run_command(
        cwd,
        args,
        command_prefix=command_name,
        package_name=config.get("bmk.package_name", default=""),
        show_warnings=config.get("bmk.show_warnings", default=True),
    )

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("custom", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@argument("command_name")
@argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def cli_custom(ctx: click.Context, command_name: str, args: tuple[str, ...]) -> None:
    """Run a custom pipeline named COMMAND_NAME.

    The pipeline is defined declaratively under ``[tool.bmk.pipelines.<name>]``
    in pyproject.toml or in ``bmk_makescripts/stages.toml``. Extra arguments are
    forwarded to the pipeline's stages.

    Example:
        bmk custom deploy              # Run the 'deploy' pipeline
        bmk custom deploy --verbose    # Forward --verbose to the stages
    """
    cli_ctx = get_cli_context(ctx)
    with lib_log_rich.runtime.bind(job_id="cli-custom", extra={"command": "custom", "prefix": command_name}):
        logger.info("Executing custom command '%s'", command_name)
        _run_custom(command_name, args, cli_ctx.config)


__all__ = ["cli_custom"]
