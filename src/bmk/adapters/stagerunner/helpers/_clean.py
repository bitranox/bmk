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
from pathlib import Path
from typing import TYPE_CHECKING

from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config

if TYPE_CHECKING:
    from collections.abc import Iterable

# The project venv is deliberately absent: bmk provisions and syncs it (see
# ``stagerunner/venv.py``), and the ``push`` pipeline cleans at order 30, right
# after ``test`` - so cleaning it would delete the venv bmk had just built and
# force a full re-resolve on the next command. On a project with a heavy
# dependency tree that is gigabytes of re-download per push, and it buys nothing:
# the sync already removes whatever the manifest no longer asks for. Remove a
# venv by hand when you actually want it gone.
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
    quiet: bool = False,
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
        quiet: If True, suppress the routine "Removed N items" summary (JSON mode).

    Returns:
        Exit code (0 on success).
    """
    if project_dir is None:
        project_dir = Path.cwd()
    if patterns is None:
        pyproject = project_dir / "pyproject.toml"
        patterns = get_clean_patterns(pyproject)

    removed, skipped = _sweep(project_dir, patterns=patterns, dry_run=dry_run, verbose=verbose)
    _print_clean_summary(removed=removed, skipped=skipped, dry_run=dry_run, verbose=verbose, quiet=quiet)
    return 0


def _sweep(project_dir: Path, *, patterns: Iterable[str], dry_run: bool, verbose: bool) -> tuple[int, int]:
    """Remove every contained path matching ``patterns`` and count the outcome.

    Args:
        project_dir: Root directory the patterns are globbed from.
        patterns: Glob patterns to remove, applied in order.
        dry_run: If True, only report what would be removed.
        verbose: If True, print a line per removed or skipped path.

    Returns:
        ``(removed, skipped)``: paths removed (or that would be, in a dry run)
        and paths skipped because they resolve outside ``project_dir``.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     _ = (Path(tmp) / "build").mkdir()
        ...     _sweep(Path(tmp), patterns=["build"], dry_run=False, verbose=False)
        (1, 0)
    """
    resolved_root = project_dir.resolve()
    removed = 0
    skipped = 0
    for pattern in patterns:
        # Iterated lazily, never listed up front: a match is acted on before the
        # glob looks further, so a directory already removed is not descended.
        for path in project_dir.glob(pattern):
            if not _is_contained(path, resolved_root):
                skipped += 1
                if verbose:
                    print(f"Skipping (outside project): {path}")
                continue
            if _remove_path(path, dry_run=dry_run, verbose=verbose):
                removed += 1
    return removed, skipped


def _remove_path(path: Path, *, dry_run: bool, verbose: bool) -> bool:
    """Remove one file or directory, or report it in a dry run.

    Args:
        path: The matched path, already known to lie inside the project.
        dry_run: If True, print what would be removed and touch nothing.
        verbose: If True, print the removal before performing it.

    Returns:
        True when the path counts as removed; False when a file was already
        gone by the time it was unlinked.

    Examples:
        >>> _remove_path(Path("dist"), dry_run=True, verbose=False)
        [DRY RUN] Would remove: dist
        True
    """
    if dry_run:
        print(f"[DRY RUN] Would remove: {path}")
        return True
    if path.is_dir():
        if verbose:
            print(f"Removing directory: {path}")
        shutil.rmtree(path, ignore_errors=True)
        return True
    if verbose:
        print(f"Removing file: {path}")
    try:
        path.unlink()
    except FileNotFoundError:
        # Something else removed it between the glob and here; nothing was
        # removed by this run, so it must not be counted.
        return False
    return True


def _print_clean_summary(*, removed: int, skipped: int, dry_run: bool, verbose: bool, quiet: bool) -> None:
    """Print the closing summary lines of a clean run.

    Args:
        removed: Paths removed, or that would be removed in a dry run.
        skipped: Paths skipped because they resolve outside the project.
        dry_run: If True, print the dry-run summary, which ``quiet`` never hides.
        verbose: If True, print the removal count even when it is zero.
        quiet: If True, suppress the routine removal count (JSON mode).

    Examples:
        >>> _print_clean_summary(removed=2, skipped=1, dry_run=False, verbose=False, quiet=False)
        Skipped 1 paths outside project directory
        Removed 2 items
    """
    if skipped > 0:
        print(f"Skipped {skipped} paths outside project directory")
    if dry_run:
        print(f"\n[DRY RUN] Would remove {removed} items")
    elif not quiet and (verbose or removed > 0):
        print(f"Removed {removed} items")


def main(
    *,
    project_dir: Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    """Main entry point for clean utility.

    Args:
        project_dir: Root directory to clean from. Defaults to cwd.
        dry_run: If True, only show what would be deleted.
        verbose: If True, list each file/directory being deleted.
        quiet: If True, suppress routine informational output (JSON mode).

    Returns:
        Exit code (0 on success).
    """
    if project_dir is None:
        project_dir = Path.cwd()
    if not quiet:
        print(f"Cleaning build artifacts in {project_dir}...")
    return clean(project_dir=project_dir, dry_run=dry_run, verbose=verbose, quiet=quiet)


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
