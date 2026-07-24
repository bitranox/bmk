"""CLI command for installing missing external tools.

Provides ``bmk ensure``, which detects the external tools bmk needs on the host
(git, pwsh, shellcheck, shfmt, bashate, PSScriptAnalyzer; winget on Windows) and
installs any that are missing, per-OS and best-effort.

Contents:
    * :func:`cli_ensure` - Ensure external tools are installed.
"""

from __future__ import annotations

import logging

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import option

logger = logging.getLogger(__name__)


@click.command("ensure", context_settings=CLICK_CONTEXT_SETTINGS)
@option("--dry-run", is_flag=True, default=False, help="Show what would be installed without installing.")
@option("--strict", is_flag=True, default=False, help="Exit non-zero if any tool is still missing afterwards.")
def cli_ensure(*, dry_run: bool, strict: bool) -> None:
    """Install missing external tools (git, pwsh, shellcheck, ...) for this OS.

    Detects the tools bmk relies on and installs any that are absent, best-effort:
    the linters via pip, git/pwsh via the system package manager (apt/brew/winget),
    PSScriptAnalyzer via ``Install-Module``. Tools with no installer on this
    platform (e.g. pwsh on Linux, winget itself) are reported with a hint.

    Example:
        bmk ensure             # install what is missing
        bmk ensure --dry-run   # preview the install commands
    """
    with lib_log_rich.runtime.bind(job_id="cli-ensure", extra={"command": "ensure"}):
        logger.info("Ensuring external tools are installed")
        # Deferred: `_ensure` pulls in per-OS installer plumbing that only this
        # command needs; command registration must not pay for it.
        from ._ensure import run_ensure  # noqa: PLC0415

        exit_code = run_ensure(dry_run=dry_run, strict=strict)
        if exit_code != 0:
            raise SystemExit(exit_code)


__all__ = ["cli_ensure"]
