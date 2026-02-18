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

import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

try:
    from _loader import load_pyproject_config
except ModuleNotFoundError:
    from bmk.makescripts._loader import load_pyproject_config


_FALLBACK_PATTERNS: tuple[str, ...] = (
    "**/__pycache__",
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
    ".venv",
    ".data_arch_violations.json",
)

__all__ = ["clean", "get_clean_patterns", "main"]


def _build_missing_section_warning() -> str:
    """Build warning message dynamically from ``_FALLBACK_PATTERNS``."""
    items = ",\n".join(f'  "{p}"' for p in _FALLBACK_PATTERNS)
    return (
        "WARNING: No [tool.clean] patterns found in pyproject.toml.\n"
        "Using built-in fallback patterns. For proper cleaning, add to your pyproject.toml:\n\n"
        "[tool.clean]\n"
        "# Patterns to remove when running `make clean`\n"
        f"patterns = [\n{items},\n]\n"
    )


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

    print(_build_missing_section_warning(), file=sys.stderr)
    return _FALLBACK_PATTERNS


def _is_contained(path: Path, root: Path) -> bool:
    """Return True if *path* is equal to or inside *root* after resolving symlinks.

    Guards against path-traversal patterns (``../``, symlinks) in user-supplied
    glob patterns.  Both paths are resolved to absolute, canonical form before
    comparison.

    >>> _is_contained(Path("/project/.cache"), Path("/project"))
    True
    >>> _is_contained(Path("/project/../etc/passwd"), Path("/project"))
    False
    """
    try:
        return path.resolve().is_relative_to(root.resolve())
    except ValueError:
        return False


def clean(
    *,
    project_dir: Path | None = None,
    patterns: Iterable[str] | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Remove cached artefacts and build outputs matching ``patterns``.

    Only paths that resolve to locations **inside** ``project_dir`` are
    touched.  Patterns containing ``..`` or symlinks pointing outside the
    project boundary are silently skipped, preventing accidental or
    malicious deletion of files above the project root.

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

    resolved_root = project_dir.resolve()
    removed_count = 0
    skipped_count = 0

    for pattern in patterns:
        for path in project_dir.glob(pattern):
            if not _is_contained(path, resolved_root):
                skipped_count += 1
                if verbose:
                    print(f"Skipping (outside project): {path}")
                continue

            if dry_run:
                print(f"[DRY RUN] Would remove: {path}")
                removed_count += 1
            elif path.is_dir():
                if verbose:
                    print(f"Removing directory: {path}")
                shutil.rmtree(path, ignore_errors=True)
                removed_count += 1
            else:
                try:
                    if verbose:
                        print(f"Removing file: {path}")
                    path.unlink()
                    removed_count += 1
                except FileNotFoundError:
                    continue

    if skipped_count > 0:
        print(f"Skipped {skipped_count} paths outside project directory")
    if dry_run:
        print(f"\n[DRY RUN] Would remove {removed_count} items")
    elif verbose or removed_count > 0:
        print(f"Removed {removed_count} items")

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
    print(f"Cleaning build artifacts in {project_dir}...")
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
    args, _unknown = parser.parse_known_args()
    sys.exit(main(project_dir=args.project_dir, dry_run=args.dry_run, verbose=args.verbose))
