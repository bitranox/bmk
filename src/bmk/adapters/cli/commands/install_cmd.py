"""CLI command for installing the bundled bmk Makefile.

Copies the bundled ``Makefile`` from the package into the current working
directory. Uses a sentinel comment (``# BMK MAKEFILE``) on the first line
to distinguish managed Makefiles (safe to overwrite) from custom ones
(left untouched).

Contents:
    * :func:`cli_install` - Install or update the bmk Makefile.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from bmk.adapters.stagerunner.output_format_env import read_tool_output_format
from bmk.domain.enums import ToolOutputFormat

from .. import safe_console
from ..constants import CLICK_CONTEXT_SETTINGS
from ..exit_codes import ExitCode

logger = logging.getLogger(__name__)

_BMK_MAKEFILE_SENTINEL = "# BMK MAKEFILE"

_BUNDLED_MAKEFILE = Path(__file__).resolve().parent.parent.parent.parent / "makefile" / "Makefile"


def _extract_version(first_line: str) -> str | None:
    """Extract version from a sentinel line like '# BMK MAKEFILE 1.0.0'.

    Returns the version string ('1.0.0') or None if not a managed Makefile.
    """
    if not first_line.startswith(_BMK_MAKEFILE_SENTINEL):
        return None
    return first_line[len(_BMK_MAKEFILE_SENTINEL) :].strip() or None


def _stdin_is_a_terminal() -> bool:
    """Whether a person can answer a prompt on stdin (``sys.stdin`` is None under pythonw)."""
    return sys.stdin is not None and sys.stdin.isatty()


def check_makefile_update() -> bool:
    """Check if the project Makefile is outdated and prompt to update.

    Returns True if the Makefile was updated (caller should exit),
    False if no update needed or user declined.

    When ``BMK_OUTPUT_FORMAT`` is not ``text`` (i.e. JSON mode), the update
    is applied automatically without prompting.

    In text mode the question is asked only when stdin is a terminal. Anything else - an
    agent's pipe, a CI step, ``yes y |`` - is not a person answering, and an open pipe nobody
    writes to would block the read forever. The update is then declined, as the prompt's own
    default would, and stderr names ``bmk install`` as the way to apply it.

    Silently returns False on any I/O error or non-interactive Abort.
    """
    target = Path.cwd() / "Makefile"
    if not target.is_file() or not _BUNDLED_MAKEFILE.is_file():
        return False

    local_first = target.read_text(encoding="utf-8").split("\n", maxsplit=1)[0]
    local_ver = _extract_version(local_first)
    if local_ver is None:
        return False

    bundled_first = _BUNDLED_MAKEFILE.read_text(encoding="utf-8").split("\n", maxsplit=1)[0]
    bundled_ver = _extract_version(bundled_first)
    if bundled_ver is None or local_ver == bundled_ver:
        return False

    auto_accept = read_tool_output_format() is not ToolOutputFormat.TEXT

    if not auto_accept and not _stdin_is_a_terminal():
        safe_console.echo(
            f"Makefile is outdated ({local_ver} \u2192 {bundled_ver}); run 'bmk install' to update it.",
            err=True,
        )
        return False

    if not auto_accept and not click.confirm(
        f"Makefile is outdated ({local_ver} \u2192 {bundled_ver}). Update?",
        default=False,
    ):
        return False

    shutil.copy2(_BUNDLED_MAKEFILE, target)
    if not auto_accept:
        safe_console.echo(f"Makefile updated to {bundled_ver}")
    return True


@click.command("install", context_settings=CLICK_CONTEXT_SETTINGS)
def cli_install() -> None:
    """Install or update the bmk Makefile in the current directory.

    Copies the bundled Makefile into the working directory. If a Makefile
    already exists, it is only overwritten when its first line starts with
    ``# BMK MAKEFILE`` (the managed-file sentinel). Custom Makefiles are
    never touched.

    Example:
        bmk install          # fresh install or update
    """
    with lib_log_rich.runtime.bind(job_id="cli-install", extra={"command": "install"}):
        makefile_error: SystemExit | None = None

        if not _BUNDLED_MAKEFILE.is_file():
            safe_console.echo(f"Error: Bundled Makefile not found at {_BUNDLED_MAKEFILE}", err=True)
            makefile_error = SystemExit(ExitCode.FILE_NOT_FOUND)
        else:
            target = Path.cwd() / "Makefile"

            if target.exists():
                first_line = target.read_text(encoding="utf-8").split("\n", maxsplit=1)[0]
                if not first_line.startswith(_BMK_MAKEFILE_SENTINEL):
                    safe_console.echo("Makefile exists but is not managed by bmk - skipping", err=True)
                    makefile_error = SystemExit(ExitCode.GENERAL_ERROR)
                else:
                    logger.info("Updating existing bmk Makefile")
                    safe_console.echo("Updating existing bmk Makefile")
                    shutil.copy2(_BUNDLED_MAKEFILE, target)
            else:
                logger.info("Installing bmk Makefile")
                safe_console.echo("Installing bmk Makefile")
                shutil.copy2(_BUNDLED_MAKEFILE, target)

        # Deferred: keep `bmk install` (and thus command registration) from paying
        # for the prerequisites-check module unless this command actually runs.
        from ._prerequisites import check_prerequisites, format_prerequisites_report  # noqa: PLC0415

        results = check_prerequisites()
        report = format_prerequisites_report(results)
        safe_console.echo("")
        safe_console.echo(report)

        if makefile_error is not None:
            raise makefile_error


__all__ = ["check_makefile_update", "cli_install"]
