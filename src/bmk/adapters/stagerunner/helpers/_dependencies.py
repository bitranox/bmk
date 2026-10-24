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
* ``PendingInstall`` / ``sync_installed_packages`` - floors the target environment does not meet yet.

PyPI documents are read through :mod:`._pypi_models`, so nothing here crawls raw JSON.

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
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from functools import cached_property, lru_cache
from itertools import product
from math import prod
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import httpx2
import orjson
from packaging.markers import InvalidMarker, Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, ValidationError

from bmk.adapters.stagerunner.helpers import _typed_tomlkit
from bmk.adapters.stagerunner.helpers._pypi_models import PypiDocument, PypiFile, PypiReleases
from bmk.adapters.stagerunner.helpers._supply_chain import (
    OwnPackageUnreadableError,
    ReleasePolicy,
    SupplyChainConfigError,
    SupplyChainSettings,
    admitted_releases,
    ensure_uv_cooldown,
    floor_pin,
    normalize,
    own_closure,
    reconcile_floor_pins,
    uv_resolved_options,
)
from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config
from bmk.adapters.stagerunner.output_format_env import read_tool_output_format
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, MutableMapping

    from bmk.adapters.stagerunner.helpers._toml_config import PyprojectConfig
    from bmk.adapters.stagerunner.output import SupportsWrite


__all__ = [
    "DependencyInfo",
    "DependencyStatus",
    "PendingInstall",
    "SyncOutcome",
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
# A PyPI package's JSON metadata is at most a few MB; anything past this cap is treated as a
# broken/hostile response rather than buffered into memory.
_MAX_PYPI_BYTES = 32 * 1024 * 1024

# Precompiled regex patterns for version parsing and dependency matching
_RE_NAME_SEPARATOR = re.compile(r"[-_.]+")
_RE_VERSION_SPEC = re.compile(r"^([a-zA-Z0-9_.-]+)\s*((?:[><=!~]+\s*[\d.a-zA-Z*]+\s*,?\s*)+)?$")
# One PEP 440 version, its epoch and pre-, post- and dev-release parts included, so a
# floor such as "7.0.post1" is read and rewritten whole rather than as "7.0." plus leftovers.
_VERSION = r"(?:\d+!)?\d+(?:\.\d+)*(?:\.?(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?"
# The lookbehind keeps the "=" of "<=" and "!=" from reading as a floor ("pkg<=7,>=6" has floor 6).
_RE_MIN_VERSION = re.compile(rf"(?<![<!])[>=~]=?\s*({_VERSION})")
_RE_UPPER_BOUND = re.compile(rf"<(?!=)\s*({_VERSION})")
_RE_VERSION_NUMERIC = re.compile(r"^([\d.]+)")
_RE_VERSION_CONSTRAINT = re.compile(rf"([><=!~]+)\s*({_VERSION})")
_RE_HAS_CONSTRAINT = re.compile(r"[><=!~]")
_RE_PACKAGE_NAME = re.compile(r"^([a-zA-Z0-9_.-]+)")


@dataclass
class DependencyInfo:
    """Information about a single dependency.

    Attributes:
        name: The package name as the project writes it.
        source: The section that declares it (``[project].dependencies``, ...).
        constraint: The version constraint as written.
        current_min: The floor the constraint states; empty when it states none.
        latest_version: The release the report proposes (the one an update writes); None when
            PyPI did not answer for the package.
        status: How the floor compares to that release.
        notes: Why the proposal is what it is, in the order the judgements added them; each is
            shown in parentheses after the version.
        original_spec: The requirement string exactly as written.
        upper_bound: The ``<`` bound, if the constraint has one (``<9`` gives ``9``).
        blocks_lock: An ERROR that ``uv lock`` fails on too, as opposed to one about reading PyPI:
            it fails the check.
    """

    name: str
    source: str
    constraint: str
    current_min: str
    latest_version: str | None
    status: DependencyStatus
    notes: tuple[str, ...] = ()
    original_spec: str = ""
    upper_bound: str = ""
    blocks_lock: bool = False

    @property
    def latest_display(self) -> str:
        """The report's "latest" column: the proposed release and its notes.

        Example:
            >>> DependencyInfo("p", "s", ">=1", "1", "1.2", DependencyStatus.OUTDATED, ("max <2",)).latest_display
            '1.2 (max <2)'
            >>> DependencyInfo("p", "s", ">=1", "1", None, DependencyStatus.ERROR).latest_display
            'not found'
        """
        if self.latest_version is None:
            return "not found"
        return self.latest_version + "".join(f" ({note})" for note in self.notes)

    @property
    def proposed(self) -> str:
        """The proposed release; empty when there is none (PyPI did not answer)."""
        return self.latest_version or ""


def _normalize_name(name: str) -> str:
    """Normalize package name for comparison (PEP 503)."""
    return _RE_NAME_SEPARATOR.sub("-", name).lower()


class _ParsedConstraint(NamedTuple):
    """The parts of a dependency spec the report reads; each is empty when the spec has none.

    Attributes:
        name: The package name, extras and markers removed.
        constraint: The version constraint as written, such as ``>=8.4.2,<9``.
        min_version: The version a ``>=`` / ``==`` / ``~=`` clause sets as the floor.
        upper_bound: The version a ``<`` / ``<=`` clause caps it at.
    """

    name: str
    constraint: str
    min_version: str
    upper_bound: str


def _parse_version_constraint(spec: str) -> _ParsedConstraint:
    """Parse a dependency spec into its name, constraint, minimum version and upper bound.

    Examples:
        "rich-click>=1.9.4" -> ("rich-click", ">=1.9.4", "1.9.4", "")
        "tomli>=2.0.0; python_version<'3.11'" -> ("tomli", ">=2.0.0", "2.0.0", "")
        "pytest>=8.4.2,<9" -> ("pytest", ">=8.4.2,<9", "8.4.2", "9")
        "hatchling>=1.27.0" -> ("hatchling", ">=1.27.0", "1.27.0", "")
    """
    spec = spec.strip()
    if not spec:
        return _ParsedConstraint(name="", constraint="", min_version="", upper_bound="")

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
        return _ParsedConstraint(name=spec, constraint="", min_version="", upper_bound="")

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

    return _ParsedConstraint(name=name, constraint=constraint, min_version=min_version, upper_bound=upper_bound)


# One check reads each package's PyPI document once. The latest lookup, the upper-bound lookup and
# the Python hold then answer from the same document, so a second request that times out cannot
# leave a floor raised past the oldest Python the first one showed it must stay installable on.
_PYPI_DOCUMENTS: ContextVar[dict[str, PypiDocument | None] | None] = ContextVar("_PYPI_DOCUMENTS", default=None)


@contextmanager
def _one_fetch_per_package() -> Generator[None]:
    """Within the block, ``_fetch_pypi_data`` downloads each package at most once.

    A nested block shares the outer one's documents, so a caller that checks twice (before and
    after writing ``[tool.uv]``) reads each package once in all.
    """
    token = _PYPI_DOCUMENTS.set(_PYPI_DOCUMENTS.get() if _PYPI_DOCUMENTS.get() is not None else {})
    try:
        yield
    finally:
        _PYPI_DOCUMENTS.reset(token)


def _fetch_pypi_data(package_name: str, version: str | None = None) -> PypiDocument | None:
    """Fetch package data from PyPI, once per document inside ``_one_fetch_per_package``.

    ``version`` selects that release's own document, whose ``info.requires_dist`` is the one
    release's requirements (the package document carries only the newest release's).

    A failed download is remembered as well, so the dependency reports one error rather than
    a mix of answers from different requests.
    """
    path = _normalize_name(package_name) if version is None else f"{_normalize_name(package_name)}/{version}"
    documents = _PYPI_DOCUMENTS.get()
    if documents is not None and path in documents:
        return documents[path]
    data = _download_pypi_data(path)
    if documents is not None:
        documents[path] = data
    return data


def _download_pypi_data(normalized: str) -> PypiDocument | None:
    """Download one package's JSON document from PyPI, validated into a :class:`PypiDocument`.

    Streamed with a hard byte cap so a broken or hostile endpoint cannot make bmk buffer an
    unbounded body into memory; a response past the cap is treated as unavailable (``None``).
    The URL is fixed to pypi.org, so this is defence-in-depth, not the primary trust boundary.
    A body that is not JSON, or JSON that is not a document (not an object), is unavailable too.
    """
    url = f"https://pypi.org/pypi/{normalized}/json"

    try:
        with httpx2.stream("GET", url, timeout=10.0) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > _MAX_PYPI_BYTES:
                    return None
                chunks.append(chunk)
        return PypiDocument.model_validate(orjson.loads(b"".join(chunks)))
    except httpx2.HTTPStatusError as exc:
        if exc.response.status_code == _HTTP_NOT_FOUND:
            return None
        return None
    except (httpx2.RequestError, orjson.JSONDecodeError, ValidationError):
        # RequestError, not just ConnectError and timeouts: a connection reset mid-body (ReadError,
        # RemoteProtocolError) or a corrupt compressed body (DecodingError) is the same unavailable
        # index and must not crash the check.
        return None


def fetch_latest_version(package_name: str) -> str | None:
    """Fetch the latest version of a package from PyPI."""
    data = _fetch_pypi_data(package_name)
    if data is None:
        return None
    return data.info.version if data.info is not None else ""


def _fetch_latest_version_within(package_name: str, ceiling: SpecifierSet) -> str | None:
    """The newest final release of ``package_name`` that ``ceiling`` admits, or None.

    Args:
        package_name: Name of the package
        ceiling: The requirement's upper bounds and exclusions (``<9``, ``<=2``, ``!=2.0``)

    Returns:
        That release's version string, or None when PyPI lists none
    """
    releases = _releases_of(package_name)
    if not releases:
        return None
    finals = [(v, text) for text in releases if (v := _version_or_none(text)) is not None and not v.is_prerelease]
    within = [(v, text) for v, text in finals if ceiling.contains(v)]
    return max(within)[1] if within else None


def _ceiling_of_spec(spec: str, upper_bound: str) -> SpecifierSet:
    """The upper bounds and exclusions of ``spec``; ``<upper_bound`` when it is not valid PEP 508."""
    specifier = _specifier_of(spec)
    if specifier is not None:
        return _ceiling_of(specifier)
    return SpecifierSet(f"<{upper_bound}") if upper_bound else SpecifierSet()


class _CeilingVerdict(NamedTuple):
    """How a floor whose newest release its ceiling excludes is reported.

    Attributes:
        status: PINNED when nothing inside the ceiling is newer than the floor, else OUTDATED.
        proposed: The release the report proposes.
        note: The report note naming the ceiling.
    """

    status: DependencyStatus
    proposed: str
    note: str


def _judge_against_ceiling(name: str, *, min_version: str, ceiling: SpecifierSet, latest: str) -> _CeilingVerdict:
    """Status, proposed release and note for a floor whose newest release ``ceiling`` excludes.

    Judged on the whole ceiling, so ``<=`` and ``!=`` bound the suggestion as ``<`` does: a floor
    raised past them is a requirement nothing satisfies.
    """
    in_range = _fetch_latest_version_within(name, ceiling)
    if in_range is None or _version_gte(min_version, in_range):
        return _CeilingVerdict(status=DependencyStatus.PINNED, proposed=latest, note=f"pinned {ceiling}")
    return _CeilingVerdict(
        status=DependencyStatus.OUTDATED, proposed=in_range, note=f"max {ceiling}, absolute: {latest}"
    )


def _version_or_none(text: str) -> Version | None:
    """``text`` as a PEP 440 version, or None when it is not one."""
    try:
        return Version(text)
    except InvalidVersion:
        return None


def _parse_version_tuple(v: str) -> tuple[int, ...]:
    """The leading release digits of ``v``: the order of last resort for a string that is not PEP 440."""
    match = _RE_VERSION_NUMERIC.match(v)
    if not match:
        return ()
    numeric = match.group(1)
    return tuple(int(p) for p in numeric.split(".") if p.isdigit())


def _version_gte(version_a: str, version_b: str) -> bool:
    """Whether ``version_a >= version_b`` in PEP 440 order.

    PEP 440 is what an installer orders by, so a post, pre or dev part and an epoch all count. The
    leading-digits tuple is used only when either side is not a version at all.
    """
    a, b = _version_or_none(version_a), _version_or_none(version_b)
    if a is not None and b is not None:
        return a >= b
    a_parts, b_parts = _parse_version_tuple(version_a), _parse_version_tuple(version_b)
    width = max(len(a_parts), len(b_parts))
    return a_parts + (0,) * (width - len(a_parts)) >= b_parts + (0,) * (width - len(b_parts))


def compare_versions(current: str, latest: str) -> DependencyStatus:
    """UP_TO_DATE when ``current >= latest`` in PEP 440 order, else OUTDATED; UNKNOWN for an empty side.

    Example:
        >>> compare_versions("1.0.post2", "1.0.post10").value
        'outdated'
        >>> compare_versions("1!7.0", "1!9.0").value
        'outdated'
    """
    if not current or not latest:
        return DependencyStatus.UNKNOWN
    return DependencyStatus.UP_TO_DATE if _version_gte(current, latest) else DependencyStatus.OUTDATED


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
        parsed = _parse_version_constraint(dep)
        name, min_version, upper_bound = parsed.name, parsed.min_version, parsed.upper_bound
        if not name:
            continue

        # Fetch latest version (respecting upper bound if present)
        latest_absolute = fetch_latest_version(name)
        ceiling = _ceiling_of_spec(original_spec, upper_bound)
        latest_version: str | None = latest_absolute
        notes: tuple[str, ...] = ()
        if latest_absolute is None:
            status = DependencyStatus.ERROR
        elif not min_version:
            status = DependencyStatus.UNKNOWN
        elif not ceiling.contains(latest_absolute, prereleases=True):
            verdict = _judge_against_ceiling(name, min_version=min_version, ceiling=ceiling, latest=latest_absolute)
            status, latest_version, notes = verdict.status, verdict.proposed, (verdict.note,)
        else:
            # No upper bound constraint or latest is within range
            status = compare_versions(min_version, latest_absolute)

        results.append(
            DependencyInfo(
                name=name,
                source=source,
                constraint=parsed.constraint,
                current_min=min_version,
                latest_version=latest_version,
                status=status,
                notes=notes,
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


# How far past the oldest supported minor to look for one a marker applies to. Python 3 minors
# are released yearly, so this covers decades; it only bounds a loop, it is not a version claim.
_MINOR_SCAN = 40
# How many patch releases of one minor to look through for the first that ``requires-python``
# admits. CPython minors reach end of life far below this; it only bounds a loop.
_PATCH_SCAN = 100


@dataclass(frozen=True)
class PythonSupport:
    """The Python 3 minors a project says it supports, for judging which releases it can install.

    A raised floor must still install on the OLDEST of them: a release that drops it makes the
    whole requirement unresolvable there (hypothesis 6.169.0 dropped 3.10, so a 3.10 project
    whose floor was raised to it could no longer install its dev extras on 3.10). It must also keep
    the later ones (:meth:`later_for`): a release capped below the newest classifier is one pip
    refuses there, while uv installs it anyway, so no uv-based gate would show the break.

    Attributes:
        lowest_minor: The oldest supported ``3.X`` minor, as ``python_support`` decides it.
        requires_python: The project's ``requires-python``, or None when absent or unparseable.
        later_minors: The supported ``3.X`` minors after ``lowest_minor``, from the classifiers, ascending.
    """

    lowest_minor: int
    requires_python: SpecifierSet | None = None
    later_minors: tuple[int, ...] = ()

    def later_for(self, spec: str) -> tuple[str, ...]:
        """The supported Pythons after :meth:`oldest_for` on which ``spec`` is installed.

        One per later classifier minor: its first patch ``requires-python`` admits, kept when the
        spec's marker can hold there.

        Example:
            >>> PythonSupport(10, later_minors=(12, 14)).later_for("pkg>=1")
            ('3.12.0', '3.14.0')
        """
        oldest = self.oldest_for(spec)
        if oldest is None:
            return ()
        marker = _marker_of_spec(spec)
        found: list[str] = []
        for minor in self.later_minors:
            patch = _oldest_patch(self.requires_python, minor)
            if minor <= Version(oldest).minor or patch is None:
                continue
            if marker is None or _marker_holds(str(marker), (patch,), ()):
                found.append(patch)
        return tuple(found)

    def oldest_for(self, spec: str) -> str | None:
        """The oldest supported Python, as a full ``3.X.Y``, on which ``spec`` is installed at all.

        Every patch ``requires-python`` admits counts, so ``>=3.10.1`` or ``==3.10.12`` still makes
        3.10 the oldest - probing a bare ``3.10`` would read it as 3.10.0 and skip the minor - and a
        ``python_full_version >= '3.10.1'`` marker is judged on 3.10.1. A marker such as
        ``python_version >= '3.11'`` moves the point up, which is what lets a python-version-split
        pair of requirements each follow its own Pythons. A marker that no Python version satisfies
        here (one about another platform) leaves the oldest supported Python, the conservative answer.

        Example:
            >>> PythonSupport(10).oldest_for("hypothesis>=6; python_version >= '3.11'")
            '3.11.0'
            >>> PythonSupport(10, SpecifierSet(">=3.10.1")).oldest_for("hypothesis>=6")
            '3.10.1'
        """
        admitted = self._admitted
        if not admitted:
            return None
        marker = _marker_of_spec(spec)
        if marker is None:
            return admitted[0]
        # Judged on every platform, never the host's: uv locks a Windows-only requirement on Linux too.
        text = str(marker)
        requires = self.requires_python
        pythons = [v for v in _python_candidates(text, admitted[0]) if requires is None or requires.contains(v)]
        return _oldest_python_holding(text, pythons, ()) or admitted[0]

    @cached_property
    def _admitted(self) -> tuple[str, ...]:
        """Every supported ``3.X.Y``, oldest first, leaving out what ``requires-python`` excludes."""
        minors = range(self.lowest_minor, self.lowest_minor + _MINOR_SCAN)
        versions = (f"3.{minor}.{patch}" for minor in minors for patch in range(_PATCH_SCAN))
        return tuple(v for v in versions if self.requires_python is None or self.requires_python.contains(v))


def _oldest_patch(requires: SpecifierSet | None, minor: int) -> str | None:
    """The first ``3.<minor>.P`` that ``requires`` admits, or None when it admits none."""
    if requires is None:
        return f"3.{minor}.0"
    return next((f"3.{minor}.{p}" for p in range(_PATCH_SCAN) if requires.contains(f"3.{minor}.{p}")), None)


def _shown(python: str) -> str:
    """A Python version for a report line: ``3.10`` for ``3.10.0``, the full version otherwise."""
    return python.removesuffix(".0") if python.count(".") == 2 else python


def _marker_of_spec(spec: str) -> Marker | None:
    _, sep, marker_text = spec.partition(";")
    if not sep or not marker_text.strip():
        return None
    try:
        return Marker(marker_text.strip())
    except InvalidMarker:
        return None


# A requires-python with none of these states no oldest Python ("<4" admits 3.0 by accident).
_LOWER_BOUND_OPERATORS = frozenset({">=", ">", "==", "~=", "==="})


def python_support(config: PyprojectConfig) -> PythonSupport | None:
    """What Pythons the project supports: its classifiers, narrowed by ``requires-python``.

    The classifiers decide, because they are what CI's matrix and bmk's own venv are built
    from, so they name the Pythons the project is actually tested on; a ``requires-python``
    left below them (``>=3.8`` beside classifiers from 3.10) must not drag floors down to
    releases for a Python nobody runs. ``requires-python`` only narrows them, and stands in
    for them when there are none - but only if it has a lower bound of its own.

    Returns None when the project states no oldest Python, so the updater keeps following the
    latest release.
    """
    requires = _specifier_or_none(config.project.requires_python)
    classifiers = sorted(int(v.split(".")[1]) for v in config.project.python_minors() if v.startswith("3."))
    lowest = next((m for m in classifiers if _oldest_patch(requires, m) is not None), None)
    if lowest is None and requires is not None and any(s.operator in _LOWER_BOUND_OPERATORS for s in requires):
        lowest = next((m for m in range(_MINOR_SCAN) if _oldest_patch(requires, m) is not None), None)
    if lowest is None:
        return None
    later = tuple(m for m in classifiers if m > lowest and _oldest_patch(requires, m) is not None)
    return PythonSupport(lowest_minor=lowest, requires_python=requires, later_minors=later)


def _specifier_or_none(text: str) -> SpecifierSet | None:
    if not text.strip():
        return None
    try:
        return SpecifierSet(text)
    except InvalidSpecifier:
        return None


def _installs_on(files: Iterable[PypiFile], python: str | None, *, yanked_ok: bool = False) -> bool:
    """Whether a release has a file whose Requires-Python admits ``python``.

    Yanked files count only with ``yanked_ok``. Missing or unparseable Requires-Python metadata
    admits, as pip treats it. ``python`` None (the project names no oldest Python) admits any file.
    """
    for entry in files:
        if entry.yanked and not yanked_ok:
            continue
        requires = _specifier_or_none(entry.requires_python or "")
        if python is None or requires is None or requires.contains(python):
            return True
    return False


def _installs_on_all(files: tuple[PypiFile, ...], pythons: tuple[str | None, ...], *, yanked_ok: bool = False) -> bool:
    """Whether a release installs on every one of ``pythons`` (see :func:`_installs_on`)."""
    return all(_installs_on(files, python, yanked_ok=yanked_ok) for python in pythons)


def _releases_of(package_name: str) -> PypiReleases | None:
    """The ``releases`` map of a package's PyPI document, or None when PyPI did not provide one."""
    data = _fetch_pypi_data(package_name)
    return data.releases if data is not None else None


# The operators that cap a requirement or exclude a release. A floor bmk writes must still satisfy
# them; the lower bounds are the part the update moves, so they are not consulted.
_CEILING_OPERATORS = frozenset({"<", "<=", "!="})


def _specifier_of(spec: str) -> SpecifierSet | None:
    """Everything a requirement admits, or None when it is not valid PEP 508."""
    try:
        return Requirement(spec).specifier
    except InvalidRequirement:
        return None


def _ceiling_of(specifier: SpecifierSet) -> SpecifierSet:
    """The specifier's upper bounds and exclusions (``<``, ``<=``, ``!=``).

    Example:
        >>> sorted(str(s) for s in _ceiling_of(SpecifierSet(">=1,!=1.5,<=2")))
        ['!=1.5', '<=2']
    """
    return SpecifierSet(",".join(str(s) for s in specifier if s.operator in _CEILING_OPERATORS))


def _admits_installable(
    releases: PypiReleases,
    *,
    python: str | None,
    specifier: SpecifierSet,
    accept: Callable[[str], bool] | None = None,
    also: tuple[str, ...] = (),
) -> bool:
    """Whether anything ``specifier`` admits installs on ``python``, judged as uv would choose.

    A prerelease counts as uv resolves it (:func:`_prereleases_allowed`); ``prereleases`` is passed
    explicitly because packaging 26's default admits any prerelease the bounds cover. A
    yanked release counts only when the specifier pins it exactly: PEP 592 lets an installer take a yanked release
    for ``==`` / ``===``, and uv (which provisions bmk's venvs) takes it in no other case. ``also``
    names further Pythons that must each find SOME release the specifier admits - not the same one:
    an installer resolves per interpreter, so `pythonnet>=3.1.0` serves 3.10 with 3.1.0 and 3.15 with
    3.2.1 although no release covers both (OPEN-WORK [3]).
    """
    exact = any(s.operator == "===" or (s.operator == "==" and not s.version.endswith(".*")) for s in specifier)
    prereleases = _prereleases_allowed(releases, named=bool(specifier.prereleases))
    # Newest first: ``accept`` reads PyPI per release, and the newest admitted one usually settles it.
    ordered = sorted(releases.items(), key=lambda item: _sort_key(item[0]), reverse=True)
    found = any(
        specifier.contains(version, prereleases=prereleases)
        and _installs_on_all(files, (python,), yanked_ok=exact)
        and (accept is None or accept(version))
        for version, files in ordered
    )
    return found and all(_admits_installable(releases, python=p, specifier=specifier) for p in also)


def _sort_key(text: str) -> tuple[int, Version]:
    """Valid versions in PEP 440 order, every invalid one below them."""
    try:
        return (1, Version(text))
    except InvalidVersion:
        return (0, Version("0"))


def _prereleases_allowed(releases: PypiReleases, *, named: bool) -> bool:
    """Whether uv would take a prerelease from ``releases``: when the requirement names one, or
    when the package publishes nothing else (uv's default ``if-necessary-or-explicit``)."""
    return named or not any((v := _version_or_none(text)) is not None and not v.is_prerelease for text in releases)


def _newest_installable(
    releases: PypiReleases,
    *,
    python: str | None,
    ceiling: SpecifierSet,
    prereleases_named: bool = False,
    accept: Callable[[str], bool] | None = None,
    also: tuple[str, ...] = (),
) -> str | None:
    """The newest release in ``releases``, in PEP 440 order, that installs on ``python`` and ``ceiling`` admits.

    A prerelease is a candidate only where uv would take one (:func:`_prereleases_allowed`), so
    ``prereleases_named`` says whether the whole requirement names one - its ceiling alone cannot.
    ``accept`` is asked last and newest first, so a costly judgement runs on as few releases as it can.
    ``also`` names further Pythons that must each still find a release at or above the one chosen,
    so a floor there never strands them; they need not share that release (see
    :func:`_admits_installable`). A Python with no release under ``ceiling`` sets no limit.
    """
    prereleases = _prereleases_allowed(releases, named=prereleases_named)
    limits = [
        Version(newest)
        for p in also
        if (newest := _newest_installable(releases, python=p, ceiling=ceiling, prereleases_named=prereleases_named))
        is not None
    ]
    highest = min(limits, default=None)
    candidates: list[tuple[Version, str]] = []
    for text, files in releases.items():
        version = _version_or_none(text)
        if version is None or (version.is_prerelease and not prereleases):
            continue
        if not ceiling.contains(version, prereleases=prereleases):
            continue
        if highest is not None and version > highest:
            continue
        if _installs_on_all(files, (python,)):
            candidates.append((version, text))
    return next((v for _, v in sorted(candidates, reverse=True) if accept is None or accept(v)), None)


# A floor is judged in these states; UNKNOWN has no floor to judge and ERROR has no release data.
_JUDGED_FLOORS = frozenset({DependencyStatus.OUTDATED, DependencyStatus.UP_TO_DATE, DependencyStatus.PINNED})


def _hold_to_supported_python(
    dep: DependencyInfo, support: PythonSupport | None, policy: ReleasePolicy | None = None
) -> DependencyInfo:
    """Keep a dependency's floor installable on the oldest supported Python, under the cooldown.

    Two limits apply, both judged against the newest release that is still admitted:

    * the oldest Python the project supports must be able to install it - and so must each later
      supported Python the requirement as written already installs on (:meth:`PythonSupport.later_for`), and
    * under ``[tool.uv] exclude-newer`` it must have been uploaded before the cutoff, since uv
      will not resolve anything newer (``policy``).

    Two cases follow:

    * The CURRENT floor admits no such release. If nothing it allows installs on that Python, the
      floor is lowered to the newest admitted release and reported OUTDATED: the one case in which
      bmk lowers one. If only the cooldown keeps it out, the floor is kept and reported as an
      ERROR: lowering would drop the fixes it was raised for, and ``deps --update`` pins the
      release instead (``_pin_young_floors``), after which it is admitted.
    * An OUTDATED suggestion is above it. The suggestion is held to that release. When the floor
      already is that release, the dependency is PINNED if the Python is what holds it, and
      UP-TO-DATE if only the cooldown does: a release still in its cooldown is not yet due.

    When the release list cannot be read, an OUTDATED floor is kept and reported as an ERROR:
    raising it blind is exactly the move this check exists to prevent.
    """
    if dep.status not in _JUDGED_FLOORS or not dep.current_min:
        return dep
    cutoff = policy.cutoff_for(dep.name) if policy is not None else None
    python = support.oldest_for(dep.original_spec) if support is not None else None
    # An exempt package under an active cooldown takes its newest release, but only one whose own
    # requirements the cooldown admits: a floor on any other makes `uv lock` unsatisfiable.
    exempt = policy is not None and policy.default is not None and cutoff is None
    if python is None and cutoff is None and not exempt:
        return dep
    lockable = (
        _LockJudge(policy, python).accepts(dep.name, _requested_extras(dep.original_spec))
        if policy is not None and exempt
        else None
    )
    later = support.later_for(dep.original_spec) if support is not None else ()
    try:
        return _judge_floor(dep, python=python, later=later, cutoff=cutoff, lockable=lockable)
    except _UnjudgeableError as exc:
        return _keep_outdated_floor(dep, why=str(exc))


# One release as it is requested: its name (PEP 503), its version and the extras asked of it.
_ReleaseKey = tuple[str, str, frozenset[str]]
# One requirement on a package: its specifier, the Python it serves, and whether it pins exactly.
_NeedKey = tuple[str, str | None, bool]


class _UnjudgeableError(Exception):
    """A release's requirements, or a requirement's releases, could not be read from PyPI."""


class _LockJudge:
    """Whether ``uv lock`` can resolve a release under the project's cooldown.

    A release locks when every requirement that applies to the project has a release the cooldown
    admits; a requirement on another exempt package needs one that itself locks. Judged from PyPI
    metadata, not by running uv: ``requires-python`` of transitive releases is not consulted.
    """

    def __init__(self, policy: ReleasePolicy, python: str | None) -> None:
        self._policy = policy
        self._python = python
        self._judged: dict[_ReleaseKey, bool] = {}

    def accepts(self, name: str, extras: frozenset[str] = frozenset()) -> Callable[[str], bool]:
        return lambda version: self.locks(name, version, frozenset(), extras=extras)

    def locks(
        self, name: str, version: str, seen: frozenset[_ReleaseKey], *, extras: frozenset[str] = frozenset()
    ) -> bool:
        key = (_normalize_name(name), version, extras)
        if key in seen:
            return True  # a cycle among own packages adds no requirement of its own
        if key not in self._judged:
            requires = _requires_of_release(name, version)
            if requires is None:
                raise _UnjudgeableError(f"requirements of {name} {version} unreadable")
            applying = (r for r in requires if _marker_applies(r, self._python, extras=extras))
            self._judged[key] = all(self._satisfiable(r, seen | {key}) for r in applying)
        return self._judged[key]

    def _satisfiable(self, requirement: Requirement, seen: frozenset[_ReleaseKey]) -> bool:
        releases = _releases_of(requirement.name)
        if releases is None:
            raise _UnjudgeableError(f"release list of {requirement.name} unreadable")
        cutoff = self._policy.cutoff_for(requirement.name)
        specifier = requirement.specifier
        matching = sorted(
            (
                v
                for v in admitted_releases(releases, cutoff)
                if _is_version(v) and specifier.contains(v, prereleases=bool(specifier.prereleases))
            ),
            key=Version,
            reverse=True,
        )
        if cutoff is not None:
            return bool(matching)
        extras = frozenset(requirement.extras)
        return any(self.locks(requirement.name, v, seen, extras=extras) for v in matching)


# `uv lock` is universal: it resolves for every platform and Python the project admits, so whether a
# marker applies is decided over every value a comparison in it can see - the literals it names,
# values below, above, between and around them, and every Python minor from the oldest up - never the
# host's own values, which packaging fills in for any variable left unset. Variables are varied
# independently, so a combination no real platform has (os_name "nt" with sys_platform "linux") can
# count as applying; that costs at most a pin nothing needed, never a missing one.
_MARKER_OP = r"(?:===|==|!=|<=|>=|~=|<|>|not in|in)"
_MARKER_LITERAL = r"(?:\"([^\"]*)\"|'([^']*)')"
_MARKER_COMPARISON = re.compile(
    rf"\b([a-z_]+) {_MARKER_OP} {_MARKER_LITERAL}|{_MARKER_LITERAL} {_MARKER_OP} ([a-z_]+)\b"
)
_PYTHON_VARIABLES = frozenset({"python_version", "python_full_version"})
# Below and above every literal, as a version and as a string, and equal to none of them.
_BEYOND_LITERALS = frozenset({"", "0", "9999", "~"})
# Past this many environments a marker is taken to apply: a wasted pin is cheap, a hung gate is not.
_MARKER_ENVIRONMENT_CAP = 50_000


def _marker_applies(requirement: Requirement, python: str | None, *, extras: Iterable[str] = ()) -> bool:
    """Whether ``requirement`` applies to the project anywhere ``uv lock`` resolves for it.

    ``python`` is the oldest Python the requirement's parent is installed on; every later one counts
    too. ``extras`` are the extras the parent was requested with: a requirement behind any other
    extra is never installed.
    """
    if requirement.marker is None:
        return True
    text = str(requirement.marker)
    return _marker_holds(text, tuple(_python_candidates(text, python)), tuple(sorted(extras)))


def _oldest_python_applying(requirement: Requirement, python: str | None, *, extras: Iterable[str] = ()) -> str | None:
    """The oldest Python, from ``python`` up, on which ``requirement`` applies.

    ``python`` itself when the marker names no Python version (or when there is no ``python``), so a
    release gated to newer Pythons is judged installable where uv actually needs it.
    """
    marker = requirement.marker
    if marker is None or python is None:
        return python
    return _oldest_python_holding(str(marker), _python_candidates(str(marker), python), tuple(sorted(extras))) or python


def _oldest_python_holding(text: str, pythons: list[str], extras: tuple[str, ...]) -> str | None:
    """The first of ``pythons`` on which the marker ``text`` can hold, or None; None also when it
    names no Python version at all, since then no Python decides it."""
    if not _literals(text).keys() & _PYTHON_VARIABLES:
        return None
    # A capped candidate never decides: answering "holds" there would pick too old a Python. A marker
    # past the cap on every Python falls back to the caller's oldest, as an unreadable one does.
    return next((v for v in pythons if _marker_holds(text, (v,), extras, when_capped=False)), None)


@lru_cache(maxsize=4096)
def _marker_holds(text: str, pythons: tuple[str, ...], extras: tuple[str, ...], *, when_capped: bool = True) -> bool:
    """Whether the marker ``text`` holds for some environment on one of ``pythons`` with ``extras``.

    ``when_capped`` is the answer past ``_MARKER_ENVIRONMENT_CAP`` environments: True where a
    wrong yes costs a wasted pin, False where it would pick too old a Python.
    """
    literals = _literals(text)
    named = {_normalize_name(e) for e in literals.get("extra", set())}
    requested = [e for e in extras if _normalize_name(e) in named]
    axes: list[list[dict[str, str]]] = [[{"extra": e} for e in ("", *requested)]]
    if literals.keys() & _PYTHON_VARIABLES:
        axes.append([{"python_version": v.rsplit(".", 1)[0], "python_full_version": v} for v in pythons])
    axes.extend(
        [{name: value} for value in sorted(_around(values))]
        for name, values in literals.items()
        if name not in _PYTHON_VARIABLES and name != "extra"
    )
    if prod(len(axis) for axis in axes) > _MARKER_ENVIRONMENT_CAP:
        return when_capped
    try:
        marker = Marker(text)
        return any(
            marker.evaluate({k: v for part in combination for k, v in part.items()}) for combination in product(*axes)
        )
    except Exception:  # an unevaluable marker may apply, so it is judged
        return True


def _around(values: set[str]) -> set[str]:
    """``values``, values beyond all of them, and a value just above each: between it and the next as a
    version, and containing it but unequal to it, for ``in``."""
    return values | _BEYOND_LITERALS | {f"{v}.1" for v in values}


def _literals(text: str) -> dict[str, set[str]]:
    """Every value each variable is compared against in the marker ``text``."""
    found: dict[str, set[str]] = {}
    for match in _MARKER_COMPARISON.finditer(text):
        if match.group(1) is not None:
            variable, value = match.group(1), _first(match.group(2), match.group(3))
        else:
            variable, value = match.group(6), _first(match.group(4), match.group(5))
        found.setdefault(variable, set()).add(value)
    return found


def _first(*groups: str | None) -> str:
    return next(g for g in groups if g is not None)


def _python_candidates(text: str, python: str | None) -> list[str]:
    """The Pythons from ``python`` up that decide every Python comparison in the marker ``text``.

    The first and last patch of every minor from ``python``'s up, ``python`` itself, and beside each
    version the marker names (in any spelling: ``3.11.*``, ``'3.11 3.12'``, ``3.12.0rc1``) that
    patch and the ones next to it.
    """
    oldest = Version(python or "3.0.0")
    last = _PATCH_SCAN - 1
    found = {str(oldest)} | {f"3.{m}.{p}" for m in range(oldest.minor, oldest.minor + _MINOR_SCAN) for p in (0, last)}
    for variable, values in _literals(text).items():
        if variable in _PYTHON_VARIABLES:
            for value in values:
                found.update(_pythons_beside(value))
    return sorted((v for v in found if Version(v) >= oldest), key=Version)


def _pythons_beside(value: str) -> list[str]:
    """The patches at and next to each version ``value`` names (a list for ``in``, ``.*`` stripped)."""
    beside: list[str] = []
    for word in value.split():
        try:
            release = Version(word.removesuffix(".*")).release
        except InvalidVersion:
            continue
        if len(release) < 2:
            continue
        minor, patch = release[1], release[2] if len(release) > 2 else 0
        beside += [f"3.{minor}.{p}" for p in (patch, patch + 1, max(patch - 1, 0))]
    return beside


def _is_version(text: str) -> bool:
    try:
        Version(text)
    except InvalidVersion:
        return False
    return True


def _requires_of_release(name: str, version: str) -> list[Requirement] | None:
    """One release's parsed requirements from its own PyPI document, or None when unreadable."""
    data = _fetch_pypi_data(name, version)
    if data is None or data.info is None:
        return None
    parsed = (_requirement_or_none(spec) for spec in data.info.requires_dist)
    return [r for r in parsed if r is not None]


def _requested_extras(spec: str) -> frozenset[str]:
    """The extras ``spec`` requests (``widget[fast]`` requests ``fast``), none when it is not PEP 508."""
    requirement = _requirement_or_none(spec)
    return frozenset(requirement.extras) if requirement is not None else frozenset()


def _requirement_or_none(spec: str) -> Requirement | None:
    """``spec`` parsed, or None when it is not valid PEP 508 (an installer skips it too)."""
    try:
        return Requirement(spec)
    except InvalidRequirement:
        return None


def _judge_floor(
    dep: DependencyInfo,
    *,
    python: str | None,
    cutoff: datetime | None,
    lockable: Callable[[str], bool] | None = None,
    later: tuple[str, ...] = (),
) -> DependencyInfo:
    """Lower, hold or keep ``dep``'s floor against ``python``, ``later``, the cooldown ``cutoff`` and ``lockable``.

    Raises:
        _UnjudgeableError: When ``lockable`` cannot read the metadata it judges from.
    """
    specifier = _specifier_of(dep.original_spec)
    if specifier is None:
        return _keep_outdated_floor(dep, why="requirement is not valid PEP 508")
    releases = _releases_of(dep.name)
    if releases is None:
        return _keep_outdated_floor(dep, why="release list unreadable")
    admitted = admitted_releases(releases, cutoff)
    ceiling = _ceiling_of(specifier)
    named = bool(specifier.prereleases)
    # Never lose a Python (user decision 2026-10-23): a later supported Python holds the floor only
    # where the requirement as written already installs; one no admitted release ever installed on
    # is not the update's to fix. uv ignores a Requires-Python upper bound, so only pip shows it.
    also = tuple(p for p in later if _admits_installable(releases, python=p, specifier=specifier))
    installable = _newest_installable(
        admitted, python=python, ceiling=ceiling, prereleases_named=named, accept=lockable, also=also
    )
    if installable is None:
        why = _no_release_why(
            releases, python=python, ceiling=ceiling, prereleases_named=named, lockable=lockable, also=also
        )
        return _unsatisfiable_floor(dep, why=why)
    # Judged on the whole specifier, so ">", "==" and "~=" floors count exactly as written.
    if not _admits_installable(admitted, python=python, specifier=specifier, accept=lockable, also=also):
        why = _floor_why(
            admitted, releases, python=python, specifier=specifier, lockable=lockable is not None, also=also
        )
        if _admits_installable(releases, python=python, specifier=specifier, also=also):
            # Only the cooldown stands in the way. Lowering would drop the fixes the floor was
            # raised for; `deps --update` pins the release instead (reconcile_floor_pins).
            return _unsatisfiable_floor(dep, why=f"floor {dep.constraint} {why}; not pinned")
        return replace(
            dep,
            status=DependencyStatus.OUTDATED,
            latest_version=installable,
            notes=(f"floor {dep.constraint} {why}",),
        )
    newest = _newest_installable(releases, python=python, ceiling=ceiling, prereleases_named=named, also=also)
    held_back = newest if newest is not None and newest != installable else None
    limit = _LOCK_LIMIT if lockable is not None else f"inside the {_COOLDOWN} cooldown"
    dropped = _python_dropped(releases, dep.proposed, python=python, also=also)
    return _hold_suggestion(
        dep, installable=installable, python=python, held_back=held_back, limit=limit, dropped=dropped
    )


def _python_dropped(releases: PypiReleases, version: str, *, python: str | None, also: tuple[str, ...]) -> str | None:
    """The first of ``also`` that ``version`` does not install on, when it installs on ``python``; else None.

    Names which Python held a floor back, so the report blames the later Python rather than the oldest.
    """
    files = releases.get(version, ())
    if not _installs_on(files, python):
        return None
    return next((p for p in also if not _installs_on(files, p)), None)


def _floor_why(
    admitted: PypiReleases,
    releases: PypiReleases,
    *,
    python: str | None,
    specifier: SpecifierSet,
    lockable: bool,
    also: tuple[str, ...] = (),
) -> str:
    if lockable and _admits_installable(admitted, python=python, specifier=specifier, also=also):
        return f"needs a release younger than the {_COOLDOWN} cooldown, so uv cannot lock it"
    if _admits_installable(releases, python=python, specifier=specifier, also=also):
        return f"is younger than the {_COOLDOWN} cooldown"
    return f"does not install on Python {_shown(python or '')}"


# How report lines name the cooldown; the actual length is the project's own exclude-newer.
_COOLDOWN = "exclude-newer"


# How a report names the limit on an exempt package whose newer releases uv cannot lock yet.
_LOCK_LIMIT = f"not lockable yet: it needs releases younger than the {_COOLDOWN} cooldown"


def _no_release_why(
    releases: PypiReleases,
    *,
    python: str | None,
    ceiling: SpecifierSet,
    prereleases_named: bool,
    lockable: Callable[[str], bool] | None,
    also: tuple[str, ...] = (),
) -> str:
    newest = _newest_installable(
        releases, python=python, ceiling=ceiling, prereleases_named=prereleases_named, also=also
    )
    if python is not None and newest is None:
        return f"no release installs on Python {_shown(python)}"
    if lockable is not None:
        return f"no release uv can lock under the {_COOLDOWN} cooldown"
    return f"no release is older than the {_COOLDOWN} cooldown"


def _keep_outdated_floor(dep: DependencyInfo, *, why: str) -> DependencyInfo:
    """An OUTDATED floor that cannot be judged is kept and reported; any other is left as it is."""
    if dep.status is not DependencyStatus.OUTDATED:
        return dep
    return replace(dep, status=DependencyStatus.ERROR, notes=(f"{why}, floor kept",))


def _unsatisfiable_floor(dep: DependencyInfo, *, why: str) -> DependencyInfo:
    """A floor nothing admitted can satisfy is an ERROR whatever it was judged before.

    ``uv lock`` fails on it, so reporting it ``[ok]`` would leave only uv's own message to explain
    a red gate; the floor is kept, since no release bmk could write would resolve either.
    """
    return replace(dep, status=DependencyStatus.ERROR, notes=(f"{why}, floor kept",), blocks_lock=True)


def _hold_suggestion(
    dep: DependencyInfo,
    *,
    installable: str,
    python: str | None,
    held_back: str | None,
    limit: str,
    dropped: str | None = None,
) -> DependencyInfo:
    """Hold an OUTDATED suggestion to ``installable``, the newest release still admitted.

    ``held_back`` is the newest release the Python alone would allow, when ``limit`` (the cooldown,
    or what uv can lock under it) is what keeps it out; None when only the Python holds.
    ``dropped`` is the later supported Python the proposed release does not install on, when that
    is what holds it rather than the oldest one.
    """
    proposed = dep.proposed
    if dep.status is not DependencyStatus.OUTDATED or installable == proposed:
        return dep
    if _version_gte(dep.current_min, installable):
        if held_back is not None:
            return replace(dep, status=DependencyStatus.UP_TO_DATE, latest_version=held_back, notes=(limit,))
        reason = (
            f"does not install on Python {_shown(dropped)}"
            if dropped
            else f"needs a newer Python than {_shown(python or '')}"
        )
        return replace(dep, status=DependencyStatus.PINNED, notes=(reason,))
    if held_back is not None:
        note = f"newest admitted; {held_back} is {limit}, absolute: {proposed}"
        return replace(dep, latest_version=installable, notes=(note,))
    label = f"newest that keeps Python {_shown(dropped)}" if dropped else f"newest for Python {_shown(python or '')}"
    return replace(dep, latest_version=installable, notes=(f"{label}, absolute: {proposed}",))


def release_policy(config: PyprojectConfig, *, now: datetime | None = None) -> ReleasePolicy:
    """The cooldown the project's ``[tool.uv]`` states, as uv itself resolves it.

    Raises:
        SupplyChainConfigError: When uv refused a stated value, or could not be asked.
    """
    uv = config.tool.uv
    stated = uv.exclude_newer is not None or bool(uv.exclude_newer_package)
    lock_options = uv_resolved_options(uv.exclude_newer, uv.exclude_newer_package) if stated else None
    return ReleasePolicy.from_project(
        exclude_newer=uv.exclude_newer,
        packages=uv.exclude_newer_package,
        lock_options=lock_options,
        now=now if now is not None else datetime.now(timezone.utc),
    )


def check_dependencies(pyproject: Path = Path("pyproject.toml")) -> list[DependencyInfo]:
    """Check all dependencies in pyproject.toml against PyPI.

    Args:
        pyproject: Path to pyproject.toml file

    Returns:
        List of DependencyInfo objects for all found dependencies.

    Raises:
        SupplyChainConfigError: When ``[tool.uv]`` states a cooldown uv would not accept.
    """
    config = load_pyproject_config(pyproject)
    support = python_support(config)
    policy = release_policy(config)
    with _one_fetch_per_package():
        return [
            _hold_exact_pin(_hold_to_supported_python(dep, support, policy))
            for dep in _extract_all_dependencies(config)
        ]


def _hold_exact_pin(dep: DependencyInfo) -> DependencyInfo:
    """Report an exact pin (``==X`` / ``===X``) that the update would move as PINNED instead.

    An exact pin names one release on purpose - a test pinned to one release's bytes, a known-good
    build - and bmk writes no ``==`` pin of its own (fleet policy, user decision 2026-10-12), so
    neither raising it to a newer release nor lowering it to one the oldest Python installs is the
    update's to decide. Checked last, so it holds whichever floor rule moved it. A wildcard
    (``==1.*``) is a range and stays movable, as ``~=`` does.
    """
    if dep.status is not DependencyStatus.OUTDATED:
        return dep
    specifier = _specifier_of(dep.original_spec)
    if specifier is None or not _exact_pin(specifier):
        return dep
    return replace(dep, status=DependencyStatus.PINNED, notes=(*dep.notes, f"exact pin {dep.constraint}"))


def _group_by_source(deps: list[DependencyInfo]) -> dict[str, list[DependencyInfo]]:
    """Index dependencies by their ``source`` (a section name), preserving order."""
    by_source: dict[str, list[DependencyInfo]] = {}
    for dep in deps:
        by_source.setdefault(dep.source, []).append(dep)
    return by_source


def _render_source_block(source: str, source_deps: list[DependencyInfo], *, verbose: bool) -> None:
    """Print one source's dependency rows, aligned; nothing when there is nothing to show.

    Non-verbose hides up-to-date rows, so a fully-current source prints no block at all.
    """
    display_deps = source_deps if verbose else [d for d in source_deps if d.status != DependencyStatus.UP_TO_DATE]
    if not display_deps:
        return

    print(f"\n{source}:")
    print("-" * len(source) + "-")

    name_width = max(len(d.name) for d in display_deps)
    constraint_width = max(len(d.constraint) for d in display_deps)
    latest_width = max(len(d.latest_display) for d in display_deps)

    for dep in sorted(display_deps, key=lambda d: d.name.lower()):
        status_icon = _get_status_icon(dep.status)
        constraint_display = dep.constraint if dep.constraint else "(any)"
        print(
            f"  {status_icon} {dep.name:<{name_width}}"
            f"  {constraint_display:<{constraint_width}}"
            f"  -> {dep.latest_display:<{latest_width}}  [{dep.status.value}]"
        )


def _print_summary(deps: list[DependencyInfo]) -> None:
    """Print the per-status tally across all dependencies."""
    count = {status: sum(1 for d in deps if d.status == status) for status in DependencyStatus}
    print(f"\nSummary: {len(deps)} dependencies checked")
    print(f"  Up-to-date: {count[DependencyStatus.UP_TO_DATE]}")
    print(f"  Pinned:     {count[DependencyStatus.PINNED]}")
    print(f"  Outdated:   {count[DependencyStatus.OUTDATED]}")
    print(f"  Unknown:    {count[DependencyStatus.UNKNOWN]}")
    print(f"  Errors:     {count[DependencyStatus.ERROR]}")


def print_report(deps: list[DependencyInfo], *, verbose: bool = False) -> int:
    """Print a formatted dependency status report.

    Args:
        deps: List of dependency info objects
        verbose: If True, show all dependencies; if False, show only outdated

    Returns:
        Exit code: 1 if any floor is outdated or makes ``uv lock`` fail, else 0
    """
    if not deps:
        print("No dependencies found in pyproject.toml")
        return 0

    for source, source_deps in sorted(_group_by_source(deps).items()):
        _render_source_block(source, source_deps, verbose=verbose)

    _print_summary(deps)

    if _check_fails(deps):
        print("\nRun with --verbose to see all dependencies")
        return 1
    return 0


def _check_fails(deps: list[DependencyInfo]) -> bool:
    """Whether the check fails: a floor is outdated, or ``uv lock`` cannot satisfy it.

    An ERROR about reading PyPI does not fail it, so an outage of the index cannot block every push.
    """
    return any(d.status == DependencyStatus.OUTDATED or d.blocks_lock for d in deps)


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


def _release_segment(version: str) -> str:
    """``version`` without its pre-, post-, dev- or local part (``8.0.post1`` -> ``8.0``)."""
    try:
        return Version(version).base_version
    except InvalidVersion:
        return version


def _replace_lower_bound(match: re.Match[str], *, latest_version: str) -> str:
    """One ``_RE_VERSION_CONSTRAINT`` match rewritten to admit ``latest_version``.

    Args:
        match: An operator plus version, as ``_RE_VERSION_CONSTRAINT`` found it.
        latest_version: The release the floor moves to, without display annotations.

    Returns:
        The rewritten constraint, or the match unchanged for an upper bound or exclusion.

    Examples:
        >>> _RE_VERSION_CONSTRAINT.sub(lambda m: _replace_lower_bound(m, latest_version="2.0"), "pkg>1.0,<3")
        'pkg>=2.0,<3'
    """
    operator = match.group(1)
    # An upper bound or exclusion is the author's ceiling, never a floor to raise.
    if operator in ("<", "<=", "!="):
        return match.group(0)
    # ">X" moved to a release must still admit it, so a strict floor is written inclusive.
    operator = ">=" if operator == ">" else operator
    if match.string.startswith(".*", match.end()):
        # A wildcard may only follow a release segment: "==8.0.post1.*" is not PEP 440.
        return f"{operator}{_release_segment(latest_version)}"
    return f"{operator}{latest_version}"


def _complete_requirement(requirement: str, updated: str, *, extras: str, latest_version: str) -> str:
    """``updated`` with a floor added when ``requirement`` had none, and its extras kept.

    Args:
        requirement: The spec before the rewrite, its environment marker removed.
        updated: ``requirement`` after ``_replace_lower_bound`` ran over it.
        extras: The ``[extra,...]`` suffix of ``requirement``, or an empty string.
        latest_version: The release the floor moves to.

    Returns:
        The requirement to write, still without its environment marker.

    Examples:
        >>> _complete_requirement("pyright[nodejs]", "pyright[nodejs]", extras="[nodejs]", latest_version="1.5")
        'pyright[nodejs]>=1.5'
    """
    if updated == requirement and not _RE_HAS_CONSTRAINT.search(requirement):
        # A bare name has nothing to rewrite, so the floor is added rather than raised.
        name_match = _RE_PACKAGE_NAME.match(requirement)
        if name_match:
            return f"{name_match.group(1)}{extras}>={latest_version}"
        return f"{requirement}>={latest_version}"
    if extras and extras not in updated:
        # A constraint written INSIDE the brackets ("pkg[a>=1]") is rewritten with the rest, so
        # the original extras are spliced back in front; the result is not valid PEP 508, and
        # update_dependencies refuses it while naming this text.
        name_match = _RE_PACKAGE_NAME.match(updated)
        if name_match:
            pkg_name = name_match.group(1)
            return f"{pkg_name}{extras}{updated[len(pkg_name) :]}"
    return updated


def _build_updated_spec(dep: DependencyInfo) -> str:
    """Build an updated dependency specification with the latest version.

    Preserves the original format (>=, ==, etc.) and any environment markers.
    """
    original = dep.original_spec
    latest_version = dep.latest_version

    # None: PyPI did not answer, so there is no release to write.
    if not original or not latest_version:
        return original

    # The marker is set aside and re-appended verbatim, so the rewrite and the extras lookup
    # see the requirement alone and nothing inside a marker is ever changed.
    marker = _marker_of(original)
    requirement = original[: original.find(";")].strip() if marker else original
    extras = _extras_of(requirement)

    updated = _RE_VERSION_CONSTRAINT.sub(
        lambda match: _replace_lower_bound(match, latest_version=latest_version), requirement
    )
    updated = _complete_requirement(requirement, updated, extras=extras, latest_version=latest_version)
    return f"{updated}{marker}"


class _UvPipListEntry(BaseModel):
    """One package of ``uv pip list --format json``.

    Strict, so only a real string counts: a number where a name belongs is no package.

    Attributes:
        name: The distribution name as installed.
        version: The installed version.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    name: str
    version: str


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
    # Entry by entry: one record uv writes in a shape bmk does not know must not hide the others.
    for entry in cast("list[object]", parsed):
        try:
            package = _UvPipListEntry.model_validate(entry)
        except ValidationError:
            continue
        versions[_normalize_name(package.name)] = package.version
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


class PendingInstall(NamedTuple):
    """One package the target environment lacks or holds below its floor.

    A NamedTuple, so the install report sorts these exactly as it sorts plain tuples: by spec name,
    then installed version.

    Attributes:
        spec_name: The package name with its extras (``pyright[nodejs]``).
        installed: The installed version; None when it is not installed.
        required: The floor it must reach.
        marker: The ``; <environment marker>`` suffix, or an empty string.
    """

    spec_name: str
    installed: str | None
    required: str
    marker: str


def _find_packages_needing_install(
    deps: list[DependencyInfo], installed_versions: dict[str, str]
) -> list[PendingInstall]:
    """Find packages that need installation or update.

    Args:
        deps: Dependencies parsed from pyproject.toml.
        installed_versions: Normalized name -> version, from the target env.

    Returns:
        One entry per package to install or update.
    """
    needs_install: list[PendingInstall] = []

    for dep in deps:
        if not dep.current_min:
            continue

        installed = installed_versions.get(_normalize_name(dep.name))
        name_with_extras = f"{dep.name}{_extras_of(dep.original_spec)}"
        marker = _marker_of(dep.original_spec)

        if installed is None or compare_versions(installed, dep.current_min) is DependencyStatus.OUTDATED:
            needs_install.append(PendingInstall(name_with_extras, installed, dep.current_min, marker))

    return needs_install


def _print_install_report(needs_install: list[PendingInstall], *, dry_run: bool) -> None:
    """Print report of packages needing installation."""
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Packages needing installation/update:\n")

    for pending in sorted(needs_install):
        status = "NOT INSTALLED" if pending.installed is None else pending.installed
        # The marker is shown because it explains an entry that will then be skipped:
        # a win32-only package always reads as NOT INSTALLED on Linux.
        print(f"  {pending.spec_name}: {status} -> >={pending.required}{pending.marker}")


@dataclass(frozen=True)
class LockedProject:
    """How :func:`main` keeps ``uv.lock`` and the project venv current; the stage wires uv in.

    Attributes:
        upgrade: Runs ``uv lock --upgrade``: every package at its newest admitted release.
        sync: Brings the project venv to the lock; True synced, False failed, None nothing to sync
            (no project venv, or ``BMK_NO_VENV_SYNC=1``).
        sync_already_failed: This run's provisioning already failed on a venv that ``sync`` would
            sync again. A lock the upgrade left byte-for-byte unchanged is then not synced again: it
            could only fail the same way and print the same report a second time. False when
            ``sync`` would do nothing (no venv), so that case still passes as it did.
        out: Where the update's failure lines go; None is the process's stderr, looked up when
            written. A JSON-mode stage passes its sink, so the reason lands in its captured output.
    """

    upgrade: Callable[[], bool]
    sync: Callable[[], bool | None]
    sync_already_failed: bool = False
    out: SupportsWrite | None = None


def _complete_block(pyproject: Path, supply_chain: SupplyChainSettings, *, quiet: bool) -> bool:
    """Write the cooldown and the own-package exemptions into ``[tool.uv]``; True when it changed.

    The caller re-locks and re-syncs on every update anyway, so it does not branch on the answer;
    the return value states what happened for a reader and a test.

    Runs before anything is locked or judged: the lock resolves under this block, and the floors
    are judged against the cutoff that lock records.
    """
    config = load_pyproject_config(pyproject)
    try:
        exempt = own_closure(
            [d.name for d in _extract_all_dependencies(config)],
            own=supply_chain.own_packages,
            requires_of=_requires_of_newest,
            project=config.project.name,
        )
    except OwnPackageUnreadableError as exc:
        print(
            f"{pyproject}: [tool.uv] left as it is: PyPI did not answer for {exc}, so the exemptions would be incomplete",
            file=sys.stderr,
        )
        return False
    changes = ensure_uv_cooldown(pyproject, cooldown=supply_chain.cooldown, exempt=exempt)
    changes += _pin_young_floors(pyproject)
    if not quiet:
        for change in changes:
            print(f"  {change}")
    return bool(changes)


def _pin_young_floors(pyproject: Path) -> list[str]:
    """Keep bmk's floor pins in ``[tool.uv]`` exactly what the declared floors need today.

    Nothing is changed when PyPI does not answer: a pin judged on missing data could be dropped
    while its floor still needs it, and ``uv lock`` would then fail on that floor.

    Raises:
        SupplyChainConfigError: When uv refuses the project's ``exclude-newer``.
    """
    config = load_pyproject_config(pyproject)
    uv = config.tool.uv
    cutoff = _default_cutoff(uv.exclude_newer)
    try:
        pins = _demanded_pins(config, cutoff, uv.exclude_newer_package)
    except _UnjudgeableError as exc:
        print(f"{pyproject}: floor pins left as they are: {exc}", file=sys.stderr)
        return []
    return reconcile_floor_pins(pyproject, pins=pins, is_floor_pin=_is_floor_pin, cutoff=cutoff)


def _default_cutoff(exclude_newer: object) -> datetime | None:
    """The cutoff the project's ``exclude-newer`` sets for a package without its own; None without one.

    A value uv refused must raise here, not read as "no cooldown": uv only warns and resolves no
    cutoff, and with none every floor pin looks undemanded, so the reconcile would drop them all
    before the check refused the value.

    Raises:
        SupplyChainConfigError: When uv refuses the value.
    """
    if exclude_newer is None:
        return None
    # from_project, not from_lock: it is the one place that refuses a value uv resolved to nothing.
    return ReleasePolicy.from_project(
        exclude_newer=exclude_newer,
        packages={},
        lock_options=uv_resolved_options(exclude_newer, {}),
        now=datetime.now(timezone.utc),
    ).default


class _DeclaredRequirement(NamedTuple):
    """One requirement the project declares, as the floor walk starts from it.

    Attributes:
        requirement: The parsed requirement.
        python: The oldest Python it applies on (``X.Y``), or None when the project states no support.
    """

    requirement: Requirement
    python: str | None


def _demanded_pins(config: PyprojectConfig, cutoff: datetime | None, packages: dict[str, Any]) -> dict[str, str]:
    """The floor pins the project's declared floors need under its default ``cutoff``.

    Raises:
        _UnjudgeableError: When a release list or a release's requirements cannot be read.
    """
    if cutoff is None:
        return {}
    exempt = frozenset(normalize(n) for n, v in packages.items() if v is False)
    kept = frozenset(normalize(n) for n, v in packages.items() if v is not False and not _is_floor_pin(normalize(n), v))
    support = python_support(config)
    demand = _FloorDemand(cutoff=cutoff, exempt=exempt, kept=kept)
    # A self-reference (`demo[cli]` in demo's own extras) is installed from the source tree: it
    # needs no pin, and for a project not on PyPI its release list cannot be read, which would
    # leave every pin unjudgeable and frozen. The extras it names are walked as declared anyway.
    own = normalize(config.project.name)
    declared: list[_DeclaredRequirement] = []
    for dep in _extract_all_dependencies(config):
        requirement = _requirement_or_none(dep.original_spec)
        if requirement is not None and normalize(requirement.name) != own:
            python = support.oldest_for(dep.original_spec) if support is not None else None
            declared.append(_DeclaredRequirement(requirement=requirement, python=python))
    return demand.resolve(declared)


def _is_floor_pin(name: str, value: object) -> bool:
    """Whether ``value`` is a pin bmk wrote: the next whole second after one file of one release.

    Any file, not only the newest: bmk pins a release at its newest file as of that day, and a file
    uploaded later (a wheel built after the sdist) must not turn bmk's own pin into what reads as the
    project's choice, which would then hold the package back for good. A timestamp the project chose
    reads as bmk's only if it falls on exactly that second after one of the package's uploads; no
    value-based rule can tell those apart, and a record kept beside the table could disagree with it.

    Raises:
        _UnjudgeableError: When the release list cannot be read.
    """
    if not isinstance(value, str):
        return False
    releases = _releases_of(name)
    if releases is None:
        raise _UnjudgeableError(f"release list of {name} unreadable")
    return any(floor_pin([entry]) == value for files in releases.values() for entry in files)


class _FloorDemand:
    """The releases a project's declared floors demand, and the pins those inside the cooldown need.

    A package needs no pin while the default cutoff shows each requirement on it a whole release to
    lock (:func:`_package_pin` says which pin otherwise). An exempt package needs no pin of its own,
    but the release it demands brings floors of its own, which are walked the same way - and so does
    a pinned release, whose own requirements can be just as young (pydantic 2.14.1 requires exactly
    pydantic-core 2.50.1, uploaded the same evening). A requirement is walked wherever ``uv lock``
    can need it: on any platform, any Python from the oldest up, and behind the extras requested.

    A pin depends on every requirement that reaches the package, and which requirements are reached
    depends on the releases walked at the pins. So :meth:`resolve` walks the whole tree at the pins of
    the previous pass and repeats until the pins stop changing; deciding as each requirement arrives
    made the result depend on walk order, and an earlier walk went stale once a later requirement
    moved the pin.

    A requirement once reached is kept for every later pass, even when the new pins no longer lead
    to it. Dropping it let a cycle oscillate (gadget's pin reaches helper, whose requirement on gadget
    moves the pin so helper is no longer reached, which moves it back), and refusing then left the
    cut release unpinned. A kept requirement the current pass did NOT reach may only TIGHTEN a pin
    (:meth:`_Need.tolerates`): one with a young floor would otherwise force a pin past the cutoff
    and let uv lock a young release no reached floor asks for. The price is a pin that may be
    stricter than the final tree strictly needs, never a looser one and never a half-visible release.
    """

    # One pass per level of a chain of young packages each reached only through the previous pin.
    _MAX_PASSES = 50

    def __init__(self, *, cutoff: datetime, exempt: frozenset[str], kept: frozenset[str]) -> None:
        self._cutoff = cutoff
        self._exempt = exempt
        self._kept = kept
        self._walked: set[_ReleaseKey] = set()
        self._needs: dict[str, dict[_NeedKey, _Need]] = {}
        self._reached: set[tuple[str, _NeedKey]] = set()
        self.pins: dict[str, str] = {}

    def resolve(self, declared: list[_DeclaredRequirement]) -> dict[str, str]:
        """The pins ``declared`` needs, walked until they settle.

        Raises:
            _UnjudgeableError: When a lookup fails, or the pins never settle (a safety net: with the
                requirements only growing, they always do).
        """
        for _ in range(self._MAX_PASSES):
            self._walked = set()
            self._reached = set()
            for entry in declared:
                self.add(entry.requirement, python=entry.python)
            pins = {
                name: pin
                for name, needs in self._needs.items()
                if (
                    pin := _package_pin(
                        [_ReachedNeed(need=need, reached=(name, key) in self._reached) for key, need in needs.items()],
                        cutoff=self._cutoff,
                    )
                )
                is not None
            }
            if pins == self.pins:
                return pins
            self.pins = pins
        raise _UnjudgeableError(f"floor pins did not settle within {self._MAX_PASSES} passes")

    def add(self, requirement: Requirement, *, python: str | None) -> None:
        name = normalize(requirement.name)
        if name in self._kept:
            return  # an override the project set itself decides this package
        releases = _releases_of(name)
        if releases is None:
            raise _UnjudgeableError(f"release list of {name} unreadable")
        extras = frozenset(requirement.extras)
        satisfying = _satisfying_releases(releases, requirement.specifier, python=python)
        if not satisfying:
            return
        if name in self._exempt:
            self._walk(name, min(satisfying, key=Version), python=python, extras=extras)
            return
        exact = _exact_pin(requirement.specifier)
        key: _NeedKey = (str(requirement.specifier), python, exact)
        need = self._needs.setdefault(name, {}).setdefault(key, _Need(releases=satisfying, python=python, exact=exact))
        self._reached.add((name, key))
        pin = self.pins.get(name)
        if pin is None:
            return
        # What uv resolves at the previous pass's pin is what this pass walks. A requirement first
        # reached in this pass may see nothing there; its pin is recomputed below and walked next pass.
        chosen = need.chosen(_as_moment(pin))
        if chosen is not None:
            self._walk(name, chosen, python=python, extras=extras)

    def _walk(self, name: str, version: str, *, python: str | None, extras: frozenset[str]) -> None:
        if (name, version, extras) in self._walked:
            return
        self._walked.add((name, version, extras))
        requires = _requires_of_release(name, version)
        if requires is None:
            raise _UnjudgeableError(f"requirements of {name} {version} unreadable")
        for requirement in requires:
            if _marker_applies(requirement, python, extras=extras):
                self.add(requirement, python=_oldest_python_applying(requirement, python, extras=extras))


def _exact_pin(specifier: SpecifierSet) -> bool:
    """Whether ``specifier`` pins one release exactly, the one case in which uv takes a yanked file."""
    return any(s.operator == "===" or (s.operator == "==" and not s.version.endswith(".*")) for s in specifier)


class _Need:
    """One requirement on a package: the releases it admits, on the Python it serves."""

    def __init__(self, *, releases: PypiReleases, python: str | None, exact: bool) -> None:
        self.releases = releases
        self.python = python
        self.exact = exact

    def chosen(self, moment: datetime) -> str | None:
        """The release uv locks for this requirement at ``moment``: the highest one a file uploaded
        before it makes visible and installable on this Python; None when there is none."""
        visible = admitted_releases(self.releases, moment)
        takeable = [v for v, files in visible.items() if _installs_on(files, self.python, yanked_ok=self.exact)]
        return max(takeable, key=Version) if takeable else None

    def settles(self, moment: datetime) -> bool:
        """Whether uv, cut off at ``moment``, locks a release for this requirement with all its files.

        Not only the release locked on the oldest Python counts: uv resolves every Python at once, so
        a higher release whose visible file installs only on a newer Python is locked there. A cut
        release BELOW the one locked on the oldest Python is never taken and does not count.
        """
        chosen = self.chosen(moment)
        return chosen is not None and not self._cut_from(chosen, moment)

    def tolerates(self, moment: datetime) -> bool:
        """The weaker test for a requirement no longer reached: it must not see a cut release it could
        lock, but it may see nothing at all - a young floor here must never force a pin forward."""
        chosen = self.chosen(moment)
        return chosen is None or not self._cut_from(chosen, moment)

    def _cut_from(self, chosen: str, moment: datetime) -> bool:
        floor = Version(chosen)
        return _cuts_at({v: f for v, f in self.releases.items() if Version(v) >= floor}, moment)


class _ReachedNeed(NamedTuple):
    """One requirement on a package, and whether the current pass of :class:`_FloorDemand` reached it.

    Attributes:
        need: The requirement.
        reached: Whether this pass reached it; one kept from an earlier pass only may hold a pin
            back, never decide one forward (see :func:`_package_pin`).
    """

    need: _Need
    reached: bool


def _package_pin(needs: list[_ReachedNeed], *, cutoff: datetime) -> str | None:
    """The pin a package needs under the default ``cutoff``, given every requirement on it; None for none.

    uv locks, per requirement, the highest release a file before the cutoff makes visible, with only
    those files: a release cut by the cutoff keeps its older files alone (pydantic-core 2.50.1 kept
    one macOS wheel of dozens) and every other platform builds from source or fails. A cut release
    no requirement would lock does not matter. So a cutoff is safe when no requirement can lock a
    cut release there (:meth:`_Need.settles`).

    No pin is needed while the default cutoff is safe. Otherwise the pin goes BACK to the latest
    safe candidate at or before the cutoff: pinning forward past a floor's own upload would admit
    young files no floor asked for (user, 2026-10-12 16:06 and 2026-10-23 21:54), and the pin goes
    once the cut release clears the cooldown. Failing that it goes FORWARD to the earliest safe
    candidate past the cutoff, where a floor release too young or itself cut is admitted whole.
    Each candidate is one second after a release's newest file, which is how bmk recognises the pin
    as its own.

    ``needs`` carries each requirement with whether this pass reached it. One not reached is not in
    the tree uv resolves; it is kept only so the passes settle (see :class:`_FloorDemand`), so it may
    hold a pin BACK (:meth:`_Need.tolerates`) but never decide one FORWARD: a forward pin admits
    young files, and only a reached requirement may ask for that.
    """
    reached = [entry.need for entry in needs if entry.reached]
    unreached = [entry.need for entry in needs if not entry.reached]

    def settles(moment: datetime) -> bool:
        return all(need.settles(moment) for need in reached)

    def safe(moment: datetime) -> bool:
        return settles(moment) and all(need.tolerates(moment) for need in unreached)

    if safe(cutoff):
        return None
    candidates = sorted(
        {pin for entry in needs for files in entry.need.releases.values() if (pin := floor_pin(files)) is not None}
    )
    back = [c for c in reversed(candidates) if _as_moment(c) <= cutoff]
    forward = [c for c in candidates if _as_moment(c) > cutoff]
    pin = next((c for c in back if safe(_as_moment(c))), None)
    if pin is not None or settles(cutoff):
        return pin  # only an unreached requirement objects to the cutoff: it decides nothing more
    pin = next((c for c in back if settles(_as_moment(c))), None)
    return pin or next((c for c in forward if settles(_as_moment(c))), None)


def _as_moment(pin: str) -> datetime:
    """A pin's timestamp as an aware datetime (pins end in ``Z``, which Python 3.10 cannot parse)."""
    return datetime.fromisoformat(pin.replace("Z", "+00:00"))


def _cuts_at(satisfying: PypiReleases, moment: datetime) -> bool:
    """Whether some release in ``satisfying`` has timed files both before and after ``moment``."""
    visible = admitted_releases(satisfying, moment)
    for version, files in satisfying.items():
        timed = sum(1 for entry in files if entry.uploaded is not None)
        if len(visible.get(version, [])) not in (0, timed):
            return True
    return False


def _satisfying_releases(
    releases: PypiReleases, specifier: SpecifierSet, *, python: str | None
) -> dict[str, tuple[PypiFile, ...]]:
    """The releases ``specifier`` admits that uv would take on ``python``: a file installing there,
    and not only yanked ones (a yanked one counts under an exact pin)."""
    exact = _exact_pin(specifier)
    return {
        version: files
        for version, files in releases.items()
        if _is_version(version)
        and specifier.contains(version, prereleases=bool(specifier.prereleases))
        and _installs_on(files, python, yanked_ok=exact)
    }


def _upgrade_and_sync(locked: LockedProject, pyproject: Path) -> int:
    """Re-lock at the newest admitted releases, then bring the venv to that lock.

    Runs whether or not a floor moved: a transitive package can move inside an unchanged manifest,
    and the gates after this stage must test exactly what the lock pins. The one exception is a
    sync this run already saw fail on a lock the upgrade did not change: retrying it repeats the
    same failure and its report, so one line points back at the first report instead.
    """
    lock_file = pyproject.parent / "uv.lock"
    before = _read_bytes(lock_file)
    if not locked.upgrade():
        _say(f"{pyproject.parent}: uv lock --upgrade failed after the floor update", locked.out)
        return 1
    if locked.sync_already_failed and _read_bytes(lock_file) == before:
        _say(
            f"{pyproject.parent}: venv provisioning already failed above; uv.lock unchanged by the update, not retrying",
            locked.out,
        )
        return 1
    if locked.sync() is False:
        _say(f"{pyproject.parent}: uv sync from uv.lock failed after the floor update", locked.out)
        return 1
    return 0


def _read_bytes(path: Path) -> bytes | None:
    """``path``'s bytes; None when it cannot be read (absent counts as unchanged if it stays absent)."""
    try:
        return path.read_bytes()
    except OSError:
        return None


def _say(line: str, out: SupportsWrite | None) -> None:
    """Write one line to ``out``, or to the process's stderr (looked up now) when None.

    ONE write, newline included, like the venv reports: stderr is shared with whatever runs in
    parallel (``push`` runs ``test`` beside ``build``), and a line written as text and newline in
    two calls can be split by theirs.
    """
    (sys.stderr if out is None else out).write(line + "\n")


def _requires_of_newest(package_name: str) -> list[str] | None:
    """The requirement strings of a package's newest release on PyPI; None when PyPI did not answer."""
    data = _fetch_pypi_data(package_name)
    if data is None or data.info is None:
        return None
    return list(data.info.requires_dist)


def _run_pip_install(needs_install: list[PendingInstall], python: str, *, project_dir: Path | None = None) -> int:
    """Install packages into ``python``'s environment.

    Installs into the *explicitly passed* interpreter (the project's venv), never
    into ``sys.executable``. bmk's helpers run in-process, so ``sys.executable``
    is whatever launched bmk - a shared editor venv, or even a system Python -
    and installing there lets any project silently inflate an environment it does
    not own.

    Uses ``uv pip install --python``, matching how bmk targets every other
    interpreter (see ``tools.ensure_audit_pip_argv``). Because the target is an
    explicit venv, no PEP 668 override is needed or wanted.

    It runs in ``project_dir`` because ``--upgrade`` takes the newest release, and uv
    holds that to the project's ``[tool.uv]`` cooldown only when it reads the project's
    own configuration, which it finds from the working directory.

    Returns:
        uv exit code
    """
    argv = ["uv", "pip", "install", "--python", python, "--upgrade"]
    # The marker must follow the version, not the name: "pkg>=1; sys_platform == 'win32'"
    # is a valid PEP 508 requirement, "pkg; sys_platform == 'win32'>=1" is not.
    argv.extend(f"{p.spec_name}>={p.required}{p.marker}" for p in needs_install)

    try:
        return subprocess.run(argv, check=False, cwd=project_dir).returncode
    except OSError:
        print("uv not found on PATH; cannot install dependencies", file=sys.stderr)
        return 1


class SyncOutcome(NamedTuple):
    """What :func:`sync_installed_packages` found and did.

    Attributes:
        pending: How many packages the environment did not meet the floor of.
        exit_code: The install's exit code; 0 when nothing was installed (none pending, or a dry run).
    """

    pending: int
    exit_code: int


def sync_installed_packages(
    deps: list[DependencyInfo],
    *,
    python: str,
    dry_run: bool = False,
    quiet: bool = False,
    project_dir: Path | None = None,
) -> SyncOutcome:
    """Ensure packages installed in ``python``'s env match pyproject.toml.

    Compares each dependency's required minimum against the version installed in
    the *target* environment and installs there if updates are needed.

    Args:
        deps: List of dependency info objects from check_dependencies
        python: Interpreter whose environment is inspected and installed into
        dry_run: If True, only show what would be installed without installing
        quiet: Suppress informational output
        project_dir: The project whose ``[tool.uv]`` cooldown the install must honour.

    Returns:
        How many packages needed updating, and the exit code of the install.
        The exit code is reported rather than swallowed so a failed install
        cannot be mistaken for a successful sync.
    """
    needs_install = _find_packages_needing_install(deps, _installed_versions(python))

    if not needs_install:
        if not quiet:
            print("\nAll installed packages match pyproject.toml requirements!")
        return SyncOutcome(pending=0, exit_code=0)

    if not quiet:
        _print_install_report(needs_install, dry_run=dry_run)

    if dry_run:
        if not quiet:
            print(f"\n[DRY RUN] Would install/update {len(needs_install)} packages")
        return SyncOutcome(pending=len(needs_install), exit_code=0)

    if not quiet:
        print("\nInstalling/updating packages...")
    exit_code = _run_pip_install(needs_install, python, project_dir=project_dir)

    if exit_code == 0:
        if not quiet:
            print(f"\nSuccessfully installed/updated {len(needs_install)} packages")
    else:
        print(f"\ninstall failed with exit code {exit_code}", file=sys.stderr)

    return SyncOutcome(pending=len(needs_install), exit_code=exit_code)


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
        if _apply_update(document, dep, quiet=quiet):
            updated_count += 1

    _finish_update(document, pyproject, updated_count=updated_count, dry_run=dry_run, quiet=quiet)
    return updated_count


def _apply_update(document: MutableMapping[str, Any], dep: DependencyInfo, *, quiet: bool) -> bool:
    """Rewrite ``dep``'s spec to its latest version inside ``document``, in place.

    Args:
        document: The parsed pyproject.toml, edited in memory only.
        dep: An outdated dependency.
        quiet: Suppress the per-dependency progress lines on stdout.

    Returns:
        True when the spec was found and replaced; False when it was skipped.
    """
    if not dep.original_spec:
        return False

    new_spec = _build_updated_spec(dep)
    if new_spec == dep.original_spec:
        return False
    if _specifier_of(new_spec) is None:
        # The rewriter reads normalized PEP 440 spellings; on any other ("1.0c1", "1.0RC1") it
        # can splice the new version into the old suffix. Never write that, whatever the cause:
        # the dependency stays outdated, so the gate stays red and names the spec to fix.
        # Printed even under quiet: it is the only explanation of that red gate.
        print(
            f"  {dep.name}: {dep.original_spec} -> {new_spec} is not a valid requirement, not written",
            file=sys.stderr,
        )
        return False

    if _replace_spec(document, dep.original_spec, new_spec):
        if not quiet:
            print(f"  {dep.name}: {dep.original_spec} -> {new_spec}")
        return True
    if not quiet:
        print(f"  {dep.name}: Could not locate in file (manual update needed)")
    return False


def _finish_update(
    document: MutableMapping[str, Any], pyproject: Path, *, updated_count: int, dry_run: bool, quiet: bool
) -> None:
    """Write ``document`` back unless this is a dry run, and report the outcome.

    Args:
        document: The parsed pyproject.toml carrying every replaced spec.
        pyproject: Where ``document`` came from and is written back to.
        updated_count: How many specs ``_apply_update`` replaced.
        dry_run: Report what would change without writing the file.
        quiet: Suppress the summary line on stdout.
    """
    if updated_count <= 0:
        if not quiet:
            print("\nNo dependencies were updated")
        return
    if dry_run:
        if not quiet:
            print(f"\n[DRY RUN] Would update {updated_count} dependencies")
        return
    pyproject.write_text(_typed_tomlkit.dumps(document), encoding="utf-8")
    if not quiet:
        print(f"\nUpdated {updated_count} dependencies in {pyproject}")


def main(
    *,
    verbose: bool = False,
    update: bool = False,
    dry_run: bool = False,
    quiet: bool = False,
    pyproject: Path = Path("pyproject.toml"),
    python: str | None = None,
    supply_chain: SupplyChainSettings | None = None,
    locked: LockedProject | None = None,
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
        supply_chain: With ``update``, the cooldown and own packages to keep in the
            project's ``[tool.uv]`` before any floor is judged. None leaves the block alone.
        locked: With ``update``, re-locks at the newest admitted releases after the floors are
            judged and syncs the venv from that lock, instead of installing floors into it.

    Returns:
        Exit code (0 if all up-to-date or the update succeeded, non-zero if any
        dependency is outdated, an install failed or ``[tool.uv]`` states a cooldown
        uv would refuse)
    """
    if not quiet:
        print(f"Checking dependencies in {pyproject}...")
    try:
        with _one_fetch_per_package():
            if update and not dry_run and supply_chain is not None:
                _complete_block(pyproject, supply_chain, quiet=quiet)
            deps = check_dependencies(pyproject)
    except SupplyChainConfigError as exc:
        # Into the stage's capture when deps_update runs as a JSON-mode stage, so its failed block
        # says why instead of reading '(no output captured)'.
        _say(f"{pyproject}: {exc}", locked.out if locked is not None else None)
        return 1
    exit_code = int(_check_fails(deps)) if quiet else print_report(deps, verbose=verbose)

    if update:
        # Update pyproject.toml with latest versions
        updated = update_dependencies(deps, pyproject, dry_run=dry_run, quiet=quiet)

        if locked is not None:
            return 0 if dry_run else _upgrade_and_sync(locked, pyproject)

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
        outcome = sync_installed_packages(
            deps, python=python, dry_run=dry_run, quiet=quiet, project_dir=pyproject.parent
        )
        return outcome.exit_code

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
    from bmk.adapters.stagerunner.venv import (
        desired_python_minor,
        ensure_project_venv_at,
        is_venv,
        lock_project_reporting,
        resolve_project_venv,
        venv_python,
        venv_sync_disabled,
    )

    args, _unknown = parser.parse_known_args()
    pyproject = args.project_dir / "pyproject.toml"
    quiet = read_tool_output_format() is not ToolOutputFormat.TEXT

    # Same rule as the stage path: install only into the project's own venv, synced from the lock.
    project_venv = resolve_project_venv(args.project_dir, os.environ)
    target = str(venv_python(project_venv)) if is_venv(project_venv) else None

    def _sync() -> bool | None:
        if venv_sync_disabled(os.environ) or not is_venv(project_venv):
            return None
        minor = desired_python_minor(args.project_dir)
        return ensure_project_venv_at(args.project_dir, project_venv, minor, quiet=quiet) is not None

    locked = LockedProject(
        upgrade=lambda: lock_project_reporting(args.project_dir, quiet=quiet, upgrade=True, stream=None),
        sync=_sync,
    )

    sys.exit(
        main(
            verbose=args.verbose,
            update=args.update,
            dry_run=args.dry_run,
            quiet=quiet,
            pyproject=pyproject,
            python=target,
            locked=locked,
        )
    )
