"""Shared helpers for CLI command modules.

Internal module (underscore prefix) providing common patterns used across
multiple command implementations.

Contents:
    * :func:`normalize_returncode` - Convert signal codes to POSIX 128+N.
    * :func:`get_script_name` - Return OS-appropriate stagerunner name.
    * :func:`resolve_script_path` - Find script in local override or bundled location.
    * :func:`execute_script` - Execute script with BMK environment variables.
    * :func:`require_script_path` - Resolve script path or exit with FILE_NOT_FOUND.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import rich_click as click

from ..exit_codes import ExitCode


def normalize_returncode(code: int) -> int:
    """Convert negative signal return codes to POSIX 128+N convention.

    Python's ``subprocess`` reports signal-killed processes as negative values
    (e.g., -2 for SIGINT). POSIX convention is 128+N (e.g., 130 for SIGINT).

    Args:
        code: Raw return code from subprocess.

    Returns:
        POSIX-conventional exit code.
    """
    if code < 0:
        return 128 + abs(code)
    return code


def get_script_name() -> str:
    """Return OS-appropriate script name.

    Returns:
        ``_btx_stagerunner.ps1`` on Windows, ``_btx_stagerunner.sh`` otherwise.
    """
    return "_btx_stagerunner.ps1" if sys.platform == "win32" else "_btx_stagerunner.sh"


def resolve_script_path(script_name: str, cwd: Path) -> Path | None:
    """Find script in local override or bundled location.

    Args:
        script_name: Name of the script file (e.g., ``test.sh``).
        cwd: Current working directory to check for local override.

    Returns:
        Path to the script if found, None otherwise.
    """
    local_script = cwd / "bmk_makescripts" / script_name
    if local_script.is_file():
        return local_script

    # Path from _shared.py up to bmk package: commands -> cli -> adapters -> bmk
    bundled_script = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
    if bundled_script.is_file():
        return bundled_script

    return None


def execute_script(
    script_path: Path,
    cwd: Path,
    extra_args: tuple[str, ...],
    *,
    command_prefix: str = "test",
    override_dir: str = "",
    package_name: str = "",
    show_warnings: bool = True,
) -> int:
    """Execute script with BMK environment variables.

    Pure function: receives all configuration values as parameters instead
    of reaching for global state. Callers are responsible for loading config.

    Args:
        script_path: Path to the script to execute.
        cwd: Current working directory (set as BMK_PROJECT_DIR env var).
        extra_args: Additional arguments to pass to the script.
        command_prefix: Command prefix for staged scripts (set as BMK_COMMAND_PREFIX env var).
        override_dir: Override directory path (set as BMK_OVERRIDE_DIR if non-empty).
        package_name: Package name override (set as BMK_PACKAGE_NAME if non-empty).
        show_warnings: Show warnings from passing parallel jobs (set as BMK_SHOW_WARNINGS env var).

    Returns:
        Exit code from the script execution.
    """
    env = os.environ.copy()
    env["BMK_PROJECT_DIR"] = str(cwd)
    env["BMK_COMMAND_PREFIX"] = command_prefix
    env["BMK_SHOW_WARNINGS"] = "1" if show_warnings else "0"
    env["BMK_PYTHON_CMD"] = sys.executable

    if override_dir:
        env["BMK_OVERRIDE_DIR"] = str(override_dir)
    if package_name:
        env["BMK_PACKAGE_NAME"] = str(package_name)

    if script_path.suffix == ".ps1":
        cmd = [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script_path),
            *extra_args,
        ]
    else:
        cmd = [str(script_path), *extra_args]

    result = subprocess.run(cmd, check=False, env=env)  # noqa: S603
    return normalize_returncode(result.returncode)


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


__all__ = [
    "execute_script",
    "get_script_name",
    "normalize_returncode",
    "require_script_path",
    "resolve_script_path",
]
