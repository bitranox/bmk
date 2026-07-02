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

from . import tools
from .actions import HelperAction, PipelineAction, ToolAction
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


# The test pipeline: sequential apply-fixes stages, then a wide parallel batch of
# checks at order 40, then shellcheck. Mirrors the test_NN_*.sh stage numbering.
_TEST_PIPELINE: tuple[Stage, ...] = (
    Stage("update_deps", 10, PipelineAction("deps_update")),
    Stage("ruff_format_apply", 20, ToolAction(tools.ruff_format_apply_argv)),
    Stage("ruff_fix_apply", 30, ToolAction(tools.ruff_fix_apply_argv)),
    Stage("bandit", 40, ToolAction(tools.bandit_argv)),
    Stage("lint_imports", 40, ToolAction(tools.lint_imports_argv)),
    Stage("pip_audit", 40, ToolAction(tools.pip_audit_argv)),
    Stage("pyright", 40, ToolAction(tools.pyright_argv)),
    Stage("pytest", 40, ToolAction(tools.pytest_cov_argv)),
    Stage("ruff_format_check", 40, ToolAction(tools.ruff_format_check_argv)),
    Stage("ruff_lint", 40, ToolAction(tools.ruff_lint_argv)),
    Stage("psscriptanalyzer", 40, ToolAction(tools.psscriptanalyzer_argv)),
    Stage("shellcheck", 60, ToolAction(tools.shellcheck_argv)),
)

_COV_PIPELINE: tuple[Stage, ...] = (
    Stage("coverage", 10, ToolAction(tools.coverage_run_argv)),
    Stage("clean", 20, HelperAction(clean_action)),
)

_TEST_INTEGRATION_PIPELINE: tuple[Stage, ...] = (
    Stage("pytest_integration", 10, ToolAction(tools.integration_pytest_argv)),
)


PIPELINES: dict[str, tuple[Stage, ...]] = {
    "clean": (Stage("clean", 10, HelperAction(clean_action)),),
    "deps": (Stage("deps", 10, HelperAction(deps_action)),),
    "deps_update": (Stage("deps_update", 10, HelperAction(deps_update_action)),),
    "test": _TEST_PIPELINE,
    "cov": _COV_PIPELINE,
    "test_integration": _TEST_INTEGRATION_PIPELINE,
}

# Prefixes whose Python pipeline is ready. During migration the CLI runs these
# in-process only when opted in (BMK_RUNNER=python); every other prefix still
# uses the legacy shell stagerunner, and all shell scripts stay intact.
PORTED_PREFIXES: frozenset[str] = frozenset(PIPELINES)
