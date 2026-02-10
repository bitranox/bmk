#!/usr/bin/env python3
"""Sync __init__conf__.py version from pyproject.toml.

Reads the version string from pyproject.toml and patches it into
__init__conf__.py so both stay in sync after version bumps.

Derives the package name using the same heuristics as _btx_stagerunner:
    1. hatch wheel packages
    2. project.scripts entry points
    3. project.name fallback

Writes only when the file content actually changes.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from _loader import load_pyproject_config
except ModuleNotFoundError:
    from bmk.makescripts._loader import load_pyproject_config

_VERSION_RE = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)


def derive_package_name(project_dir: Path) -> str:
    """Derive the importable package name from pyproject.toml.

    Uses the same resolution order as _btx_stagerunner.sh:
        1. hatch wheel packages
        2. project.scripts entry points
        3. project.name (hyphens replaced with underscores)

    Args:
        project_dir: Project root containing pyproject.toml.

    Returns:
        Package name string.

    Raises:
        ValueError: If no package name can be derived.
    """
    try:
        import rtoml
    except ImportError:
        import tomllib as rtoml  # type: ignore[no-redef]

    pyproject_path = project_dir / "pyproject.toml"
    with pyproject_path.open("r", encoding="utf-8") as fh:
        data = rtoml.load(fh)  # type: ignore[arg-type]

    # 1. hatch wheel packages
    tool = data.get("tool", {})
    hatch = tool.get("hatch", {})
    build = hatch.get("build", {})
    targets = build.get("targets", {})
    wheel = targets.get("wheel", {})
    packages = wheel.get("packages", [])
    if packages:
        return Path(packages[0]).name

    # 2. project.scripts entry points
    project = data.get("project", {})
    scripts = project.get("scripts", {})
    for spec in scripts.values():
        if ":" in spec:
            module = spec.split(":", 1)[0]
            return module.split(".", 1)[0]

    # 3. project.name fallback
    name = project.get("name", "")
    if name:
        return name.replace("-", "_")

    msg = "Cannot derive package name from pyproject.toml"
    raise ValueError(msg)


def sync_initconf_version(project_dir: Path) -> bool:
    """Patch the version line in __init__conf__.py to match pyproject.toml.

    Args:
        project_dir: Project root directory.

    Returns:
        True if the file was updated, False if already in sync or not found.
    """
    pyproject_path = project_dir / "pyproject.toml"
    config = load_pyproject_config(pyproject_path)
    version = config.project.version
    if not version:
        print("Warning: no [project].version in pyproject.toml", file=sys.stderr)
        return False

    package_name = derive_package_name(project_dir)
    initconf_path = project_dir / "src" / package_name / "__init__conf__.py"

    if not initconf_path.exists():
        return False

    content = initconf_path.read_text(encoding="utf-8")
    new_content = _VERSION_RE.sub(rf"\g<1>{version}\2", content)

    if new_content == content:
        return False

    initconf_path.write_text(new_content, encoding="utf-8")
    print(f"Synced __init__conf__.py version to {version}")
    return True


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Sync __init__conf__.py version from pyproject.toml")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory")
    args, _unknown = parser.parse_known_args()

    try:
        sync_initconf_version(args.project_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
