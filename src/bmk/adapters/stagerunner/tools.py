"""Argv builders for the tool stages of the test / cov / integration pipelines.

Each builder maps a StageContext to an argv list, applying the same JSON-vs-text
flags the shell stages used. Every stage runs as a subprocess (ToolAction), so
each stage's output streams to its own per-stage sink - parallel order-40 stages
never share ``sys.stdout``, sidestepping in-process capture thread-safety issues.

The three ``.py`` helper stages (coverage/pytest, shellcheck, PSScriptAnalyzer)
are invoked as subprocesses of the makescripts scripts, matching the shell.
"""

from __future__ import annotations

from pathlib import Path

import bmk

from .model import StageContext
from .project import derive_package_name, pip_audit_ignore_flags

# Locate the makescripts helper dir relative to the bmk package (which has an
# __init__.py); makescripts itself is a namespace package with no usable __file__.
_bmk_file = bmk.__file__
assert _bmk_file is not None, "bmk package must have a __file__"
_MAKESCRIPTS_DIR = Path(_bmk_file).parent / "makescripts"


def _is_json(ctx: StageContext) -> bool:
    return ctx.output_format == "json"


def _helper(name: str) -> str:
    return str(_MAKESCRIPTS_DIR / name)


# --- ruff -------------------------------------------------------------------


def ruff_format_apply_argv(_ctx: StageContext) -> list[str]:
    return ["ruff", "format", "."]


def ruff_fix_apply_argv(_ctx: StageContext) -> list[str]:
    return ["ruff", "check", "--fix", "."]


def ruff_format_check_argv(_ctx: StageContext) -> list[str]:
    return ["ruff", "format", "--check", "."]


def ruff_lint_argv(ctx: StageContext) -> list[str]:
    argv = ["ruff", "check"]
    if _is_json(ctx):
        argv += ["--output-format", "json"]
    return [*argv, "."]


# --- other external tools ---------------------------------------------------


def bandit_argv(ctx: StageContext) -> list[str]:
    package = ctx.package_name or derive_package_name(ctx.project_dir / "pyproject.toml") or ""
    fmt = ["-f", "json"] if _is_json(ctx) else ["-q"]
    return ["bandit", "-r", "-c", "pyproject.toml", *fmt, f"src/{package}"]


def lint_imports_argv(_ctx: StageContext) -> list[str]:
    return ["lint-imports"]


def pip_audit_argv(ctx: StageContext) -> list[str]:
    ignores = pip_audit_ignore_flags(ctx.project_dir / "pyproject.toml")
    fmt = ["-f", "json"] if _is_json(ctx) else []
    return ["pip-audit", *ignores, *fmt]


def pyright_argv(ctx: StageContext) -> list[str]:
    return ["pyright", "--outputjson"] if _is_json(ctx) else ["pyright"]


# --- makescripts .py helper subprocesses ------------------------------------


def pytest_cov_argv(ctx: StageContext) -> list[str]:
    argv = [ctx.python_cmd, _helper("_coverage.py"), "--run", "--project-dir", str(ctx.project_dir)]
    if _is_json(ctx):
        argv += ["--output-format", "json"]
    return argv


def coverage_run_argv(ctx: StageContext) -> list[str]:
    return [ctx.python_cmd, _helper("_coverage.py"), "--run", "--project-dir", str(ctx.project_dir)]


def shellcheck_argv(ctx: StageContext) -> list[str]:
    argv = [ctx.python_cmd, _helper("_shellcheck.py"), "--project-dir", str(ctx.project_dir)]
    if _is_json(ctx):
        argv += ["--output-format", "json"]
    return [*argv, *ctx.args]


def psscriptanalyzer_argv(ctx: StageContext) -> list[str]:
    argv = [ctx.python_cmd, _helper("_psscriptanalyzer.py"), "--project-dir", str(ctx.project_dir)]
    if _is_json(ctx):
        argv += ["--output-format", "json"]
    return [*argv, *ctx.args]


def integration_pytest_argv(ctx: StageContext) -> list[str]:
    return ["pytest", "-m", "integration", "--tb=short", "-q", *ctx.args]
