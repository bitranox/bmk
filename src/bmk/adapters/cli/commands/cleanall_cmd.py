"""CLI command for a full clean that also purges every virtual environment.

``clean-all`` removes everything ``clean`` removes PLUS every ``.venv*`` - the whole version
matrix and the default venv. Plain ``clean`` deliberately keeps the venv (deleting it forces a
full re-resolve), so this is the explicit "remove it all".

Contents:
    * :func:`cli_clean_all` - Clean-all command.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ._shared import run_command

logger = logging.getLogger(__name__)


def _run_clean_all() -> None:
    exit_code = run_command(Path.cwd(), (), command_prefix="clean_all")
    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("clean-all", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_clean_all() -> None:
    """Clean build artifacts and caches AND remove every virtual environment (`.venv*`).

    Everything ``clean`` removes, plus ``.venv``, ``.venv-bmk``, and every ``.venv-<minor>``
    the matrix created. The next ``make`` rebuilds whatever it needs. Use this to reclaim disk
    or force a from-scratch re-resolve; plain ``clean`` keeps the venvs on purpose.

    Example:
        bmk clean-all
    """
    with lib_log_rich.runtime.bind(job_id="cli-clean-all"):
        logger.info("Cleaning artifacts and purging all venvs (clean-all)")
        _run_clean_all()


__all__ = ["cli_clean_all"]
