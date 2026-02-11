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
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

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


def check_makefile_update() -> bool:
    """Check if the project Makefile is outdated and prompt to update.

    Returns True if the Makefile was updated (caller should exit),
    False if no update needed or user declined.

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

    if not click.confirm(
        f"Makefile is outdated ({local_ver} \u2192 {bundled_ver}). Update?",
        default=False,
    ):
        return False

    shutil.copy2(_BUNDLED_MAKEFILE, target)
    click.echo(f"Makefile updated to {bundled_ver}")
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
        if not _BUNDLED_MAKEFILE.is_file():
            click.echo(f"Error: Bundled Makefile not found at {_BUNDLED_MAKEFILE}", err=True)
            raise SystemExit(ExitCode.FILE_NOT_FOUND)

        target = Path.cwd() / "Makefile"

        if target.exists():
            first_line = target.read_text(encoding="utf-8").split("\n", maxsplit=1)[0]
            if not first_line.startswith(_BMK_MAKEFILE_SENTINEL):
                click.echo("Makefile exists but is not managed by bmk — skipping", err=True)
                raise SystemExit(ExitCode.GENERAL_ERROR)
            logger.info("Updating existing bmk Makefile")
            click.echo("Updating existing bmk Makefile")
        else:
            logger.info("Installing bmk Makefile")
            click.echo("Installing bmk Makefile")

        shutil.copy2(_BUNDLED_MAKEFILE, target)


__all__ = ["check_makefile_update", "cli_install"]
