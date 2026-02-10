"""CLI commands for running project test scripts.

Provides `test` and `t` commands that execute external shell scripts with
local override support. Scripts are searched in priority order:
1. Local override: ``<cwd>/bmk_makescripts/test.sh`` (or ``.ps1``)
2. Bundled default: ``<package>/makescripts/test.sh`` (or ``.ps1``)

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - Command prefix for staged scripts
    * ``BMK_OVERRIDE_DIR`` - Per-project override directory (from config, if set)
    * ``BMK_PACKAGE_NAME`` - Package name override (from config, if set)

Contents:
    * :func:`cli_test` - Run the project test script.
    * :func:`cli_t` - Alias for ``cli_test``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from bmk.adapters.config.loader import get_config

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS

logger = logging.getLogger(__name__)


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

    # Path from test_cmd.py up to bmk package: commands -> cli -> adapters -> bmk
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

    Returns:
        Exit code from the script execution.
    """
    env = os.environ.copy()
    env["BMK_PROJECT_DIR"] = str(cwd)
    env["BMK_COMMAND_PREFIX"] = command_prefix

    if override_dir:
        env["BMK_OVERRIDE_DIR"] = str(override_dir)
    if package_name:
        env["BMK_PACKAGE_NAME"] = str(package_name)

    if script_path.suffix == ".ps1":
        cmd = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *extra_args,
        ]
    else:
        cmd = [str(script_path), *extra_args]

    result = subprocess.run(cmd, check=False, env=env)  # noqa: S603
    return normalize_returncode(result.returncode)


def _run_test(args: tuple[str, ...]) -> None:
    """Shared implementation for test commands.

    Args:
        args: Arguments to pass through to the test script.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if script not found,
            or the script's exit code on failure.
    """
    from ._shared import require_script_path

    cwd = Path.cwd()
    script_name = get_script_name()
    script_path = require_script_path(script_name, cwd, "Test")

    bmk_config = get_config().as_dict().get("bmk", {})

    logger.debug("Executing test script: %s", script_path)
    exit_code = execute_script(
        script_path,
        cwd,
        args,
        override_dir=bmk_config.get("override_dir", ""),
        package_name=bmk_config.get("package_name", ""),
    )

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("test", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_test(args: tuple[str, ...]) -> None:
    """Run the project test script.

    Executes test.sh (Linux/macOS) or test.ps1 (Windows) with the current
    working directory as the first argument, followed by any additional
    arguments passed to this command.

    Script lookup order:
    1. <cwd>/bmk_makescripts/test.sh (local override)
    2. <package>/makescripts/test.sh (bundled default)

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_test)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "test"}):
        logger.info("Executing test command")
        _run_test(args)


@click.command("t", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_t(args: tuple[str, ...]) -> None:
    """Run the project test script (alias for 'test').

    See ``bmk test --help`` for full documentation.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli_t)
        >>> result.exit_code in (0, 2)  # 0 if script exists, 2 if not found
        True
    """
    with lib_log_rich.runtime.bind(job_id="cli-test", extra={"command": "t"}):
        logger.info("Executing test command (via alias 't')")
        _run_test(args)


__all__ = [
    "cli_t",
    "cli_test",
    "execute_script",
    "get_script_name",
    "normalize_returncode",
    "resolve_script_path",
]
