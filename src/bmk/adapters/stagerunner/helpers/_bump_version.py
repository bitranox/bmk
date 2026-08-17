#!/usr/bin/env python3
"""Version bump utility for pyproject.toml and CHANGELOG.md.

Standalone script that bumps the project version in project files:
- Updates version in pyproject.toml (preserves file formatting)
- Renames [Unreleased] section in CHANGELOG.md to new version with timestamp
- Creates new [Unreleased] section above the versioned entry

The version rules themselves live in ``bmk.domain.version``, shared with the release
gate so the two cannot disagree about what a project version may be. A bump always
lands on a plain release: a non-final version (``1.2.3rc1``, ``1.2.3.dev4``) is
FINALIZED to ``1.2.3`` rather than stepped past it.

Uses _toml_config for TOML parsing to centralize configuration access,
and native string operations to preserve file formatting when writing.

Contents:
    * :func:`update_pyproject` - Update version in pyproject.toml.
    * :func:`update_changelog` - Update CHANGELOG.md with new version section.
    * :func:`main` - CLI entry point.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config
from bmk.domain.enums import BumpPart
from bmk.domain.version import next_version


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
    """Find index of the first versioned ``## [...]`` line (any version spelling).

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
    parser.add_argument("part", choices=[p.value for p in BumpPart], help="Version part to bump")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory")
    args, _unknown = parser.parse_known_args()

    try:
        # Read current version using toml_config
        pyproject_path = args.project_dir / "pyproject.toml"
        config = load_pyproject_config(pyproject_path)
        current_version = config.project.version

        if not current_version:
            print("Error: Could not find [project].version in pyproject.toml", file=sys.stderr)
            return 1

        new_version = next_version(current_version, BumpPart(args.part))

        # Update files
        old_version = update_pyproject(args.project_dir, new_version)
        update_changelog(args.project_dir, new_version)

        print(f"Bumped version: {old_version} -> {new_version}")
        return 0

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
