"""Build a StageContext: the resolved environment a pipeline runs against.

Assembles the environment stages run under: project dir, output format, and the
venv pinning (``VIRTUAL_ENV`` / ``PIPAPI_PYTHON_LOCATION``) that points tools at
the target project's interpreter rather than bmk's own.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from bmk.domain.enums import ToolOutputFormat

from .model import StageContext


def _pin_project_venv(env: dict[str, str], cwd: Path) -> None:
    """Point tools at the target project's venv, not bmk's own (uvx) venv.

    Tools like pyright and pip-audit resolve their environment from
    ``VIRTUAL_ENV``. pip-audit additionally resolves the pip it audits via
    ``sys.executable`` / PATH, not ``VIRTUAL_ENV``, so when a different venv is
    active in the caller's shell it audits the wrong environment; pin it to the
    target interpreter via ``PIPAPI_PYTHON_LOCATION``.

    Two layouts:

    * The project has a ``.venv`` (its dependencies live there): pin at
      ``.venv``'s interpreter.
    * No ``.venv`` (the ``uv tool install --with .`` layout, including bmk
      auditing itself): pin at bmk's own interpreter (``sys.executable``). Its
      tool venv holds bmk plus the project's full dependency tree, so pip-audit
      audits *that*, not whatever ``pip-audit`` sits first on PATH (e.g. an
      editor's venv full of unrelated packages).

    This is the pin at context-build time; the ``pip_audit`` stage re-resolves the
    interpreter when it runs (see ``resolve_audit_python``) so a ``clean`` that removed
    the ``.venv`` in between cannot crash it, and bootstraps a current pip into the
    resolved interpreter (a uv-created ``.venv`` ships no pip) via
    ``tools.ensure_audit_pip_argv``.
    """
    project_venv = cwd / ".venv"
    if project_venv.is_dir() and (project_venv / "pyvenv.cfg").is_file():
        env["VIRTUAL_ENV"] = str(project_venv)
        venv_python = project_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if venv_python.exists():
            env["PIPAPI_PYTHON_LOCATION"] = str(venv_python)
        else:
            env.pop("PIPAPI_PYTHON_LOCATION", None)
    else:
        env.pop("VIRTUAL_ENV", None)
        env["PIPAPI_PYTHON_LOCATION"] = sys.executable


def resolve_audit_python(ctx: StageContext) -> str:
    """Interpreter pip-audit should audit, resolved when the stage runs.

    Prefer the pinned ``PIPAPI_PYTHON_LOCATION`` while it still exists on disk; if it
    is gone (e.g. a ``clean`` stage removed the project ``.venv`` earlier in the same
    pipeline run), fall back to bmk's own interpreter, whose tool venv holds the full
    dependency tree. Resolving at run time - not at context-build time - keeps pip-audit
    from crashing on a pinned interpreter that no longer exists (the ``.venv``-vs-clean
    race).
    """
    pinned = ctx.env.get("PIPAPI_PYTHON_LOCATION")
    if pinned and Path(pinned).exists():
        return pinned
    return ctx.python_cmd


def _prepend_src_to_pythonpath(env: dict[str, str], cwd: Path) -> None:
    """Put the project's ``src/`` on PYTHONPATH so tools can import the package.

    Tools like import-linter and integration pytest import the target project's
    package; when bmk runs from its own (uv tool) venv, the project's ``src`` is
    not otherwise importable. Uses ``os.pathsep`` for cross-OS correctness.
    """
    src_dir = cwd / "src"
    if not src_dir.is_dir():
        return
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing}" if existing else str(src_dir)


def _prepend_tool_bin_to_path(env: dict[str, str]) -> None:
    """Put bmk's own venv bin dir on PATH so bare-name tool stages resolve.

    Tool stages spawn ``ruff`` / ``pytest`` / ``pyright`` / ``pip-audit`` / ``bandit``
    / ``lint-imports`` by bare name (see ``tools.py``), and ``subprocess`` resolves
    those against ``PATH``. bmk's runtime dependencies install those executables next
    to bmk's own interpreter - the ``uv tool install --with .`` venv's ``Scripts``
    (Windows) / ``bin`` (POSIX) dir, i.e. ``Path(sys.executable).parent`` - but that
    dir is *not* on ``PATH`` by default: ``uv tool install`` only exposes bmk's own
    entry points (``bmk``/``mk``). Without this, a machine with no global ruff/pytest
    on PATH fails the first tool stage with ``FileNotFoundError`` (WinError 2 on
    Windows). Prepending also pins tool stages to bmk's *own* pinned toolchain rather
    than whatever ruff/pytest happens to sit first on PATH.
    """
    tool_bin = str(Path(sys.executable).parent)
    existing = env.get("PATH", "")
    env["PATH"] = f"{tool_bin}{os.pathsep}{existing}" if existing else tool_bin


def build_context(
    cwd: Path,
    args: tuple[str, ...],
    *,
    command_prefix: str,
    output_format: ToolOutputFormat,
    show_warnings: bool,
    package_name: str = "",
) -> StageContext:
    """Assemble the StageContext (including the child-process environment)."""
    env = os.environ.copy()
    env["BMK_PROJECT_DIR"] = str(cwd)
    env["BMK_COMMAND_PREFIX"] = command_prefix
    env["BMK_SHOW_WARNINGS"] = "1" if show_warnings else "0"
    env["BMK_PYTHON_CMD"] = sys.executable
    env["BMK_OUTPUT_FORMAT"] = output_format.value  # serialize enum -> env string at the subprocess boundary
    if package_name:
        env["BMK_PACKAGE_NAME"] = package_name
    _prepend_src_to_pythonpath(env, cwd)
    _pin_project_venv(env, cwd)
    _prepend_tool_bin_to_path(env)

    return StageContext(
        project_dir=cwd,
        args=args,
        output_format=output_format,
        python_cmd=sys.executable,
        package_name=package_name,
        env=env,
        show_warnings=show_warnings,
    )
