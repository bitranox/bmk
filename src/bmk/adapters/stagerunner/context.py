"""Build a StageContext: the resolved environment a pipeline runs against.

Mirrors the environment the legacy shell path set (project dir, output format,
venv pinning). During migration this duplicates the env logic in
``cli.commands._shared.execute_script``; the shell copy retires in the final
phase, leaving this the single source.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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


def build_context(
    cwd: Path,
    args: tuple[str, ...],
    *,
    command_prefix: str,
    output_format: str,
    show_warnings: bool,
    package_name: str = "",
) -> StageContext:
    """Assemble the StageContext (including the child-process environment)."""
    env = os.environ.copy()
    env["BMK_PROJECT_DIR"] = str(cwd)
    env["BMK_COMMAND_PREFIX"] = command_prefix
    env["BMK_SHOW_WARNINGS"] = "1" if show_warnings else "0"
    env["BMK_PYTHON_CMD"] = sys.executable
    env["BMK_OUTPUT_FORMAT"] = output_format
    if package_name:
        env["BMK_PACKAGE_NAME"] = package_name
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
