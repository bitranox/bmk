"""PowerShell linting via PSScriptAnalyzer.

Purpose
-------
Run PSScriptAnalyzer against all ``.ps1`` files in a project, with excluded
rules driven by ``pyproject.toml`` configuration.

Contents
--------
* ``get_excluded_rules`` -- Read excluded rules from pyproject.toml.
* ``check_pwsh`` -- Detect the ``pwsh`` interpreter.
* ``ensure_psscriptanalyzer`` -- Auto-install PSScriptAnalyzer if absent.
* ``find_ps1_files`` -- Discover ``.ps1`` files, skipping vendored dirs.
* ``run_psscriptanalyzer`` -- Invoke PSScriptAnalyzer via subprocess.
* ``main`` -- Main entry point orchestrating the full lint flow.

System Role
-----------
Development automation helper that sits alongside other makescripts.
Reads configuration from ``[tool.psscriptanalyzer]`` in ``pyproject.toml``
and delegates the heavy lifting to ``pwsh`` via subprocess.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from _loader import load_pyproject_config
except ModuleNotFoundError:
    from bmk.makescripts._loader import load_pyproject_config


_FALLBACK_EXCLUDED_RULES: tuple[str, ...] = (
    "PSAvoidUsingWriteHost",
    "PSUseBOMForUnicodeEncodedFile",
    "PSUseUsingScopeModifierInNewRunspaces",
)

_EXCLUDED_DIRS: tuple[str, ...] = (
    ".venv",
    "node_modules",
    ".git",
)

__all__ = [
    "get_excluded_rules",
    "check_pwsh",
    "ensure_psscriptanalyzer",
    "find_ps1_files",
    "run_psscriptanalyzer",
    "main",
]


def _build_missing_section_warning() -> str:
    """Build warning message dynamically from ``_FALLBACK_EXCLUDED_RULES``."""
    items = ",\n".join(f'  "{r}"' for r in _FALLBACK_EXCLUDED_RULES)
    return (
        "WARNING: No [tool.psscriptanalyzer] section found in pyproject.toml.\n"
        "Using built-in fallback rules. For proper configuration, add to your pyproject.toml:\n\n"
        "[tool.psscriptanalyzer]\n"
        "# PSScriptAnalyzer rules to exclude when linting .ps1 files\n"
        f"exclude-rules = [\n{items},\n]\n"
    )


def get_excluded_rules(pyproject: Path = Path("pyproject.toml")) -> tuple[str, ...]:
    """Read excluded rules from pyproject.toml [tool.psscriptanalyzer].exclude-rules.

    Args:
        pyproject: Path to pyproject.toml file.

    Returns:
        Tuple of rule names to exclude. Returns fallback rules if
        pyproject.toml doesn't exist or has no [tool.psscriptanalyzer] section.
    """
    if not pyproject.exists():
        return _FALLBACK_EXCLUDED_RULES

    config = load_pyproject_config(pyproject)
    rules = config.tool.psscriptanalyzer.exclude_rules
    if rules:
        return rules

    print(_build_missing_section_warning(), file=sys.stderr)
    return _FALLBACK_EXCLUDED_RULES


def check_pwsh() -> str | None:
    """Detect the ``pwsh`` interpreter.

    Returns:
        Path to ``pwsh`` executable, or None if not found.
    """
    return shutil.which("pwsh")


def ensure_psscriptanalyzer(pwsh: str) -> None:
    """Auto-install PSScriptAnalyzer module if not already present.

    Args:
        pwsh: Path to the ``pwsh`` executable.
    """
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", "Get-Module -ListAvailable PSScriptAnalyzer"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "PSScriptAnalyzer" not in result.stdout:
        print("Installing PSScriptAnalyzer...")
        subprocess.run(
            [pwsh, "-NoProfile", "-Command", "Install-Module PSScriptAnalyzer -Force -Scope CurrentUser"],
            check=True,
        )


def _is_excluded_dir(path: Path) -> bool:
    """Return True if any path component matches an excluded directory."""
    return any(excluded in path.parts for excluded in _EXCLUDED_DIRS)


def find_ps1_files(project_dir: Path) -> list[Path]:
    """Find all ``.ps1`` files under ``project_dir``, excluding vendored directories.

    Args:
        project_dir: Root directory to search.

    Returns:
        Sorted list of ``.ps1`` file paths.
    """
    files = [p for p in project_dir.rglob("*.ps1") if not _is_excluded_dir(p.relative_to(project_dir))]
    return sorted(files)


def run_psscriptanalyzer(
    *,
    pwsh: str,
    project_dir: Path,
    exclude_rules: tuple[str, ...],
    verbose: bool = False,
) -> int:
    """Invoke PSScriptAnalyzer via subprocess.

    Args:
        pwsh: Path to the ``pwsh`` executable.
        project_dir: Project root to scan.
        exclude_rules: Rule names to exclude.
        verbose: If True, print additional diagnostic output.

    Returns:
        Exit code from PSScriptAnalyzer (0 = clean, >0 = violation count).
    """
    exclude_csv = ",".join(exclude_rules)
    command = (
        f"Invoke-ScriptAnalyzer -Path '{project_dir}' -Recurse"
        f" -Severity Error,Warning"
        f" -ExcludeRule {exclude_csv}"
        f" -EnableExit"
    )
    if verbose:
        print(f'Running: pwsh -NoProfile -Command "{command}"')

    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        check=False,
    )
    return result.returncode


def main(*, project_dir: Path | None = None, verbose: bool = False) -> int:
    """Orchestrate the full PSScriptAnalyzer lint flow.

    Args:
        project_dir: Root directory to lint. Defaults to cwd.
        verbose: If True, print additional diagnostic output.

    Returns:
        Exit code (0 on success, non-zero on lint violations or skip).
    """
    if project_dir is None:
        project_dir = Path.cwd()

    pwsh = check_pwsh()
    if pwsh is None:
        print("pwsh not found -- skipping PowerShell linting.")
        return 0

    ensure_psscriptanalyzer(pwsh)

    files = find_ps1_files(project_dir)
    if not files:
        print("No .ps1 files found -- skipping PowerShell linting.")
        return 0

    print(f"Found {len(files)} .ps1 files to lint.")

    pyproject = project_dir / "pyproject.toml"
    exclude_rules = get_excluded_rules(pyproject)

    exit_code = run_psscriptanalyzer(
        pwsh=pwsh,
        project_dir=project_dir,
        exclude_rules=exclude_rules,
        verbose=verbose,
    )

    if exit_code != 0:
        print(f"PSScriptAnalyzer found lint violations (exit {exit_code})", file=sys.stderr)

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Run PSScriptAnalyzer on PowerShell scripts")
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
    args, _unknown = parser.parse_known_args()
    sys.exit(main(project_dir=args.project_dir, verbose=args.verbose))
