"""Invoke the project CLI via uvx from the local development directory.

Purpose
-------
Self-contained runner for the stagerunner pipeline. Reads the project name
and dependencies from ``pyproject.toml``, discovers sibling directories that
match declared dependencies, and invokes the project CLI via ``uvx`` with
``--no-cache`` to ensure fresh builds from source.

This script accepts no options of its own. Everything on the command line
is passed through verbatim to the project CLI. The project directory is
read from the ``BMK_PROJECT_DIR`` environment variable.

Contents
--------
* ``run_cli`` - Build and execute the uvx command with local dependencies.

System Role
-----------
Development automation helper executed by ``run_010_run.sh`` inside the
stagerunner pipeline. Uses ``_toml_config`` for pyproject parsing and
``subprocess.run`` for all operations — no external script imports.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from _loader import load_pyproject_config
except ModuleNotFoundError:
    from bmk.makescripts._loader import load_pyproject_config

if TYPE_CHECKING:
    from _toml_config import PyprojectConfig

__all__ = ["run_cli"]

_RE_DEPENDENCY_NAME = re.compile(r"^([a-zA-Z0-9][-a-zA-Z0-9._]*)")


# ---------------------------------------------------------------------------
# Dependency discovery
# ---------------------------------------------------------------------------


def _extract_dependency_names(config: PyprojectConfig) -> list[str]:
    """Extract normalized dependency package names from config.

    Returns names with hyphens replaced by underscores for filesystem matching.
    """
    names: list[str] = []
    for dep in config.project.dependencies:
        match = _RE_DEPENDENCY_NAME.match(dep.strip())
        if match:
            name = match.group(1).replace("-", "_")
            names.append(name)
    return names


def _find_local_dependencies(project_dir: Path, config: PyprojectConfig) -> list[tuple[str, str]]:
    """Find sibling directories that match project dependencies.

    Scans the parent directory for subdirectories that match dependency names
    and contain a pyproject.toml file (indicating a valid Python project).

    Returns:
        List of tuples (package_name, absolute_path) for local dependencies.
        Package names use hyphens (PyPI convention) for --reinstall-package.
    """
    parent_dir = project_dir.parent
    dependency_names = _extract_dependency_names(config)

    local_deps: list[tuple[str, str]] = []
    for dep_name in dependency_names:
        variants = [dep_name, dep_name.replace("_", "-")]
        for variant in variants:
            sibling = parent_dir / variant
            if sibling.is_dir() and (sibling / "pyproject.toml").exists():
                package_name = dep_name.replace("_", "-")
                local_deps.append((package_name, str(sibling)))
                break
    return local_deps


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------


def run_cli(*, project_dir: Path, args: list[str]) -> int:
    """Invoke the project CLI via uvx using the local development version.

    Uses --no-cache to bypass the cache entirely, ensuring all packages
    (including local dependencies) are always rebuilt from source.
    Discovers sibling directories that match project dependencies and
    includes them with --with flags.

    All arguments are passed through verbatim to the project CLI.

    Args:
        project_dir: Root directory of the project.
        args: Arguments to forward to the project CLI.

    Returns:
        Exit code from uvx execution.
    """
    pyproject_path = project_dir / "pyproject.toml"
    config = load_pyproject_config(pyproject_path)

    project_name = config.project.name
    if not project_name:
        print("[run] Could not read project name from pyproject.toml", file=sys.stderr)
        return 1

    forwarded = args if args else ["--help"]

    command = ["uvx", "--from", str(project_dir), "--no-cache"]

    local_deps = _find_local_dependencies(project_dir, config)
    for _dep_name, local_path in local_deps:
        command.extend(["--with", local_path])

    command.extend([project_name, *forwarded])

    print(f"[run] {' '.join(command)}")
    result = subprocess.run(command, check=False)
    return result.returncode


if __name__ == "__main__":  # pragma: no cover
    project_dir_env = os.environ.get("BMK_PROJECT_DIR")
    if not project_dir_env:
        print("[run] BMK_PROJECT_DIR environment variable must be set", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(run_cli(project_dir=Path(project_dir_env), args=sys.argv[1:]))
