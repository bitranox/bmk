"""Shared helpers for CLI command modules.

Internal module (underscore prefix) providing common patterns used across
multiple command implementations.

Contents:
    * :func:`require_script_path` - Resolve script path or exit with FILE_NOT_FOUND.
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from ..exit_codes import ExitCode
from .test_cmd import resolve_script_path


def require_script_path(script_name: str, cwd: Path, command_label: str) -> Path:
    """Resolve script path or exit with FILE_NOT_FOUND.

    Combines :func:`resolve_script_path` with standardized error reporting.
    If the script is found, returns its path. Otherwise, prints the search
    locations and raises SystemExit.

    Args:
        script_name: Name of the script file (e.g., ``_btx_stagerunner.sh``).
        cwd: Current working directory to check for local override.
        command_label: Human-readable label for error messages (e.g., "Test", "Build").

    Returns:
        Path to the resolved script.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found.
    """
    script_path = resolve_script_path(script_name, cwd)
    if script_path is not None:
        return script_path

    click.echo(f"Error: {command_label} script '{script_name}' not found", err=True)
    click.echo("Searched locations:", err=True)
    click.echo(f"  - {cwd / 'bmk_makescripts' / script_name}", err=True)
    bundled = Path(__file__).parent.parent.parent / "makescripts" / script_name
    click.echo(f"  - {bundled}", err=True)
    raise SystemExit(ExitCode.FILE_NOT_FOUND)


__all__ = ["require_script_path"]
