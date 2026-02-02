#!/usr/bin/env python3
"""Version bump utility for pyproject.toml and CHANGELOG.md.

Standalone script that bumps semantic versions in project files:
- Updates version in pyproject.toml (preserves file formatting)
- Renames [Unreleased] section in CHANGELOG.md to new version with timestamp
- Creates new [Unreleased] section above the versioned entry

Uses _toml_config for TOML parsing to centralize configuration access,
and native string operations to preserve file formatting when writing.

Contents:
    * :func:`parse_version` - Parse semantic version string to tuple.
    * :func:`bump_version` - Increment version by specified part.
    * :func:`update_pyproject` - Update version in pyproject.toml.
    * :func:`update_changelog` - Update CHANGELOG.md with new version section.
    * :func:`main` - CLI entry point.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _toml_config import PyprojectConfig


def _load_toml_config_module():
    """Dynamically import _toml_config from the same directory as this script.

    This allows the script to work both when run standalone from the makescripts
    directory and when imported for testing from elsewhere.

    The module is registered in sys.modules to ensure dataclasses can resolve
    type annotations correctly in Python 3.14+.
    """
    # Check if already loaded
    if "_toml_config" in sys.modules:
        return sys.modules["_toml_config"]

    script_dir = Path(__file__).parent
    toml_config_path = script_dir / "_toml_config.py"

    spec = importlib.util.spec_from_file_location("_toml_config", toml_config_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load _toml_config from {toml_config_path}"
        raise ImportError(msg)

    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec to allow dataclasses to work
    sys.modules["_toml_config"] = module
    spec.loader.exec_module(module)
    return module


_toml_config = _load_toml_config_module()


def load_pyproject_config(path: Path) -> PyprojectConfig:
    """Load pyproject.toml configuration using toml_config module."""
    return _toml_config.load_pyproject_config(path)


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse semantic version string to tuple.

    Args:
        version_str: Version string in X.Y.Z format.

    Returns:
        Tuple of (major, minor, patch) integers.

    Raises:
        ValueError: If version string is not in X.Y.Z format.

    Example:
        >>> parse_version("1.2.3")
        (1, 2, 3)
        >>> parse_version("0.0.1")
        (0, 0, 1)
    """
    semver_parts_count = 3
    parts = version_str.split(".")
    if len(parts) != semver_parts_count:
        msg = f"Invalid version format: {version_str}"
        raise ValueError(msg)
    return int(parts[0]), int(parts[1]), int(parts[2])


def bump_version(current: tuple[int, int, int], part: str) -> str:
    """Bump version by specified part.

    Args:
        current: Current version as (major, minor, patch) tuple.
        part: Which part to bump: "major", "minor", or "patch".

    Returns:
        New version string in X.Y.Z format.

    Raises:
        ValueError: If part is not "major", "minor", or "patch".

    Example:
        >>> bump_version((1, 2, 3), "major")
        '2.0.0'
        >>> bump_version((1, 2, 3), "minor")
        '1.3.0'
        >>> bump_version((1, 2, 3), "patch")
        '1.2.4'
    """
    major, minor, patch = current
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    msg = f"Invalid part: {part}"
    raise ValueError(msg)


def update_pyproject(project_dir: Path, new_version: str) -> str:
    """Update version in pyproject.toml, preserving file formatting.

    Uses toml_config for reading and string replacement for writing to preserve
    comments, formatting, and ordering in the original file.

    Args:
        project_dir: Path to project root containing pyproject.toml.
        new_version: New version string to set.

    Returns:
        Previous version string.

    Raises:
        ValueError: If [project].version not found in pyproject.toml.
        FileNotFoundError: If pyproject.toml does not exist.
    """
    pyproject_path = project_dir / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")

    # Parse TOML to get current version using toml_config
    config = load_pyproject_config(pyproject_path)
    old_version = config.project.version
    if not old_version:
        msg = "Could not find [project].version in pyproject.toml"
        raise ValueError(msg)

    # Update version in-place by string replacement (preserves formatting)
    old_line = f'version = "{old_version}"'
    new_line = f'version = "{new_version}"'
    if old_line not in content:
        # Try single quotes
        old_line = f"version = '{old_version}'"
        new_line = f"version = '{new_version}'"

    new_content = content.replace(old_line, new_line, 1)
    pyproject_path.write_text(new_content, encoding="utf-8")
    return old_version


def find_unreleased_line(lines: list[str]) -> int | None:
    """Find index of ## [Unreleased] line (case-insensitive).

    Args:
        lines: List of lines from CHANGELOG.md.

    Returns:
        Line index if found, None otherwise.
    """
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("## [unreleased]"):
            return i
    return None


def find_first_version_line(lines: list[str]) -> int | None:
    """Find index of first ## [X.Y.Z] version line.

    Args:
        lines: List of lines from CHANGELOG.md.

    Returns:
        Line index of first versioned section, None if not found.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## [") and not stripped.lower().startswith("## [unreleased]"):
            return i
    return None


def update_changelog(project_dir: Path, new_version: str) -> None:
    """Update CHANGELOG.md - rename [Unreleased] to new version, add new [Unreleased].

    If [Unreleased] section exists:
    - Keeps [Unreleased] header
    - Inserts blank line and new version header below it

    If no [Unreleased] section:
    - Inserts [Unreleased] and new version before first existing version

    Args:
        project_dir: Path to project root containing CHANGELOG.md.
        new_version: New version string to add.
    """
    changelog_path = project_dir / "CHANGELOG.md"
    if not changelog_path.exists():
        return

    content = changelog_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_version_line = f"## [{new_version}] {timestamp}"

    unreleased_idx = find_unreleased_line(lines)

    if unreleased_idx is not None:
        # Replace [Unreleased] with new [Unreleased] + new version
        lines[unreleased_idx] = "## [Unreleased]"
        lines.insert(unreleased_idx + 1, "")
        lines.insert(unreleased_idx + 2, new_version_line)
    else:
        # No [Unreleased] - insert before first version entry
        first_version_idx = find_first_version_line(lines)
        if first_version_idx is not None:
            lines.insert(first_version_idx, "## [Unreleased]")
            lines.insert(first_version_idx + 1, "")
            lines.insert(first_version_idx + 2, new_version_line)
            lines.insert(first_version_idx + 3, "")

    changelog_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """CLI entry point for version bump utility.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    parser = argparse.ArgumentParser(description="Bump version in pyproject.toml and CHANGELOG.md")
    parser.add_argument("part", choices=["major", "minor", "patch"], help="Version part to bump")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory")
    args = parser.parse_args()

    try:
        # Read current version using toml_config
        pyproject_path = args.project_dir / "pyproject.toml"
        config = load_pyproject_config(pyproject_path)
        current_version = config.project.version

        if not current_version:
            print("Error: Could not find [project].version in pyproject.toml", file=sys.stderr)  # noqa: T201
            return 1

        current = parse_version(current_version)
        new_version = bump_version(current, args.part)

        # Update files
        old_version = update_pyproject(args.project_dir, new_version)
        update_changelog(args.project_dir, new_version)

        print(f"Bumped version: {old_version} -> {new_version}")  # noqa: T201
        return 0

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)  # noqa: T201
        return 1
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}", file=sys.stderr)  # noqa: T201
        return 1


if __name__ == "__main__":
    sys.exit(main())
