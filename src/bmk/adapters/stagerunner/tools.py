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
from typing import TYPE_CHECKING

from bmk.domain.enums import ToolOutputFormat

from .context import resolve_test_python
from .project import derive_package_name, pip_audit_ignore_flags

if TYPE_CHECKING:
    from collections.abc import Callable

    from .model import StageContext

# The subprocess-invoked helper scripts live next to this module, in helpers/.
_HELPERS_DIR = Path(__file__).resolve().parent / "helpers"


def _is_json(ctx: StageContext) -> bool:
    return ctx.output_format is ToolOutputFormat.JSON


def _helper(name: str) -> str:
    return str(_HELPERS_DIR / name)


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


def ensure_audit_pip_argv(ctx: StageContext) -> list[str]:
    """Install/upgrade a current pip in the interpreter pip-audit will audit.

    pip-audit runs ``<PIPAPI_PYTHON_LOCATION> -m pip``; a uv-created ``.venv`` ships
    no pip, and ensurepip's bundled pip (25.2) is itself flagged. Install the latest
    pip via uv into the pinned interpreter (uv is a bmk prerequisite). Targeting the
    same interpreter ``_pin_project_venv`` pinned keeps ensure-target == audit-target.
    """
    target = ctx.env.get("PIPAPI_PYTHON_LOCATION") or ctx.python_cmd
    return ["uv", "pip", "install", "--python", target, "--upgrade", "pip"]


def pip_audit_argv(ctx: StageContext) -> list[str]:
    ignores = pip_audit_ignore_flags(ctx.project_dir / "pyproject.toml")
    fmt = ["-f", "json"] if _is_json(ctx) else []
    return ["pip-audit", *ignores, *fmt]


def pyright_argv(ctx: StageContext) -> list[str]:
    """``pyright``, pinned at the interpreter whose imports it must resolve.

    pyright does NOT honour ``VIRTUAL_ENV`` (verified against pyright 1.1.x): given no
    ``--pythonpath`` it resolves an interpreter from PATH - and ``_prepend_tool_bin_to_path``
    puts bmk's OWN tool bin first, so an unpinned pyright type-checks the project against
    bmk's environment rather than the one the project declares. That is exactly the defect
    ``_test_python_flags`` guards the pytest stage against.

    It hides well: bmk's env carries bmk's own dependencies (pydantic, rich-click, orjson,
    ...), which overlap what many projects import, so most repos pass by luck. Only a
    project depending on something bmk lacks sees the phantom missing import.

    Omitted when no project venv resolves, which leaves pyright's own PATH discovery - no
    worse than before, and the venv provisioning step reports that problem itself.
    """
    python = resolve_test_python(ctx)
    argv = ["pyright", *(["--pythonpath", python] if python else [])]
    return [*argv, "--outputjson"] if _is_json(ctx) else argv


# --- makescripts .py helper subprocesses ------------------------------------


def _test_python_flags(ctx: StageContext) -> list[str]:
    """``--python <project venv>`` for the helper, or nothing.

    The helper script itself runs under bmk's interpreter (it is stdlib-only), but the
    pytest it spawns must run in the PROJECT's venv - the environment the project
    declares. Passing the interpreter explicitly keeps that decision here, next to the
    other stage wiring, rather than buried in the helper's ``sys.executable``.

    Omitted when no project venv resolves; the helper then reports the problem itself,
    naming the fix. It must never quietly fall back to bmk's interpreter: that is the
    defect (tests running against a tree the project never declared).
    """
    python = resolve_test_python(ctx)
    return ["--python", python] if python else []


def pytest_cov_argv(ctx: StageContext) -> list[str]:
    argv = [ctx.python_cmd, _helper("_coverage.py"), "--run", "--project-dir", str(ctx.project_dir)]
    argv += _test_python_flags(ctx)
    if _is_json(ctx):
        argv += ["--output-format", "json"]
    return argv


def coverage_run_argv(ctx: StageContext) -> list[str]:
    argv = [ctx.python_cmd, _helper("_coverage.py"), "--run", "--project-dir", str(ctx.project_dir)]
    return argv + _test_python_flags(ctx)


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
    """Integration pytest, run from the PROJECT's venv like every other test stage.

    A bare ``pytest`` would resolve off PATH to bmk's own env (see
    ``context._prepend_tool_bin_to_path``), i.e. the wrong dependency tree - the same
    defect as the unit-test stage. Fall back to the bare name only when no project venv
    resolves, so the failure looks the way it always did rather than a confusing
    FileNotFoundError.
    """
    python = resolve_test_python(ctx)
    head = [python, "-m", "pytest"] if python else ["pytest"]
    return [*head, "-m", "integration", "--tb=short", "-q", *ctx.args]


# --- build / version / release / run -----------------------------------------


def python_build_argv(ctx: StageContext) -> list[str]:
    return [ctx.python_cmd, "-m", "build"]


def sync_initconf_argv(ctx: StageContext) -> list[str]:
    return [ctx.python_cmd, _helper("_sync_initconf.py"), "--project-dir", str(ctx.project_dir)]


def bump_argv(kind: str) -> Callable[[StageContext], list[str]]:
    """Build the argv for a ``bump_{major,minor,patch}`` stage."""

    def build(ctx: StageContext) -> list[str]:
        return [ctx.python_cmd, _helper("_bump_version.py"), kind, "--project-dir", str(ctx.project_dir)]

    return build


def release_argv(ctx: StageContext) -> list[str]:
    return [ctx.python_cmd, _helper("_release.py"), "--project-dir", str(ctx.project_dir), *ctx.args]


def run_project_argv(ctx: StageContext) -> list[str]:
    return [ctx.python_cmd, _helper("_run.py"), *ctx.args]
