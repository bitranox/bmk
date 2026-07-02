"""Shared helper for CLI command modules.

Runs a command's staged pipeline via the in-process Python stage runner
(:mod:`bmk.adapters.stagerunner`). The prefix's stages come from the built-in
registry, a project ``[tool.bmk.pipelines]`` overlay (in pyproject.toml or
override.
"""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from bmk.domain.enums import ToolOutputFormat
from bmk.domain.stages import normalize_returncode

from ..exit_codes import ExitCode


def run_command(
    cwd: Path,
    extra_args: tuple[str, ...],
    *,
    command_prefix: str,
    output_format: ToolOutputFormat | None = None,
    show_warnings: bool = True,
    package_name: str = "",
) -> int:
    """Resolve and run the pipeline for ``command_prefix`` via the stage runner.

    Args:
        cwd: Project directory (the pipeline runs here).
        extra_args: Arguments forwarded to the pipeline's stages.
        command_prefix: Pipeline to run (e.g. ``"test"``, ``"clean"``).
        output_format: TEXT (verbose) or JSON (machine-readable, quiet). When
            ``None``, resolved from ``BMK_OUTPUT_FORMAT`` (default JSON).
        show_warnings: Show warnings from passing parallel stages.
        package_name: Import package name override (else derived from pyproject).

    Returns:
        Exit code from the pipeline.

    Raises:
        SystemExit: With FILE_NOT_FOUND (2) if no pipeline is defined for the prefix.
    """
    from bmk.adapters.stagerunner.context import build_context
    from bmk.adapters.stagerunner.engine import run_pipeline
    from bmk.adapters.stagerunner.registry import resolve_python_pipeline

    if output_format is None:
        output_format = resolve_output_format(human=False)

    stages = resolve_python_pipeline(cwd, command_prefix)
    if stages is None:
        click.echo(f"Error: no pipeline defined for '{command_prefix}'", err=True)
        click.echo(
            "Define one under [tool.bmk.pipelines] in pyproject.toml or in bmk_makescripts/stages.toml.",
            err=True,
        )
        raise SystemExit(ExitCode.FILE_NOT_FOUND)

    ctx = build_context(
        cwd,
        extra_args,
        command_prefix=command_prefix,
        output_format=output_format,
        show_warnings=show_warnings,
        package_name=package_name,
    )
    return run_pipeline(stages, ctx)


def resolve_output_format(*, human: bool) -> ToolOutputFormat:
    """Parse the tool output format at the CLI boundary.

    ``--human`` forces TEXT; otherwise ``BMK_OUTPUT_FORMAT=text`` selects TEXT and
    anything else (including unset) defaults to JSON.
    """
    import os

    if human or os.environ.get("BMK_OUTPUT_FORMAT") == ToolOutputFormat.TEXT.value:
        return ToolOutputFormat.TEXT
    return ToolOutputFormat.JSON


__all__ = ["normalize_returncode", "resolve_output_format", "run_command"]
