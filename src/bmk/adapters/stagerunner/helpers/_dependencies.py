"""Check pyproject.toml dependencies against latest PyPI versions.

Purpose
-------
Scan all dependency specifications in ``pyproject.toml`` and compare them
against the latest available versions on PyPI. This helps keep dependencies
up-to-date and identifies potential upgrades.

Contents
--------
* ``DependencyInfo`` - captures a dependency's current constraint and latest version.
* ``check_dependencies`` - main entry point that checks all dependencies.
* ``print_report`` - renders a formatted report of dependency status.
* ``update_dependencies`` - updates outdated dependencies to latest versions.

System Role
-----------
Development automation helper that sits alongside other scripts. It queries
PyPI via its JSON API to retrieve latest package versions without requiring
additional dependencies.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx2
import orjson

from bmk.adapters.stagerunner.helpers import _typed_tomlkit
from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config

if TYPE_CHECKING:
    from bmk.adapters.stagerunner.helpers._toml_config import PyprojectConfig


__all__ = [
    "DependencyInfo",
    "DependencyStatus",
    "check_dependencies",
    "compare_versions",
    "fetch_latest_version",
    "print_report",
    "sync_installed_packages",
    "update_dependencies",
]


class DependencyStatus(str, Enum):
    """How one declared dependency compares to the latest release on PyPI.

    A ``str`` Enum (not ``StrEnum``: the floor is Python 3.10), so members compare and hash
    equal to their value and the report tables keep working unchanged.
    """

    UP_TO_DATE = "up-to-date"
    OUTDATED = "outdated"
    PINNED = "pinned"
    UNKNOWN = "unknown"
    ERROR = "error"


# HTTP status codes
_HTTP_NOT_FOUND = 404

# Precompiled regex patterns for version parsing and dependency matching
_RE_NAME_SEPARATOR = re.compile(r"[-_.]+")
_RE_VERSION_SPEC = re.compile(r"^([a-zA-Z0-9_.-]+)\s*((?:[><=!~]+\s*[\d.a-zA-Z*]+\s*,?\s*)+)?$")
_RE_MIN_VERSION = re.compile(r"[>=~]=?\s*([\d.]+(?:a\d+|b\d+|rc\d+)?)")
_RE_UPPER_BOUND = re.compile(r"<(?!=)\s*([\d.]+(?:a\d+|b\d+|rc\d+)?)")
_RE_PRERELEASE = re.compile(r"(a|b|rc|dev|alpha|beta)", re.IGNORECASE)
_RE_VERSION_NUMERIC = re.compile(r"^([\d.]+)")
_RE_VERSION_CONSTRAINT = re.compile(r"([><=!~]+)\s*([\d.]+(?:a\d+|b\d+|rc\d+)?)")
_RE_HAS_CONSTRAINT = re.compile(r"[><=!~]")
_RE_PACKAGE_NAME = re.compile(r"^([a-zA-Z0-9_.-]+)")


@dataclass
class DependencyInfo:
    """Information about a single dependency."""

    name: str
    source: str
    constraint: str
    current_min: str
    latest: str
    status: DependencyStatus
    original_spec: str = ""  # Original dependency specification string
    upper_bound: str = ""  # Upper version bound if specified (e.g., "<9" means "9")


def _normalize_name(name: str) -> str:
    """Normalize package name for comparison (PEP 503)."""
    return _RE_NAME_SEPARATOR.sub("-", name).lower()


def _parse_version_constraint(spec: str) -> tuple[str, str, str, str]:
    """Parse a dependency spec into (name, constraint, minimum_version, upper_bound).

    Examples:
        "rich-click>=1.9.4" -> ("rich-click", ">=1.9.4", "1.9.4", "")
        "tomli>=2.0.0; python_version<'3.11'" -> ("tomli", ">=2.0.0", "2.0.0", "")
        "pytest>=8.4.2,<9" -> ("pytest", ">=8.4.2,<9", "8.4.2", "9")
        "hatchling>=1.27.0" -> ("hatchling", ">=1.27.0", "1.27.0", "")
    """
    spec = spec.strip()
    if not spec:
        return "", "", "", ""

    # Remove environment markers (e.g., "; python_version<'3.11'")
    marker_idx = spec.find(";")
    if marker_idx != -1:
        spec = spec[:marker_idx].strip()

    # Handle extras in brackets (e.g., "package[extra]>=1.0")
    bracket_idx = spec.find("[")
    if bracket_idx != -1:
        close_bracket = spec.find("]", bracket_idx)
        if close_bracket != -1:
            spec = spec[:bracket_idx] + spec[close_bracket + 1 :]

    # Extract version constraint
    # Patterns: >=, <=, ==, !=, ~=, >, <
    match = _RE_VERSION_SPEC.match(spec)
    if not match:
        # Fallback: just return the spec as name
        return spec, "", "", ""

    name = match.group(1).strip()
    constraint = match.group(2).strip() if match.group(2) else ""

    # Extract minimum version from constraint
    min_version = ""
    upper_bound = ""
    if constraint:
        # Look for >= or == patterns to find minimum version
        version_match = _RE_MIN_VERSION.search(constraint)
        if version_match:
            min_version = version_match.group(1)

        # Look for < or <= patterns to find upper bound (but not !=)
        upper_match = _RE_UPPER_BOUND.search(constraint)
        if upper_match:
            upper_bound = upper_match.group(1)

    return name, constraint, min_version, upper_bound


def _fetch_pypi_data(package_name: str) -> dict[str, Any] | None:
    """Fetch package data from PyPI."""
    normalized = _normalize_name(package_name)
    url = f"https://pypi.org/pypi/{normalized}/json"

    try:
        response = httpx2.get(url, timeout=10.0)
        response.raise_for_status()
        return orjson.loads(response.content)  # type: ignore[no-any-return]
    except httpx2.HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_NOT_FOUND:
            return None
        return None
    except (httpx2.ConnectError, httpx2.TimeoutException, orjson.JSONDecodeError):
        return None


def fetch_latest_version(package_name: str) -> str | None:
    """Fetch the latest version of a package from PyPI."""
    data = _fetch_pypi_data(package_name)
    if data is None:
        return None
    info = data.get("info")
    if isinstance(info, dict):
        typed_info = cast(dict[str, Any], info)
        version = typed_info.get("version", "")
        return str(version) if version else ""
    return ""


def _fetch_latest_version_below(package_name: str, upper_bound: str) -> str | None:
    """Fetch the latest version of a package that is below the upper bound.

    Args:
        package_name: Name of the package
        upper_bound: Upper version bound (exclusive), e.g., "9" for "<9"

    Returns:
        Latest version string below the bound, or None if not found
    """
    data = _fetch_pypi_data(package_name)
    if data is None:
        return None

    releases = data.get("releases")
    if not isinstance(releases, dict) or not releases:
        return None

    typed_releases = cast(dict[str, Any], releases)

    # Get all version strings and filter to those below upper_bound
    valid_versions: list[tuple[tuple[int, ...], str]] = []
    for version_str in typed_releases:
        # Skip pre-release versions (containing a, b, rc, dev, etc.)
        if _RE_PRERELEASE.search(version_str):
            continue

        version_tuple = _parse_version_tuple(version_str)
        if not version_tuple:
            continue

        # Check if version is below upper_bound
        if not _version_gte(version_str, upper_bound):
            valid_versions.append((version_tuple, version_str))

    if not valid_versions:
        return None

    # Sort by version tuple (descending) and return the highest
    valid_versions.sort(reverse=True, key=lambda x: x[0])
    return valid_versions[0][1]


def _parse_version_tuple(v: str) -> tuple[int, ...]:
    """Parse version string into a tuple of integers for comparison."""
    match = _RE_VERSION_NUMERIC.match(v)
    if not match:
        return ()
    numeric = match.group(1)
    return tuple(int(p) for p in numeric.split(".") if p.isdigit())


def _version_gte(version_a: str, version_b: str) -> bool:
    """Check if version_a >= version_b."""
    a_parts = _parse_version_tuple(version_a)
    b_parts = _parse_version_tuple(version_b)

    # Pad to same length
    max_len = max(len(a_parts), len(b_parts))
    a_padded = a_parts + (0,) * (max_len - len(a_parts))
    b_padded = b_parts + (0,) * (max_len - len(b_parts))

    return a_padded >= b_padded


def compare_versions(current: str, latest: str) -> DependencyStatus:
    """Compare two version strings and return status."""
    if not current or not latest:
        return DependencyStatus.UNKNOWN

    current_parts = _parse_version_tuple(current)
    latest_parts = _parse_version_tuple(latest)

    # Pad to same length for comparison
    max_len = max(len(current_parts), len(latest_parts))
    current_padded = current_parts + (0,) * (max_len - len(current_parts))
    latest_padded = latest_parts + (0,) * (max_len - len(latest_parts))

    if current_padded >= latest_padded:
        return DependencyStatus.UP_TO_DATE
    return DependencyStatus.OUTDATED


def _extract_dependencies_from_list(
    deps: tuple[str, ...] | list[str],
    source: str,
) -> list[DependencyInfo]:
    """Extract dependency info from a list of requirement strings."""
    results: list[DependencyInfo] = []

    for dep in deps:
        if not dep:
            continue
        # Skip direct URL references (PEP 440) - not on PyPI
        if " @ " in dep:
            continue

        original_spec = dep.strip()
        name, constraint, min_version, upper_bound = _parse_version_constraint(dep)
        if not name:
            continue

        # Fetch latest version (respecting upper bound if present)
        latest_absolute = fetch_latest_version(name)
        if latest_absolute is None:
            status = DependencyStatus.ERROR
            latest_str = "not found"
        elif not min_version:
            status = DependencyStatus.UNKNOWN
            latest_str = latest_absolute
        elif upper_bound and _version_gte(latest_absolute, upper_bound):
            # Latest version exceeds our upper bound - check for updates within range
            latest_in_range = _fetch_latest_version_below(name, upper_bound)
            if latest_in_range is None:
                status = DependencyStatus.PINNED
                latest_str = f"{latest_absolute} (pinned <{upper_bound})"
            elif _version_gte(min_version, latest_in_range):
                # We're at the latest version within the allowed range
                status = DependencyStatus.PINNED
                latest_str = f"{latest_absolute} (pinned <{upper_bound})"
            else:
                # There's a newer version within the allowed range
                status = DependencyStatus.OUTDATED
                latest_str = f"{latest_in_range} (max <{upper_bound}, absolute: {latest_absolute})"
        else:
            # No upper bound constraint or latest is within range
            status = compare_versions(min_version, latest_absolute)
            latest_str = latest_absolute

        results.append(
            DependencyInfo(
                name=name,
                source=source,
                constraint=constraint,
                current_min=min_version,
                latest=latest_str,
                status=status,
                original_spec=original_spec,
                upper_bound=upper_bound,
            )
        )

    return results


def _extract_all_dependencies(config: PyprojectConfig) -> list[DependencyInfo]:
    """Extract all dependencies from PyprojectConfig.

    Scans multiple dependency locations in pyproject.toml:
    - project.dependencies
    - project.optional-dependencies
    - build-system.requires
    - dependency-groups (PEP 735)
    - tool.pdm.dev-dependencies
    - tool.poetry.dependencies / dev-dependencies / group.*.dependencies
    - tool.uv.dev-dependencies
    """
    all_deps: list[DependencyInfo] = []

    if config.project.dependencies:
        all_deps.extend(_extract_dependencies_from_list(config.project.dependencies, "[project].dependencies"))

    for group_name, group_deps in config.project.optional_dependencies.items():
        source = f"[project.optional-dependencies].{group_name}"
        all_deps.extend(_extract_dependencies_from_list(group_deps, source))

    if config.build_system.requires:
        all_deps.extend(_extract_dependencies_from_list(config.build_system.requires, "[build-system].requires"))

    for group_name, group_deps in config.dependency_groups.groups.items():
        source = f"[dependency-groups].{group_name}"
        all_deps.extend(_extract_dependencies_from_list(group_deps, source))

    for group_name, group_deps in config.tool.pdm.dev_dependencies.items():
        source = f"[tool.pdm.dev-dependencies].{group_name}"
        all_deps.extend(_extract_dependencies_from_list(group_deps, source))

    if config.tool.poetry.dependencies:
        poetry_deps = [dep.to_requirement_string() for dep in config.tool.poetry.dependencies]
        all_deps.extend(_extract_dependencies_from_list(poetry_deps, "[tool.poetry.dependencies]"))

    if config.tool.poetry.dev_dependencies:
        poetry_dev_deps = [dep.to_requirement_string() for dep in config.tool.poetry.dev_dependencies]
        all_deps.extend(_extract_dependencies_from_list(poetry_dev_deps, "[tool.poetry.dev-dependencies]"))

    for group_name, group_deps in config.tool.poetry.group_dependencies.items():
        poetry_group_deps = [dep.to_requirement_string() for dep in group_deps]
        source = f"[tool.poetry.group.{group_name}.dependencies]"
        all_deps.extend(_extract_dependencies_from_list(poetry_group_deps, source))

    if config.tool.uv.dev_dependencies:
        all_deps.extend(_extract_dependencies_from_list(config.tool.uv.dev_dependencies, "[tool.uv.dev-dependencies]"))

    return all_deps


def check_dependencies(pyproject: Path = Path("pyproject.toml")) -> list[DependencyInfo]:
    """Check all dependencies in pyproject.toml against PyPI.

    Args:
        pyproject: Path to pyproject.toml file

    Returns:
        List of DependencyInfo objects for all found dependencies.
    """
    config = load_pyproject_config(pyproject)
    return _extract_all_dependencies(config)


def print_report(deps: list[DependencyInfo], *, verbose: bool = False) -> int:
    """Print a formatted dependency status report.

    Args:
        deps: List of dependency info objects
        verbose: If True, show all dependencies; if False, show only outdated

    Returns:
        Exit code (0 if all up-to-date, 1 if any outdated)
    """
    if not deps:
        print("No dependencies found in pyproject.toml")
        return 0

    # Group by source
    by_source: dict[str, list[DependencyInfo]] = {}
    for dep in deps:
        by_source.setdefault(dep.source, []).append(dep)

    outdated_count = 0
    error_count = 0

    for source, source_deps in sorted(by_source.items()):
        # Filter if not verbose
        display_deps = source_deps if verbose else [d for d in source_deps if d.status != DependencyStatus.UP_TO_DATE]

        if not display_deps:
            continue

        print(f"\n{source}:")
        print("-" * len(source) + "-")

        # Calculate column widths
        name_width = max(len(d.name) for d in display_deps)
        constraint_width = max(len(d.constraint) for d in display_deps) if display_deps else 0
        latest_width = max(len(d.latest) for d in display_deps)

        for dep in sorted(display_deps, key=lambda d: d.name.lower()):
            status_icon = _get_status_icon(dep.status)
            constraint_display = dep.constraint if dep.constraint else "(any)"

            print(
                f"  {status_icon} {dep.name:<{name_width}}"
                f"  {constraint_display:<{constraint_width}}"
                f"  -> {dep.latest:<{latest_width}}  [{dep.status}]"
            )

            if dep.status == DependencyStatus.OUTDATED:
                outdated_count += 1
            elif dep.status == DependencyStatus.ERROR:
                error_count += 1

    # Summary
    total = len(deps)
    up_to_date = sum(1 for d in deps if d.status == DependencyStatus.UP_TO_DATE)
    pinned = sum(1 for d in deps if d.status == DependencyStatus.PINNED)
    unknown = sum(1 for d in deps if d.status == DependencyStatus.UNKNOWN)

    print(f"\nSummary: {total} dependencies checked")
    print(f"  Up-to-date: {up_to_date}")
    print(f"  Pinned:     {pinned}")
    print(f"  Outdated:   {outdated_count}")
    print(f"  Unknown:    {unknown}")
    print(f"  Errors:     {error_count}")

    if outdated_count > 0:
        print("\nRun with --verbose to see all dependencies")
        return 1
    return 0


def _get_status_icon(status: DependencyStatus) -> str:
    """Get a status icon character (ASCII-safe for Windows compatibility)."""
    icons = {
        DependencyStatus.UP_TO_DATE: "[ok]",
        DependencyStatus.OUTDATED: "[!!]",
        DependencyStatus.PINNED: "[==]",
        DependencyStatus.UNKNOWN: "[??]",
        DependencyStatus.ERROR: "[XX]",
    }
    return icons.get(status, "[??]")


def _build_updated_spec(dep: DependencyInfo) -> str:
    """Build an updated dependency specification with the latest version.

    Preserves the original format (>=, ==, etc.) and any environment markers.
    """
    original = dep.original_spec
    latest = dep.latest

    if not original or not latest or latest == "not found":
        return original

    # Extract just the version number (strip display annotations like "(max <1.3, ...)")
    latest_version = latest.split(" ", 1)[0] if " " in latest else latest

    # Check for environment markers
    marker = ""
    marker_idx = original.find(";")
    if marker_idx != -1:
        marker = original[marker_idx:]
        original = original[:marker_idx].strip()

    # Check for extras
    extras = ""
    bracket_idx = original.find("[")
    if bracket_idx != -1:
        close_bracket = original.find("]", bracket_idx)
        if close_bracket != -1:
            extras = original[bracket_idx : close_bracket + 1]

    # Replace only lower-bound version constraints, preserve upper bounds
    def replace_version(match: re.Match[str]) -> str:
        operator = match.group(1)
        # Preserve upper-bound and exclusion constraints as-is
        if operator in ("<", "<=", "!="):
            return match.group(0)
        return f"{operator}{latest_version}"

    # Replace all version constraints with latest
    updated = _RE_VERSION_CONSTRAINT.sub(replace_version, original)

    # If no version constraint was found, add >=latest_version
    if updated == original and not _RE_HAS_CONSTRAINT.search(original):
        # Extract just the package name
        name_match = _RE_PACKAGE_NAME.match(original)
        if name_match:
            pkg_name = name_match.group(1)
            updated = f"{pkg_name}{extras}>={latest_version}"
        else:
            updated = f"{original}>={latest_version}"
    elif extras and extras not in updated:
        # Re-add extras if they were stripped
        name_match = _RE_PACKAGE_NAME.match(updated)
        if name_match:
            pkg_name = name_match.group(1)
            rest = updated[len(pkg_name) :]
            updated = f"{pkg_name}{extras}{rest}"

    # Re-add environment marker
    if marker:
        updated = f"{updated}{marker}"

    return updated


def _installed_versions(python: str) -> dict[str, str]:
    """Map of normalized package name -> installed version in ``python``'s env.

    Queries the *target* interpreter rather than importing metadata in-process:
    bmk runs from its own tool venv (or whatever venv launched it), so
    ``importlib.metadata`` here would answer for the wrong environment entirely.

    Returns an empty map when the environment cannot be read, which makes every
    dependency look "not installed"; the caller then targets that same
    interpreter, so a wrong answer cannot leak into a different environment.
    """
    argv = ["uv", "pip", "list", "--python", python, "--format", "json"]
    try:
        # argv is built from literals and a resolved path; no shell.
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError:
        return {}
    if result.returncode != 0:
        return {}
    try:
        parsed: object = orjson.loads(result.stdout)
    except orjson.JSONDecodeError:
        return {}
    if not isinstance(parsed, list):
        return {}

    versions: dict[str, str] = {}
    for entry in cast("list[object]", parsed):
        if not isinstance(entry, dict):
            continue
        fields = cast("dict[str, object]", entry)
        name = fields.get("name")
        version = fields.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[_normalize_name(name)] = version
    return versions


def _extras_of(spec: str) -> str:
    """The ``[extra,extra]`` suffix of a dependency spec, or an empty string.

    Extras change what gets installed (``pyright[nodejs]`` pulls a bundled Node),
    so an install spec rebuilt from the bare name silently installs the wrong
    thing.
    """
    open_idx = spec.find("[")
    if open_idx == -1:
        return ""
    close_idx = spec.find("]", open_idx)
    return "" if close_idx == -1 else spec[open_idx : close_idx + 1]


def _marker_of(spec: str) -> str:
    """The ``; <environment marker>`` suffix of a dependency spec, or an empty string.

    The same class of bug as the extras above, with louder consequences. A spec
    rebuilt from the bare name drops the marker, so a dependency meant for ONE
    platform is demanded on EVERY platform - and the install then cannot succeed:
    ``pywin32>=312; sys_platform == 'win32'`` rebuilt as ``pywin32>=312`` fails on
    Linux with "no wheels with a matching platform tag" and takes the whole run
    down. Keeping the marker lets uv evaluate it and skip the package on a platform
    it was never meant for.
    """
    marker_idx = spec.find(";")
    return "" if marker_idx == -1 else spec[marker_idx:]


def _find_packages_needing_install(
    deps: list[DependencyInfo], installed_versions: dict[str, str]
) -> list[tuple[str, str | None, str, str]]:
    """Find packages that need installation or update.

    Args:
        deps: Dependencies parsed from pyproject.toml.
        installed_versions: Normalized name -> version, from the target env.

    Returns:
        List of (name, installed_version, required_version, marker) tuples.
        installed_version is None if not installed; marker is "" when the spec
        carries no environment marker.
    """
    needs_install: list[tuple[str, str | None, str, str]] = []

    for dep in deps:
        if not dep.current_min:
            continue

        installed = installed_versions.get(_normalize_name(dep.name))
        name_with_extras = f"{dep.name}{_extras_of(dep.original_spec)}"
        marker = _marker_of(dep.original_spec)

        if installed is None:
            needs_install.append((name_with_extras, None, dep.current_min, marker))
        elif compare_versions(installed, dep.current_min) == DependencyStatus.OUTDATED:
            needs_install.append((name_with_extras, installed, dep.current_min, marker))

    return needs_install


def _print_install_report(needs_install: list[tuple[str, str | None, str, str]], *, dry_run: bool) -> None:
    """Print report of packages needing installation."""
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Packages needing installation/update:\n")

    for name, installed, required, marker in sorted(needs_install):
        status = "NOT INSTALLED" if installed is None else installed
        # The marker is shown because it explains an entry that will then be skipped:
        # a win32-only package always reads as NOT INSTALLED on Linux.
        print(f"  {name}: {status} -> >={required}{marker}")


def _run_pip_install(needs_install: list[tuple[str, str | None, str, str]], python: str) -> int:
    """Install packages into ``python``'s environment.

    Installs into the *explicitly passed* interpreter (the project's venv), never
    into ``sys.executable``. bmk's helpers run in-process, so ``sys.executable``
    is whatever launched bmk - a shared editor venv, or even a system Python -
    and installing there lets any project silently inflate an environment it does
    not own.

    Uses ``uv pip install --python``, matching how bmk targets every other
    interpreter (see ``tools.ensure_audit_pip_argv``). Because the target is an
    explicit venv, no PEP 668 override is needed or wanted.

    Returns:
        uv exit code
    """
    argv = ["uv", "pip", "install", "--python", python, "--upgrade"]
    # The marker must follow the version, not the name: "pkg>=1; sys_platform == 'win32'"
    # is a valid PEP 508 requirement, "pkg; sys_platform == 'win32'>=1" is not.
    argv.extend(f"{name}>={required}{marker}" for name, _, required, marker in needs_install)

    try:
        return subprocess.run(argv, check=False).returncode
    except OSError:
        print("uv not found on PATH; cannot install dependencies", file=sys.stderr)
        return 1


def sync_installed_packages(
    deps: list[DependencyInfo],
    *,
    python: str,
    dry_run: bool = False,
    quiet: bool = False,
) -> tuple[int, int]:
    """Ensure packages installed in ``python``'s env match pyproject.toml.

    Compares each dependency's required minimum against the version installed in
    the *target* environment and installs there if updates are needed.

    Args:
        deps: List of dependency info objects from check_dependencies
        python: Interpreter whose environment is inspected and installed into
        dry_run: If True, only show what would be installed without installing
        quiet: Suppress informational output

    Returns:
        (number of packages that needed updating, exit code of the install).
        The exit code is reported rather than swallowed so a failed install
        cannot be mistaken for a successful sync.
    """
    needs_install = _find_packages_needing_install(deps, _installed_versions(python))

    if not needs_install:
        if not quiet:
            print("\nAll installed packages match pyproject.toml requirements!")
        return 0, 0

    if not quiet:
        _print_install_report(needs_install, dry_run=dry_run)

    if dry_run:
        if not quiet:
            print(f"\n[DRY RUN] Would install/update {len(needs_install)} packages")
        return len(needs_install), 0

    if not quiet:
        print("\nInstalling/updating packages...")
    exit_code = _run_pip_install(needs_install, python)

    if exit_code == 0:
        if not quiet:
            print(f"\nSuccessfully installed/updated {len(needs_install)} packages")
    else:
        print(f"\ninstall failed with exit code {exit_code}", file=sys.stderr)

    return len(needs_install), exit_code


def _replace_spec(node: Any, original: str, new: str) -> bool:
    """Replace the first array item equal to ``original`` with ``new``, in place.

    Walks the parsed document structurally instead of rewriting the file's text.
    A regex over the raw source cannot tell a dependency spec from the same
    characters inside a comment or an unrelated value, and rewriting text risks
    the surrounding formatting; tomlkit edits the value and leaves every byte it
    did not touch alone, so comments explaining a pin survive an update.

    Stops at the first match, so a spec repeated across sections (for example in
    both ``dependencies`` and an extra) is updated once per dependency entry.

    Returns:
        True if a replacement was made.
    """
    if isinstance(node, dict):
        values = list(cast("dict[str, Any]", node).values())
        return any(_replace_spec(value, original, new) for value in values)
    if isinstance(node, list):
        items = cast("list[Any]", node)
        for index, item in enumerate(items):
            if isinstance(item, str):
                if item == original:
                    items[index] = new
                    return True
            elif isinstance(item, (dict, list)) and _replace_spec(item, original, new):
                return True
    return False


def update_dependencies(
    deps: list[DependencyInfo],
    pyproject: Path = Path("pyproject.toml"),
    *,
    dry_run: bool = False,
    quiet: bool = False,
) -> int:
    """Update outdated dependencies in pyproject.toml to latest versions.

    Args:
        deps: List of dependency info objects from check_dependencies
        pyproject: Path to pyproject.toml file
        dry_run: If True, only show what would be changed without modifying
        quiet: Suppress informational output

    Returns:
        Number of dependencies updated
    """
    outdated = [d for d in deps if d.status == DependencyStatus.OUTDATED]
    if not outdated:
        if not quiet:
            print("All dependencies are up-to-date!")
        return 0

    document = _typed_tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    updated_count = 0

    if not quiet:
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Updating {len(outdated)} dependencies:\n")

    for dep in outdated:
        if not dep.original_spec:
            continue

        new_spec = _build_updated_spec(dep)
        if new_spec == dep.original_spec:
            continue

        if _replace_spec(document, dep.original_spec, new_spec):
            if not quiet:
                print(f"  {dep.name}: {dep.original_spec} -> {new_spec}")
            updated_count += 1
        elif not quiet:
            print(f"  {dep.name}: Could not locate in file (manual update needed)")

    if updated_count > 0:
        if dry_run:
            if not quiet:
                print(f"\n[DRY RUN] Would update {updated_count} dependencies")
        else:
            pyproject.write_text(_typed_tomlkit.dumps(document), encoding="utf-8")
            if not quiet:
                print(f"\nUpdated {updated_count} dependencies in {pyproject}")
    elif not quiet:
        print("\nNo dependencies were updated")

    return updated_count


def main(
    *,
    verbose: bool = False,
    update: bool = False,
    dry_run: bool = False,
    quiet: bool = False,
    pyproject: Path = Path("pyproject.toml"),
    python: str | None = None,
) -> int:
    """Main entry point for dependency checking.

    Args:
        verbose: Show all dependencies, not just outdated ones
        update: Update outdated dependencies to latest versions
        dry_run: Show what would be updated without making changes
        quiet: Suppress informational output (JSON mode)
        pyproject: Path to pyproject.toml
        python: Interpreter to inspect and install into. Required for ``update``;
            without it there is no environment bmk may safely write to, so the
            sync is skipped rather than defaulting to the ambient interpreter.

    Returns:
        Exit code (0 if all up-to-date or the update succeeded, non-zero if any
        dependency is outdated or an install failed)
    """
    if not quiet:
        print(f"Checking dependencies in {pyproject}...")
    deps = check_dependencies(pyproject)
    if not quiet:
        exit_code = print_report(deps, verbose=verbose)
    else:
        exit_code = 1 if any(d.status == DependencyStatus.OUTDATED for d in deps) else 0

    if update:
        # Update pyproject.toml with latest versions
        updated = update_dependencies(deps, pyproject, dry_run=dry_run, quiet=quiet)

        # Re-check dependencies after pyproject.toml update
        if updated > 0 and not dry_run:
            deps = check_dependencies(pyproject)

        if python is None:
            print(
                "No project environment resolved; skipping install sync.",
                file=sys.stderr,
            )
            return 0

        # Sync installed packages with pyproject.toml requirements
        _, install_code = sync_installed_packages(deps, python=python, dry_run=dry_run, quiet=quiet)
        return install_code

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Check/update project dependencies against PyPI")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show all dependencies, not just outdated")
    parser.add_argument("-u", "--update", action="store_true", help="Update outdated dependencies to latest versions")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without making changes")
    parser.add_argument(
        "--project-dir", type=Path, default=Path.cwd(), help="Project directory containing pyproject.toml"
    )
    from bmk.adapters.stagerunner.venv import is_venv, resolve_project_venv, venv_python

    args, _unknown = parser.parse_known_args()
    pyproject = args.project_dir / "pyproject.toml"
    quiet = os.environ.get("BMK_OUTPUT_FORMAT", "json") != "text"

    # Same rule as the stage path: install only into the project's own venv.
    project_venv = resolve_project_venv(args.project_dir, os.environ)
    target = str(venv_python(project_venv)) if is_venv(project_venv) else None

    sys.exit(
        main(
            verbose=args.verbose,
            update=args.update,
            dry_run=args.dry_run,
            quiet=quiet,
            pyproject=pyproject,
            python=target,
        )
    )
