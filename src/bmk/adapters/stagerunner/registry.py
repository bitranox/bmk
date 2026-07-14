"""Built-in pipeline registry.

Maps a command prefix to its ordered tuple of stages. Leaf helpers live in the
``helpers`` subpackage and are called in-process (``HelperAction``) or as
subprocesses (``tools.py``); external tools run via ``ToolAction``; a pipeline can
delegate to another via ``PipelineAction`` (e.g. ``bld`` -> ``clean``).
"""

from __future__ import annotations

from pathlib import Path

from bmk.domain.enums import ToolOutputFormat

from . import git_ops, tools
from .actions import HelperAction, PipAuditAction, PipelineAction, ToolAction
from .context import resolve_audit_python
from .helpers import _clean, _dependencies
from .model import Stage, StageContext
from .overrides import load_overlay, resolve_stages
from .venv import is_venv, resolve_project_venv, venv_python


def clean_action(ctx: StageContext) -> int:
    """Remove build artifacts and caches for the project."""
    return _clean.main(
        project_dir=ctx.project_dir,
        dry_run=False,
        verbose=False,
        quiet=ctx.output_format is not ToolOutputFormat.TEXT,
    )


def _project_python(ctx: StageContext) -> str | None:
    """Interpreter ``deps update`` may install into, or None if there is none.

    Deliberately *not* ``resolve_audit_python``: that falls back to bmk's own
    interpreter when the project venv is missing, which is right for auditing
    (read-only) but would make an install write into whatever environment
    launched bmk - a shared editor venv, or a system Python. Installing has no
    safe fallback, so the absence of a project venv must yield None and skip the
    sync rather than silently retarget it.
    """
    venv = resolve_project_venv(ctx.project_dir, ctx.env)
    if not is_venv(venv):
        return None
    interpreter = venv_python(venv)
    return str(interpreter) if interpreter.exists() else None


def deps_action(ctx: StageContext) -> int:
    """Check project dependencies against PyPI."""
    return _dependencies.main(
        pyproject=ctx.project_dir / "pyproject.toml",
        quiet=ctx.output_format is not ToolOutputFormat.TEXT,
    )


def deps_update_action(ctx: StageContext) -> int:
    """Update outdated dependencies to their latest versions."""
    return _dependencies.main(
        update=True,
        pyproject=ctx.project_dir / "pyproject.toml",
        quiet=ctx.output_format is not ToolOutputFormat.TEXT,
        python=_project_python(ctx),
    )


# The test pipeline: sequential apply-fixes stages, then a wide parallel batch of
# checks at order 40, then shellcheck.
_TEST_PIPELINE: tuple[Stage, ...] = (
    Stage("update_deps", 10, PipelineAction("deps_update")),
    Stage("ruff_format_apply", 20, ToolAction(tools.ruff_format_apply_argv)),
    Stage("ruff_fix_apply", 30, ToolAction(tools.ruff_fix_apply_argv)),
    Stage("bandit", 40, ToolAction(tools.bandit_argv)),
    Stage("lint_imports", 40, ToolAction(tools.lint_imports_argv)),
    Stage("pip_audit", 40, PipAuditAction(resolve_audit_python, tools.ensure_audit_pip_argv, tools.pip_audit_argv)),
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


def _bump_pipeline(kind: str) -> tuple[Stage, ...]:
    return (
        Stage("bump", 10, ToolAction(tools.bump_argv(kind))),
        Stage("sync_initconf", 20, ToolAction(tools.sync_initconf_argv)),
    )


_COMMIT_PIPELINE: tuple[Stage, ...] = (
    Stage("sync_initconf", 5, ToolAction(tools.sync_initconf_argv)),
    Stage("commit", 10, HelperAction(git_ops.commit), interactive=True),
)

_BLD_PIPELINE: tuple[Stage, ...] = (
    Stage("clean", 10, PipelineAction("clean")),
    Stage("build", 20, ToolAction(tools.python_build_argv)),
)

# push composes other pipelines (build + test run in parallel at order 20).
# `build` runs a direct `python -m build` here, NOT the `bld` pipeline: `bld` cleans
# first, and that clean - running in the same order-20 batch as `test` - rmtree's the
# project `.venv` and the caches (.pytest_cache/.ruff_cache/.pyright/.coverage/...) that
# the concurrent `test` tools read and write, while they are pinned to `.venv` via
# VIRTUAL_ENV / PIPAPI_PYTHON_LOCATION (pip-audit crashed on the vanished interpreter;
# pyright/cache deletions were latent flakiness). So push does NOT clean before `test`;
# the sole `clean` runs at order 30, AFTER `test`, leaving every pin valid throughout.
_PUSH_PIPELINE: tuple[Stage, ...] = (
    Stage("update_deps", 10, PipelineAction("deps")),
    Stage("build", 20, ToolAction(tools.python_build_argv)),
    Stage("test", 20, PipelineAction("test")),
    Stage("clean", 30, PipelineAction("clean")),
    Stage("commit", 40, PipelineAction("commit")),
    Stage("push", 50, ToolAction(git_ops.push_argv)),
)


PIPELINES: dict[str, tuple[Stage, ...]] = {
    "clean": (Stage("clean", 10, HelperAction(clean_action)),),
    "deps": (Stage("deps", 10, HelperAction(deps_action)),),
    "deps_update": (Stage("deps_update", 10, HelperAction(deps_update_action)),),
    "test": _TEST_PIPELINE,
    "cov": _COV_PIPELINE,
    "test_integration": _TEST_INTEGRATION_PIPELINE,
    "bump_major": _bump_pipeline("major"),
    "bump_minor": _bump_pipeline("minor"),
    "bump_patch": _bump_pipeline("patch"),
    "commit": _COMMIT_PIPELINE,
    "bld": _BLD_PIPELINE,
    "push": _PUSH_PIPELINE,
    "rel": (Stage("release", 10, ToolAction(tools.release_argv)),),
    "run": (Stage("run", 10, ToolAction(tools.run_project_argv)),),
}

# All built-in pipeline prefixes (kept for introspection and tests).
PORTED_PREFIXES: frozenset[str] = frozenset(PIPELINES)


def resolve_python_pipeline(cwd: Path, prefix: str) -> list[Stage] | None:
    """Resolve the stages to run for ``prefix``, or ``None`` if it is unknown.

    A prefix is known when it is a built-in pipeline or has a TOML overlay (the
    latter also covers custom prefixes). Returns the resolved stages (built-in
    plus any overlay), or ``None`` when nothing defines the prefix.
    """
    if prefix not in PIPELINES and load_overlay(cwd, prefix) is None:
        return None
    return resolve_stages(cwd, prefix, PIPELINES.get(prefix, ()))
