"""Invoke the project CLI via uvx from the local development directory.

Purpose
-------
Self-contained runner for the stagerunner pipeline. Reads the project name
and dependencies from ``pyproject.toml``, discovers sibling directories that
match declared dependencies, and invokes the project CLI via ``uvx`` with
``--no-cache`` to ensure fresh builds from source.

Contents
--------
* ``run_cli`` - Build and execute the uvx command with local dependencies.
* ``main`` - Main entry point for standalone execution.

System Role
-----------
Development automation helper executed by ``run_010_run.sh`` inside the
stagerunner pipeline. Uses ``_toml_config`` for pyproject parsing and
``subprocess.run`` for all operations — no external script imports.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _toml_config import PyprojectConfig

__all__ = ["run_cli", "main"]

_RE_DEPENDENCY_NAME = re.compile(r"^([a-zA-Z0-9][-a-zA-Z0-9._]*)")


# ---------------------------------------------------------------------------
# _toml_config dynamic loader (same pattern as _release.py)
# ---------------------------------------------------------------------------


def _load_toml_config_module():
    """Dynamically import _toml_config from the same directory as this script.

    Allows the script to work both when run standalone from the makescripts
    directory and when imported for testing from elsewhere.

    The module is registered in sys.modules to ensure dataclasses can resolve
    type annotations correctly in Python 3.14+.
    """
    if "_toml_config" in sys.modules:
        return sys.modules["_toml_config"]

    script_dir = Path(__file__).parent
    toml_config_path = script_dir / "_toml_config.py"

    spec = importlib.util.spec_from_file_location("_toml_config", toml_config_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load _toml_config from {toml_config_path}"
        raise ImportError(msg)

    module = importlib.util.module_from_spec(spec)
    sys.modules["_toml_config"] = module
    spec.loader.exec_module(module)
    return module


_toml_config = _load_toml_config_module()


def _load_pyproject(path: Path) -> PyprojectConfig:
    """Load pyproject.toml configuration using toml_config module."""
    return _toml_config.load_pyproject_config(path)


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


def run_cli(*, project_dir: Path, args: list[str] | None = None) -> int:
    """Invoke the project CLI via uvx using the local development version.

    Uses --no-cache to bypass the cache entirely, ensuring all packages
    (including local dependencies) are always rebuilt from source.
    Discovers sibling directories that match project dependencies and
    includes them with --with flags.

    Args:
        project_dir: Root directory of the project.
        args: Arguments to forward to the project CLI.

    Returns:
        Exit code from uvx execution.
    """
    pyproject_path = project_dir / "pyproject.toml"
    config = _load_pyproject(pyproject_path)

    project_name = config.project.name
    if not project_name:
        print("[run] Could not read project name from pyproject.toml", file=sys.stderr)
        return 1

    forwarded = list(args) if args else ["--help"]

    command = ["uvx", "--from", str(project_dir), "--no-cache"]

    local_deps = _find_local_dependencies(project_dir, config)
    for _dep_name, local_path in local_deps:
        command.extend(["--with", local_path])

    command.extend([project_name, *forwarded])

    print(f"[run] {' '.join(command)}")
    result = subprocess.run(command, check=False)
    return result.returncode


def main(*, project_dir: Path, args: list[str] | None = None) -> int:
    """Main entry point for run utility.

    Args:
        project_dir: Root directory of the project.
        args: Arguments to forward to the project CLI.

    Returns:
        Exit code (0 on success).
    """
    return run_cli(project_dir=project_dir, args=args)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Run project CLI via uvx")
    parser.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="Project root directory",
    )
    parsed, remaining = parser.parse_known_args()
    sys.exit(main(project_dir=parsed.project_dir, args=remaining or None))
