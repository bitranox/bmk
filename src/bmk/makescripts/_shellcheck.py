"""Shell linting via shellcheck, shfmt, and bashate.

Purpose
-------
Run shellcheck, shfmt, and bashate against all ``.sh`` files in a project,
with bashate options driven by ``pyproject.toml`` configuration.

Contents
--------
* ``get_bashate_config`` -- Read bashate settings from pyproject.toml.
* ``find_sh_files`` -- Discover ``.sh`` files, skipping vendored dirs.
* ``run_shellcheck`` -- Invoke shellcheck via subprocess.
* ``run_shfmt`` -- Invoke shfmt via subprocess.
* ``run_bashate`` -- Invoke bashate via subprocess.
* ``main`` -- Main entry point orchestrating the full lint flow.

System Role
-----------
Development automation helper that sits alongside other makescripts.
Reads configuration from ``[tool.bashate]`` in ``pyproject.toml``
and delegates the heavy lifting to external tools via subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from _loader import load_pyproject_config
except ModuleNotFoundError:
    from bmk.makescripts._loader import load_pyproject_config


_FALLBACK_BASHATE_MAX_LINE_LENGTH: int = 120
_FALLBACK_BASHATE_IGNORES: tuple[str, ...] = ("E003",)

_EXCLUDED_DIRS: tuple[str, ...] = (
    ".venv",
    "node_modules",
    ".git",
)

__all__ = [
    "get_bashate_config",
    "find_sh_files",
    "run_shellcheck",
    "run_shfmt",
    "run_bashate",
    "main",
]


def _build_missing_section_warning() -> str:
    """Build warning message dynamically from fallback values."""
    items = ",\n".join(f'  "{code}"' for code in _FALLBACK_BASHATE_IGNORES)
    return (
        "WARNING: No [tool.bashate] section found in pyproject.toml.\n"
        "Using built-in fallback settings. For proper configuration, add to your pyproject.toml:\n\n"
        "[tool.bashate]\n"
        "# bashate style settings for .sh files\n"
        f"max-line-length = {_FALLBACK_BASHATE_MAX_LINE_LENGTH}\n"
        f"ignores = [\n{items},\n]\n"
    )


def get_bashate_config(pyproject: Path = Path("pyproject.toml")) -> tuple[int, tuple[str, ...]]:
    """Read bashate settings from pyproject.toml [tool.bashate].

    Args:
        pyproject: Path to pyproject.toml file.

    Returns:
        Tuple of (max_line_length, ignores). Returns fallback values if
        pyproject.toml doesn't exist or has no [tool.bashate] section.
    """
    if not pyproject.exists():
        return _FALLBACK_BASHATE_MAX_LINE_LENGTH, _FALLBACK_BASHATE_IGNORES

    config = load_pyproject_config(pyproject)
    bashate_cfg = config.tool.bashate

    if bashate_cfg.max_line_length != 120 or bashate_cfg.ignores:
        return bashate_cfg.max_line_length, bashate_cfg.ignores

    print(_build_missing_section_warning(), file=sys.stderr)
    return _FALLBACK_BASHATE_MAX_LINE_LENGTH, _FALLBACK_BASHATE_IGNORES


def _is_excluded_dir(path: Path) -> bool:
    """Return True if any path component matches an excluded directory."""
    return any(excluded in path.parts for excluded in _EXCLUDED_DIRS)


def find_sh_files(project_dir: Path) -> list[Path]:
    """Find all ``.sh`` files under ``project_dir``, excluding vendored directories.

    Args:
        project_dir: Root directory to search.

    Returns:
        Sorted list of ``.sh`` file paths.
    """
    files = [p for p in project_dir.rglob("*.sh") if not _is_excluded_dir(p.relative_to(project_dir))]
    return sorted(files)


def run_shellcheck(*, files: list[Path], verbose: bool = False, output_format: str = "text") -> int:
    """Invoke shellcheck against the given files.

    Args:
        files: List of ``.sh`` files to lint.
        verbose: If True, print the command being run.
        output_format: ``"json"`` for machine-readable output, ``"text"`` for human-readable.

    Returns:
        Exit code (0 = clean, non-zero = violations found).
    """
    cmd = ["shellcheck", "-S", "warning", "-x"]
    if output_format == "json":
        cmd.extend(["-f", "json1"])
    cmd.extend(str(f) for f in files)
    if verbose:
        print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, check=False)
    return result.returncode


def run_shfmt(*, files: list[Path], verbose: bool = False) -> int:
    """Invoke shfmt in diff mode against the given files.

    Parse errors (e.g. advanced glob syntax) go to stderr; formatting diffs
    to stdout.  Stderr is suppressed so parse-unsupported constructs don't
    cause false failures -- only actual formatting differences are treated
    as violations.

    Args:
        files: List of ``.sh`` files to check.
        verbose: If True, print the command being run.

    Returns:
        0 if no formatting differences, 1 if differences found.
    """
    cmd = ["shfmt", "-d", "-i", "4", "-bn", "-ci", *[str(f) for f in files]]
    if verbose:
        print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.stdout:
        print(result.stdout)
        print("shfmt found formatting differences", file=sys.stderr)
        return 1
    return 0


def run_bashate(
    *,
    files: list[Path],
    max_line_length: int,
    ignores: tuple[str, ...],
    verbose: bool = False,
) -> int:
    """Invoke bashate against the given files.

    Args:
        files: List of ``.sh`` files to lint.
        max_line_length: Maximum line length.
        ignores: Error codes to ignore.
        verbose: If True, print the command being run.

    Returns:
        Exit code (0 = clean, non-zero = violations found).
    """
    cmd = ["bashate", f"--max-line-length={max_line_length}"]
    if ignores:
        cmd.append(f"--ignore={','.join(ignores)}")
    cmd.extend(str(f) for f in files)

    if verbose:
        print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, check=False)
    return result.returncode


def main(*, project_dir: Path | None = None, verbose: bool = False, output_format: str = "text") -> int:
    """Orchestrate the full shell lint flow.

    Args:
        project_dir: Root directory to lint. Defaults to cwd.
        verbose: If True, print additional diagnostic output.
        output_format: ``"json"`` for machine-readable output, ``"text"`` for human-readable.

    Returns:
        Exit code (0 on success, 1 on lint violations).
    """
    if project_dir is None:
        project_dir = Path.cwd()

    files = find_sh_files(project_dir)
    if not files:
        print("No .sh files found -- skipping shell linting.")
        return 0

    print(f"Found {len(files)} .sh files to lint.")

    pyproject = project_dir / "pyproject.toml"
    max_line_length, ignores = get_bashate_config(pyproject)

    overall_exit = 0

    print("Running shellcheck...")
    if run_shellcheck(files=files, verbose=verbose, output_format=output_format) != 0:
        print("shellcheck found lint violations", file=sys.stderr)
        overall_exit = 1

    print("Running shfmt...")
    if run_shfmt(files=files, verbose=verbose) != 0:
        overall_exit = 1

    print("Running bashate...")
    if run_bashate(files=files, max_line_length=max_line_length, ignores=ignores, verbose=verbose) != 0:
        print("bashate found style issues", file=sys.stderr)
        overall_exit = 1

    return overall_exit


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Run shell linting tools (shellcheck + shfmt + bashate)")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory to lint (default: current directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print additional diagnostic output",
    )
    parser.add_argument(
        "--output-format",
        choices=["json", "text"],
        default="text",
        help="Output format: json for machine-readable, text for human-readable (default: text)",
    )
    args, _unknown = parser.parse_known_args()
    sys.exit(main(project_dir=args.project_dir, verbose=args.verbose, output_format=args.output_format))
