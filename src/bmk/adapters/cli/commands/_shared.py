"""Shared helper for CLI command modules.

Runs a command's staged pipeline via the in-process Python stage runner
(:mod:`bmk.adapters.stagerunner`). The prefix's stages come from the built-in
registry, which a project ``[tool.bmk.pipelines]`` overlay (in pyproject.toml or
``bmk_makescripts/stages.toml``) may override.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import rich_click as click

from bmk.adapters.stagerunner.output_format_env import read_tool_output_format
from bmk.domain.enums import ToolOutputFormat, VenvProvisioning
from bmk.domain.stages import normalize_returncode

from .. import safe_console
from ..context import CLIContext
from ..exit_codes import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

    from bmk.adapters.stagerunner.settings import BmkSettings

# Pipelines whose stages read or write the project's Python environment, and so
# need it provisioned and synced first. Everything else (clean, bump, commit,
# release, run) must not pay for building a venv it never looks at.
VENV_PIPELINES: frozenset[str] = frozenset({"test", "cov", "test_integration", "push", "deps", "deps_update", "bld"})


def run_command(
    cwd: Path,
    extra_args: tuple[str, ...],
    *,
    command_prefix: str,
    output_format: ToolOutputFormat | None = None,
) -> int:
    """Resolve and run the pipeline for ``command_prefix`` via the stage runner.

    Args:
        cwd: Project directory (the pipeline runs here).
        extra_args: Arguments forwarded to the pipeline's stages.
        command_prefix: Pipeline to run (e.g. ``"test"``, ``"clean"``).
        output_format: TEXT (verbose) or JSON (machine-readable, quiet). When
            ``None``, resolved from ``BMK_OUTPUT_FORMAT`` (default JSON).

    Returns:
        Exit code from the pipeline.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined for the prefix, or
            CONFIG_ERROR (78) when the ``[bmk]`` section holds a value bmk refuses.
    """
    # Deferred: the stagerunner subsystem (pipeline engine, registry, venv provisioning)
    # is expensive to import and only every command that actually RUNS a pipeline needs
    # it - `bmk --version` / `bmk info` must not pay for it.
    from bmk.adapters.stagerunner.context import build_context  # noqa: PLC0415
    from bmk.adapters.stagerunner.engine import run_pipeline  # noqa: PLC0415
    from bmk.adapters.stagerunner.registry import resolve_python_pipeline  # noqa: PLC0415

    if output_format is None:
        output_format = resolve_output_format(human=False)
    # Read here, not by each command: a key that only some commands passed on silently fell back
    # to its default in all the others.
    settings = _configured_bmk_settings()

    stages = resolve_python_pipeline(cwd, command_prefix)
    if stages is None:
        safe_console.echo(f"Error: no pipeline defined for '{command_prefix}'", err=True)
        safe_console.echo(
            "Define one under [tool.bmk.pipelines] in pyproject.toml or in bmk_makescripts/stages.toml.",
            err=True,
        )
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    # Provision before build_context: it pins VIRTUAL_ENV / PIPAPI_PYTHON_LOCATION
    # once and StageContext is frozen, so a venv created later could not repair the
    # pins for the stages that follow.
    provisioning = _provision_venv(cwd, command_prefix, quiet=output_format is not ToolOutputFormat.TEXT)

    ctx = build_context(
        cwd,
        extra_args,
        command_prefix=command_prefix,
        output_format=output_format,
        show_warnings=settings.show_warnings,
        package_name=settings.package_name,
        supply_chain=settings.supply_chain,
        venv_provisioning=provisioning,
    )
    return run_pipeline(stages, ctx)


def _provision_venv(cwd: Path, command_prefix: str, *, quiet: bool) -> VenvProvisioning:
    """Provision the project venv for a pipeline that uses it, and say what happened.

    The answer travels to the stages in the StageContext: ``deps_update`` re-syncs the venv, and must
    not repeat a sync this run already saw fail when its re-lock changed nothing.
    """
    from bmk.adapters.stagerunner.venv import ensure_project_venv, venv_sync_disabled  # noqa: PLC0415 - see run_command

    if command_prefix not in VENV_PIPELINES:
        return VenvProvisioning.NOT_ATTEMPTED
    if venv_sync_disabled(os.environ):
        return VenvProvisioning.SKIPPED
    venv = ensure_project_venv(cwd, os.environ, quiet=quiet)
    return VenvProvisioning.FAILED if venv is None else VenvProvisioning.PROVISIONED


def _configured_bmk_settings() -> BmkSettings:
    """The ``[bmk]`` section the running CLI loaded, validated; defaults outside the CLI.

    A value bmk must not use stops the command with CONFIG_ERROR (78) and one stderr line per
    problem, rather than running under a setting nobody chose.
    """
    from bmk.adapters.stagerunner.settings import (  # noqa: PLC0415 - see run_command
        BmkSettings,
        BmkSettingsError,
        parse_bmk_settings,
    )

    ctx = click.get_current_context(silent=True)
    obj = ctx.find_root().obj if ctx is not None else None
    if not isinstance(obj, CLIContext):
        return BmkSettings()
    try:
        return parse_bmk_settings(obj.config.get("bmk", default={}))
    except BmkSettingsError as exc:
        for problem in exc.problems:
            safe_console.echo(f"Error: {problem}", err=True)
        raise SystemExit(ExitCode.CONFIG_ERROR) from exc


def resolve_output_format(*, human: bool) -> ToolOutputFormat:
    """Parse the tool output format at the CLI boundary.

    ``--human`` forces TEXT; otherwise ``BMK_OUTPUT_FORMAT=text`` (any case) selects TEXT and
    anything else (including unset) defaults to JSON, with a stderr warning for a value that is
    neither unset, empty, ``text`` nor ``json``.
    """
    if human:
        return ToolOutputFormat.TEXT
    return read_tool_output_format()


__all__ = ["normalize_returncode", "resolve_output_format", "run_command"]
