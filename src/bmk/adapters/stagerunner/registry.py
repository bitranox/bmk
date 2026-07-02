"""Built-in pipeline registry.

Maps a command prefix to its ordered tuple of stages. Grows one pipeline per
migration phase.

During migration the stage helpers stay in ``bmk.makescripts`` and are called
in-process here; the legacy shell scripts remain intact so unported pipelines
(and cross-pipeline delegators such as ``bld`` -> ``clean``) keep working. The
helpers move into this package only in the final phase, when every shell script
retires at once.
"""

from __future__ import annotations

from bmk.makescripts import _clean, _dependencies

from .actions import HelperAction
from .model import Stage, StageContext


def clean_action(ctx: StageContext) -> int:
    """Remove build artifacts and caches for the project."""
    return _clean.main(project_dir=ctx.project_dir, dry_run=False, verbose=False)


def deps_action(ctx: StageContext) -> int:
    """Check project dependencies against PyPI."""
    return _dependencies.main(
        pyproject=ctx.project_dir / "pyproject.toml",
        quiet=ctx.output_format != "text",
    )


def deps_update_action(ctx: StageContext) -> int:
    """Update outdated dependencies to their latest versions."""
    return _dependencies.main(
        update=True,
        pyproject=ctx.project_dir / "pyproject.toml",
        quiet=ctx.output_format != "text",
    )


PIPELINES: dict[str, tuple[Stage, ...]] = {
    "clean": (Stage("clean", 10, HelperAction(clean_action)),),
    "deps": (Stage("deps", 10, HelperAction(deps_action)),),
    "deps_update": (Stage("deps_update", 10, HelperAction(deps_update_action)),),
}

# Prefixes whose Python pipeline is ready. During migration the CLI runs these
# in-process only when opted in (BMK_RUNNER=python); every other prefix still
# uses the legacy shell stagerunner, and all shell scripts stay intact.
PORTED_PREFIXES: frozenset[str] = frozenset(PIPELINES)
