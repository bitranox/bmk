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
from typing import TYPE_CHECKING

from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from collections.abc import Sequence

_FALLBACK_EXCLUDED_RULES: tuple[str, ...] = (
    "PSAvoidUsingWriteHost",
    "PSUseBOMForUnicodeEncodedFile",
    "PSUseUsingScopeModifierInNewRunspaces",
)

_EXCLUDED_DIRS: tuple[str, ...] = (
    "node_modules",
    ".git",
)

__all__ = [
    "check_pwsh",
    "ensure_psscriptanalyzer",
    "find_ps1_files",
    "get_excluded_rules",
    "main",
    "run_psscriptanalyzer",
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
    """Detect a usable ``pwsh`` interpreter.

    Returns the path only when ``pwsh`` is present *and* can actually launch
    (some Linux setups have a snap-installed ``pwsh`` that fails with
    ``snap-confine`` errors and would never execute scripts).

    Returns:
        Path to a working ``pwsh`` executable, or None if missing/non-functional.
    """
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return None
    try:
        probe = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", "exit 0"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode != 0:
        return None
    return pwsh


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
    """Return True if any path component is a virtualenv or vendored directory.

    A component starting with ``.venv`` counts as a Python virtualenv - the plain
    ``.venv`` plus the dual-OS ``.venv-win`` / ``.venv-linux`` layout - so vendored
    scripts bundled inside any of them (an ``Activate.ps1``, an ``npm.ps1``) never
    trip the linter. ``node_modules`` and ``.git`` still match exactly.
    """
    parts = path.parts
    if any(part.startswith(".venv") for part in parts):
        return True
    return any(excluded in parts for excluded in _EXCLUDED_DIRS)


def find_ps1_files(project_dir: Path) -> list[Path]:
    """Find all ``.ps1`` files under ``project_dir``, excluding vendored directories.

    Args:
        project_dir: Root directory to search.

    Returns:
        Sorted list of ``.ps1`` file paths.
    """
    files = [p for p in project_dir.rglob("*.ps1") if not _is_excluded_dir(p.relative_to(project_dir))]
    return sorted(files)


def _ps_single_quote(value: str) -> str:
    """Wrap ``value`` in a PowerShell single-quoted string literal.

    PowerShell single-quoted strings take everything verbatim; the only escape is a
    doubled ``''`` for an embedded quote. So this is injection-safe for interpolating an
    arbitrary path or token into a ``-Command`` string.
    """
    return "'" + value.replace("'", "''") + "'"


def _exclude_rule_fragment(exclude_rules: tuple[str, ...]) -> str:
    """Build ``-ExcludeRule 'A','B'`` (each element PS-escaped), or ``""`` when empty.

    Each rule is emitted as its own single-quoted array element rather than an unquoted
    CSV, so a metacharacter in a rule name (blocked at the config boundary, but this is
    the defence-in-depth layer) cannot break out of the command.
    """
    if not exclude_rules:
        return ""
    array = ",".join(_ps_single_quote(rule) for rule in exclude_rules)
    return f" -ExcludeRule {array}"


def run_psscriptanalyzer(
    *,
    pwsh: str,
    files: Sequence[Path],
    exclude_rules: tuple[str, ...],
    verbose: bool = False,
    output_format: ToolOutputFormat = ToolOutputFormat.TEXT,
) -> int:
    """Invoke PSScriptAnalyzer over exactly ``files``.

    Takes the resolved file list, NOT the project root: an earlier version passed
    ``-Path <project_dir> -Recurse``, which re-walked the tree and undid every exclusion
    ``find_ps1_files`` had just applied. Discovery was then only a "run at all?" gate, so a
    repo holding one real script plus an in-tree ``.venv`` linted the vendored ``.ps1``
    shipped inside that venv (npm wrappers from ``pyright[nodejs]``). CI never saw it,
    because CI builds its venv outside the repo.

    Args:
        pwsh: Path to the ``pwsh`` executable.
        files: The ``.ps1`` files to lint, as returned by ``find_ps1_files``.
        exclude_rules: Rule names to exclude.
        verbose: If True, print additional diagnostic output.
        output_format: ``JSON`` for machine-readable output, ``TEXT`` for human-readable.

    Returns:
        Exit code: 0 when clean, else the violation count capped at 255.
    """
    if not files:
        return 0

    file_array = ",".join(_ps_single_quote(str(f)) for f in files)
    exclude_fragment = _exclude_rule_fragment(exclude_rules)
    # Each file is analysed by name. `-Recurse` is deliberately absent: it would re-expand
    # any directory back into the tree this list was filtered out of.
    collect = (
        f"$results = @({file_array}) | ForEach-Object {{"
        f" Invoke-ScriptAnalyzer -Path $_ -Severity Error,Warning{exclude_fragment} }};"
    )
    # `@(...)` forces an array: a lone violation is a bare object whose .Count would be
    # unreliable. The cap matters because a POSIX exit status is mod 256, so exactly 256
    # violations would otherwise exit 0 and report a clean run.
    verdict = " $n = @($results).Count; if ($n -gt 255) { exit 255 } else { exit $n }"
    render = " $results | ConvertTo-Json -Depth 5;" if output_format is ToolOutputFormat.JSON else " $results;"
    command = collect + render + verdict

    if verbose:
        print(f'Running: pwsh -NoProfile -Command "{command}"')

    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        check=False,
    )
    return result.returncode


def main(
    *, project_dir: Path | None = None, verbose: bool = False, output_format: ToolOutputFormat = ToolOutputFormat.TEXT
) -> int:
    """Orchestrate the full PSScriptAnalyzer lint flow.

    Args:
        project_dir: Root directory to lint. Defaults to cwd.
        verbose: If True, print additional diagnostic output.
        output_format: ``JSON`` for machine-readable output, ``TEXT`` for human-readable.

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
        files=files,
        exclude_rules=exclude_rules,
        verbose=verbose,
        output_format=output_format,
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
    parser.add_argument(
        "--output-format",
        choices=["json", "text"],
        default="text",
        help="Output format: json for machine-readable, text for human-readable (default: text)",
    )
    args, _unknown = parser.parse_known_args()
    sys.exit(
        main(project_dir=args.project_dir, verbose=args.verbose, output_format=ToolOutputFormat(args.output_format))
    )
