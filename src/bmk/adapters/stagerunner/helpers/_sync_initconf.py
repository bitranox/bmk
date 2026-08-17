#!/usr/bin/env python3
"""Sync __init__conf__.py, the bundled Makefile and a shipped plugin version.

Reads the version string from pyproject.toml and patches it into
__init__conf__.py and src/<pkg>/makefile/Makefile so both stay in sync
after version bumps. A repo that also ships a Claude Code skill carries
.claude-plugin/plugin.json, whose version is what an install compares to decide
whether to re-fetch; that one is synced too, but never downward - see
sync_plugin_version.

Derives the package name using the same heuristics as _btx_stagerunner:
    1. hatch wheel packages
    2. project.scripts entry points
    3. project.name fallback

Writes only when the file content actually changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config
from bmk.adapters.stagerunner.project import derive_package_name as _derive

_VERSION_RE = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)
_MAKEFILE_VERSION_RE = re.compile(r"^(# BMK MAKEFILE )\S+")
# The template's minimum-bmk floor. It must track the package version: it is the
# version this template was generated from, and it is what stops uv from silently
# backtracking bmk to an ancient release when a project dependency caps something
# bmk requires.
_MAKEFILE_MIN_RE = re.compile(r"^(BMK_MIN := )\S+", re.MULTILINE)


def derive_package_name(project_dir: Path) -> str:
    """Derive the importable package name from ``project_dir``'s pyproject.toml.

    Delegates to the canonical reader in ``stagerunner.project`` (hatch wheel ->
    script entry point -> project name).

    Raises:
        ValueError: If no package name can be derived.
    """
    name = _derive(project_dir / "pyproject.toml")
    if name is None:
        msg = "Cannot derive package name from pyproject.toml"
        raise ValueError(msg)
    return name


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


def sync_makefile_version(project_dir: Path) -> bool:
    """Patch the version sentinel in the bundled Makefile to match pyproject.toml.

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
    makefile_path = project_dir / "src" / package_name / "makefile" / "Makefile"

    if not makefile_path.exists():
        return False

    content = makefile_path.read_text(encoding="utf-8")
    new_content = _MAKEFILE_VERSION_RE.sub(rf"\g<1>{version}", content, count=1)
    # The floor is the version the template was generated from; left behind it would
    # let uv backtrack bmk past this release without anyone noticing.
    new_content = _MAKEFILE_MIN_RE.sub(rf"\g<1>{version}", new_content, count=1)

    if new_content == content:
        return False

    makefile_path.write_text(new_content, encoding="utf-8")
    print(f"Synced Makefile version and BMK_MIN to {version}")
    return True


def _ordered(version: str) -> Version | None:
    """Return ``version`` as a comparable PEP 440 version, or None if it is not one.

    Wider than the three-part regex this replaced: ``1.0`` and ``2026.07.30-1`` are
    real versions with a defined ordering, and dropping them used to skip the sync
    entirely, letting a skill edit ship unannounced.
    """
    try:
        return Version(version)
    except InvalidVersion:
        return None


def _may_raise_manifest(package_version: str, current: str) -> bool:
    """Whether the manifest may be raised from ``current`` to ``package_version``.

    False on every reason not to write, so the caller stays a single decision:
    either side unreadable, the package version non-final, or the manifest already
    at or above it. See :func:`sync_plugin_version` for why non-final is excluded.
    """
    package_order, current_order = _ordered(package_version), _ordered(current)
    if package_order is None or current_order is None:
        # One of them is not a version at all; there is nothing to order against.
        return False
    if package_order.is_prerelease:
        return False
    return package_order > current_order


def sync_plugin_version(project_dir: Path) -> bool:
    """Raise .claude-plugin/plugin.json to the package version, never lower it.

    A repo that ships a skill publishes it through its own marketplace, and an
    install only re-fetches when this version CHANGES - so a skill edit that never
    moves it ships nothing, silently. Slaving it to the package version removes that
    whole class of mistake.

    The guard matters as much as the sync: a skill legitimately ships more often than
    the package it documents, so the plugin version can legitimately be AHEAD. Writing
    the package version there unconditionally would then move an install BACKWARD to a
    version it already had, which is worse than drift - the number stops meaning
    anything. Measured across the bitranox fleet before this existed, two repos of
    seven were in exactly that state.

    A non-final package version is deliberately NOT written. Ordering it is no longer
    the problem - PEP 440 defines that - but this manifest is read by Claude Code's
    marketplace machinery, and every plugin version seen in the wild is a plain X.Y.Z.
    bmk will not be the first to write ``1.2.0rc1`` there and risk freezing installs;
    the final release that follows carries the skill.

    Args:
        project_dir: Project root directory.

    Returns:
        True if plugin.json was updated, False when it is absent, the package version
        is non-final, either version is unreadable, or the manifest is already at or
        above the package version.
    """
    plugin_path = project_dir / ".claude-plugin" / "plugin.json"
    if not plugin_path.exists():
        return False

    config = load_pyproject_config(project_dir / "pyproject.toml")
    package_version = config.project.version
    if not package_version:
        return False

    try:
        data = json.loads(plugin_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: cannot read {plugin_path.name}: {exc}", file=sys.stderr)
        return False

    current = str(data.get("version", ""))
    if not _may_raise_manifest(package_version, current):
        return False

    data["version"] = package_version
    plugin_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Synced plugin.json version {current} -> {package_version}")
    return True


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Sync __init__conf__.py, Makefile and plugin.json versions from pyproject.toml"
    )
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory")
    args, _unknown = parser.parse_known_args()

    try:
        sync_initconf_version(args.project_dir)
        sync_makefile_version(args.project_dir)
        sync_plugin_version(args.project_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
