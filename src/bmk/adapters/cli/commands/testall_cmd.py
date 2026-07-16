"""CLI command for the per-version test matrix.

``test-all`` runs the test suite and type-check on EVERY Python version the project's
classifiers declare, in parallel, so a break that only shows on an older Python is caught
locally instead of waiting for CI. Plain ``test`` stays fast (newest version only).

Contents:
    * :func:`cli_test_all` - Test-all command.
"""

from __future__ import annotations

import logging
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import option
from ._shared import resolve_output_format, run_command

logger = logging.getLogger(__name__)


def _run_test_all(*, human: bool) -> None:
    exit_code = run_command(
        Path.cwd(),
        (),
        command_prefix="test_all",
        output_format=resolve_output_format(human=human),
    )
    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("test-all", context_settings=CLICK_CONTEXT_SETTINGS)
@option("--human", is_flag=True, default=False, help="Use human-readable text output instead of JSON.")
def cli_test_all(*, human: bool) -> None:
    """Run pytest + pyright on every Python version the project declares.

    Provisions one ``.venv-<minor>`` per ``Programming Language :: Python :: X.Y`` classifier
    (each on its latest patch), runs the suite and type-check in each in parallel, and fails
    if any version fails. With no such classifier, it tests the default interpreter once and
    warns. Reproduces CI's version matrix locally before you push.

    Example:
        bmk test-all
        bmk test-all --human
    """
    with lib_log_rich.runtime.bind(job_id="cli-test-all"):
        logger.info("Running the version matrix (test-all)")
        _run_test_all(human=human)


__all__ = ["cli_test_all"]
