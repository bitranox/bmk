"""CLI command for running custom stagerunner commands.

Provides ``custom`` command that executes user-defined staged scripts
from the override directory. The first argument is the command prefix
used to match scripts (e.g., ``deploy`` matches ``deploy_01_*.sh``).

Unlike built-in commands (test, clean, build), custom commands have
no bundled scripts — they exist only in the override directory.

Environment variables set for scripts:
    * ``BMK_PROJECT_DIR`` - Path to the current working directory
    * ``BMK_COMMAND_PREFIX`` - The user-supplied command name
    * ``BMK_OVERRIDE_DIR`` - The override directory (forced to the resolved dir)
    * ``BMK_PACKAGE_NAME`` - Package name override (from config, if set)

Contents:
    * :func:`cli_custom` - Run a custom command from the override directory.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

import lib_log_rich.runtime
import rich_click as click

from bmk.adapters.config.loader import get_config

from ..constants import PASSTHROUGH_CONTEXT_SETTINGS
from ..exit_codes import ExitCode
from .test_cmd import get_script_name, normalize_returncode

_RE_COMMAND_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

logger = logging.getLogger(__name__)


def resolve_override_dir(cwd: Path, bmk_config: dict[str, str]) -> Path:
    """Read ``bmk.override_dir`` from config dict; default to ``cwd/makescripts``.

    Args:
        cwd: Current working directory used as fallback base.
        bmk_config: The ``[bmk]`` config section dict.

    Returns:
        Resolved override directory path.
    """
    override_dir = bmk_config.get("override_dir", "")
    if override_dir:
        resolved = Path(override_dir)
        try:
            resolved.resolve().relative_to(cwd.resolve())
        except ValueError:
            logger.warning("Override directory '%s' is outside project tree '%s'", resolved, cwd)
        return resolved
    return cwd / "makescripts"


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


def find_custom_scripts(override_dir: Path, command_name: str) -> list[Path]:
    """Glob for ``{name}_[0-9]*_*.sh`` in the override directory.

    Args:
        override_dir: Directory to search for scripts.
        command_name: Command prefix to match against script filenames.

    Returns:
        Sorted list of matching script paths.
    """
    if not override_dir.is_dir():
        return []
    pattern = f"{command_name}_[0-9]*_*.sh"
    return sorted(override_dir.glob(pattern))


def execute_custom_script(
    script_path: Path,
    cwd: Path,
    extra_args: tuple[str, ...],
    *,
    command_prefix: str,
    override_dir: Path,
    package_name: str = "",
    show_warnings: bool = True,
) -> int:
    """Execute stagerunner with forced ``BMK_OVERRIDE_DIR``.

    Pure function: receives all configuration values as parameters instead
    of reaching for global state. Callers are responsible for loading config.

    Args:
        script_path: Path to the stagerunner script.
        cwd: Current working directory (set as BMK_PROJECT_DIR env var).
        extra_args: Additional arguments to pass to the script.
        command_prefix: Command prefix for staged scripts.
        override_dir: Override directory forced into the environment.
        package_name: Package name override (set as BMK_PACKAGE_NAME if non-empty).
        show_warnings: Show warnings from passing parallel jobs (set as BMK_SHOW_WARNINGS env var).

    Returns:
        Exit code from the script execution.
    """
    env = os.environ.copy()
    env["BMK_PROJECT_DIR"] = str(cwd)
    env["BMK_COMMAND_PREFIX"] = command_prefix
    env["BMK_OVERRIDE_DIR"] = str(override_dir)
    env["BMK_SHOW_WARNINGS"] = "1" if show_warnings else "0"

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


def _run_custom(command_name: str, args: tuple[str, ...]) -> None:
    """Resolve override dir, check for scripts, invoke stagerunner.

    Args:
        command_name: User-supplied command prefix.
        args: Arguments to forward to the scripts.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if override dir missing or
            no scripts match, or the script's exit code on failure.
    """
    validate_command_name(command_name)
    cwd = Path.cwd()
    bmk_config = get_config().as_dict().get("bmk", {})
    override_dir = resolve_override_dir(cwd, bmk_config)

    if not override_dir.is_dir():
        click.echo(
            f"Error: Override directory '{override_dir}' does not exist",
            err=True,
        )
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    matching_scripts = find_custom_scripts(override_dir, command_name)
    if not matching_scripts:
        click.echo(
            f'custom command "{command_name}" not found in directory {override_dir}',
            err=True,
        )
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    script_name = get_script_name()
    # Resolve stagerunner from bundled location
    bundled_script = Path(__file__).parent.parent.parent.parent / "makescripts" / script_name
    if not bundled_script.is_file():
        click.echo(f"Error: Stagerunner '{script_name}' not found", err=True)
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    logger.debug(
        "Executing custom command '%s' via stagerunner: %s (override_dir=%s)",
        command_name,
        bundled_script,
        override_dir,
    )
    exit_code = execute_custom_script(
        bundled_script,
        cwd,
        args,
        command_prefix=command_name,
        override_dir=override_dir,
        package_name=bmk_config.get("package_name", ""),
        show_warnings=bmk_config.get("show_warnings", True),
    )

    if exit_code != 0:
        raise SystemExit(exit_code)


@click.command("custom", context_settings=PASSTHROUGH_CONTEXT_SETTINGS)
@click.argument("command_name")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli_custom(command_name: str, args: tuple[str, ...]) -> None:
    """Run a custom command from the override directory.

    Executes user-defined staged scripts matching COMMAND_NAME from the
    override directory. The override directory is read from
    ``bmk.override_dir`` config or defaults to ``<cwd>/makescripts``.

    Scripts must follow the naming convention ``<name>_<NNN>_<desc>.sh``
    (e.g., ``deploy_01_prepare.sh``, ``deploy_02_upload.sh``).

    Example:
        bmk custom deploy              # Run deploy_*.sh scripts
        bmk custom deploy --verbose    # Forward --verbose to scripts
    """
    with lib_log_rich.runtime.bind(job_id="cli-custom", extra={"command": "custom", "prefix": command_name}):
        logger.info("Executing custom command '%s'", command_name)
        _run_custom(command_name, args)


__all__ = ["cli_custom"]
