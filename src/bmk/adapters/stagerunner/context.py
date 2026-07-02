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
    project venv's interpreter via ``PIPAPI_PYTHON_LOCATION``.
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
        env.pop("PIPAPI_PYTHON_LOCATION", None)


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

    return StageContext(
        project_dir=cwd,
        args=args,
        output_format=output_format,
        python_cmd=sys.executable,
        package_name=package_name,
        env=env,
        show_warnings=show_warnings,
    )
