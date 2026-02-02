"""Clean build artifacts and cache directories.

Purpose
-------
Remove build artifacts, cache directories, and temporary files from the project.
Reads patterns from pyproject.toml [tool.clean].patterns or uses built-in defaults.

Contents
--------
* ``clean`` - Remove cached artifacts and build outputs matching patterns.
* ``get_clean_patterns`` - Read clean patterns from pyproject.toml.
* ``main`` - Main entry point for clean utility.

System Role
-----------
Development automation helper that sits alongside other scripts. Supports both
import-time usage and standalone execution via command line.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import Iterable
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


_FALLBACK_PATTERNS: tuple[str, ...] = (
    ".hypothesis",
    ".import_linter_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".pyright",
    ".mypy_cache",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "build",
    "dist",
    "htmlcov",
    ".coverage",
    "coverage.xml",
    "codecov.sh",
    ".cache",
    "result",
)

__all__ = ["clean", "get_clean_patterns", "main"]


def get_clean_patterns(pyproject: Path = Path("pyproject.toml")) -> tuple[str, ...]:
    """Read clean patterns from pyproject.toml [tool.clean].patterns.

    Args:
        pyproject: Path to pyproject.toml file.

    Returns:
        Tuple of glob patterns to clean. Returns fallback patterns if
        pyproject.toml doesn't exist or has no [tool.clean].patterns.
    """
    if not pyproject.exists():
        return _FALLBACK_PATTERNS

    config = load_pyproject_config(pyproject)
    patterns = config.tool.clean.patterns
    if patterns:
        return patterns
    return _FALLBACK_PATTERNS


def clean(
    *,
    project_dir: Path | None = None,
    patterns: Iterable[str] | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Remove cached artefacts and build outputs matching ``patterns``.

    Args:
        project_dir: Root directory to clean from. Defaults to cwd.
        patterns: Glob patterns to remove. If None, reads from pyproject.toml
                  or uses built-in defaults.
        dry_run: If True, only show what would be deleted without removing.
        verbose: If True, list each file/directory being deleted.

    Returns:
        Exit code (0 on success).
    """
    if project_dir is None:
        project_dir = Path.cwd()
    if patterns is None:
        pyproject = project_dir / "pyproject.toml"
        patterns = get_clean_patterns(pyproject)

    removed_count = 0
    for pattern in patterns:
        for path in project_dir.glob(pattern):
            if dry_run:
                print(f"[DRY RUN] Would remove: {path}")  # noqa: T201
                removed_count += 1
            elif path.is_dir():
                if verbose:
                    print(f"Removing directory: {path}")  # noqa: T201
                shutil.rmtree(path, ignore_errors=True)
                removed_count += 1
            else:
                try:
                    if verbose:
                        print(f"Removing file: {path}")  # noqa: T201
                    path.unlink()
                    removed_count += 1
                except FileNotFoundError:
                    continue

    if dry_run:
        print(f"\n[DRY RUN] Would remove {removed_count} items")  # noqa: T201
    elif verbose or removed_count > 0:
        print(f"Removed {removed_count} items")  # noqa: T201

    return 0


def main(
    *,
    project_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Main entry point for clean utility.

    Args:
        project_dir: Root directory to clean from. Defaults to cwd.
        dry_run: If True, only show what would be deleted.
        verbose: If True, list each file/directory being deleted.

    Returns:
        Exit code (0 on success).
    """
    if project_dir is None:
        project_dir = Path.cwd()
    print(f"Cleaning build artifacts in {project_dir}...")  # noqa: T201
    return clean(project_dir=project_dir, dry_run=dry_run, verbose=verbose)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Clean build artifacts and cache directories")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory to clean (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without removing",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="List each file/directory being deleted",
    )
    args = parser.parse_args()
    sys.exit(main(project_dir=args.project_dir, dry_run=args.dry_run, verbose=args.verbose))
