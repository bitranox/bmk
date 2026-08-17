"""PEP 440 rules for a project's own version.

Purpose
-------
Two questions, both pure, both answered here so the release gate, the bump helper and
the plugin-version sync cannot drift apart on them:

* **Will bmk act on this version?** (:func:`version_problem`, :func:`parse_project_version`)
  Any canonical PEP 440 version - wider than ``X.Y.Z``, because hatchling builds
  ``pkg-1.2.3rc1.tar.gz`` and PyPI accepts it, so bmk refusing it helped nobody.
* **What does a bump produce from it?** (:func:`next_version`) A plain three-part release.

Why "canonical" and not merely "parseable"
------------------------------------------
``packaging`` accepts more spellings than it round-trips. ``Version("v1.0.0")`` parses
and normalises to ``1.0.0``; ``Version("1.0.0-beta")`` becomes ``1.0.0b0``. Accepting a
raw spelling that normalises to something else breaks two things silently:

* ``_release.py`` builds its tag as ``f"v{version}"``, so a ``v``-prefixed version tags
  ``vv1.0.0``;
* hatchling names the artifact from the NORMALISED version, so the git tag and the file
  on PyPI would disagree.

Requiring ``str(Version(raw)) == raw`` costs nothing for a version already written the
normal way and refuses the ambiguous ones with the canonical spelling in the message.

System Role
-----------
Domain layer: pure value logic, no I/O. ``packaging.version`` is a third-party value
type with no side effects; the import-linter contracts forbid the domain importing
``bmk.adapters`` / ``bmk.composition``, not third-party packages.
"""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

from bmk.domain.enums import BumpPart
from bmk.domain.errors import InvalidProjectVersionError

__all__ = ["next_version", "parse_project_version", "version_problem"]

#: major.minor.patch. A bump is defined on exactly these three.
_RELEASE_PARTS = 3


def version_problem(raw: str) -> str | None:
    """Return why bmk will not act on ``raw``, or None when it will.

    Args:
        raw: The ``[project].version`` string as written in pyproject.toml.

    Returns:
        A message naming the problem and, where there is one, the fix - or None.

    Example:
        >>> version_problem("1.2.3rc1") is None
        True
        >>> version_problem("v1.0.0")
        '"v1.0.0" is not a canonical PEP 440 version; write it as "1.0.0"'
        >>> version_problem("nope")
        '"nope" is not a PEP 440 version'
    """
    if not raw.strip():
        return "no version found"
    try:
        parsed = Version(raw)
    except InvalidVersion:
        return f'"{raw}" is not a PEP 440 version'
    canonical = str(parsed)
    if canonical != raw:
        return f'"{raw}" is not a canonical PEP 440 version; write it as "{canonical}"'
    if parsed.local is not None:
        return f'"{raw}" carries a local version segment, which PyPI rejects on upload'
    return None


def parse_project_version(raw: str) -> Version:
    """Return ``raw`` parsed, or raise if bmk will not act on it.

    Args:
        raw: The ``[project].version`` string as written in pyproject.toml.

    Returns:
        The parsed version.

    Raises:
        InvalidProjectVersionError: With the reason from :func:`version_problem`.

    Example:
        >>> str(parse_project_version("1.2.3rc1"))
        '1.2.3rc1'
    """
    problem = version_problem(raw)
    if problem is not None:
        raise InvalidProjectVersionError(problem)
    return Version(raw)


def _release_triple(parsed: Version, raw: str) -> tuple[int, int, int]:
    """Return ``parsed``'s release segment as exactly three components.

    A shorter segment is padded (``1.0`` means ``1.0.0``). A longer one is refused
    rather than truncated: dropping the ``.4`` of ``1.2.3.4`` would lose data, and a
    bump is defined on three components only.

    Raises:
        InvalidProjectVersionError: If the release segment has more than three parts.
    """
    release = parsed.release
    if len(release) > _RELEASE_PARTS:
        msg = (
            f'"{raw}" has a {len(release)}-part release segment; bump advances '
            "major.minor.patch only, and dropping the rest would lose data"
        )
        raise InvalidProjectVersionError(msg)
    padded = (*release, 0, 0)[:_RELEASE_PARTS]
    return padded[0], padded[1], padded[2]


def _advance(triple: tuple[int, int, int], part: BumpPart, *, non_final: bool) -> tuple[int, int, int]:
    """Return the next release triple.

    A non-final version is FINALIZED rather than stepped past, whenever the requested
    part leaves the components below it at zero. That keeps the release an rc was
    rehearsing reachable: without it, ``1.2.3rc1`` could only ever become ``1.2.4`` and
    ``1.2.3`` would never be published.
    """
    major, minor, patch = triple
    if part is BumpPart.MAJOR:
        return (major, 0, 0) if non_final and minor == 0 and patch == 0 else (major + 1, 0, 0)
    if part is BumpPart.MINOR:
        return (major, minor, 0) if non_final and patch == 0 else (major, minor + 1, 0)
    return triple if non_final else (major, minor, patch + 1)


def next_version(current: str, part: BumpPart) -> str:
    """Return the version a bump of ``part`` produces from ``current``.

    The epoch survives; any pre-release, dev, post or local segment is dropped, because
    a bump always lands on a plain release.

    Args:
        current: The current ``[project].version``.
        part: Which component to advance.

    Returns:
        The new version string.

    Raises:
        InvalidProjectVersionError: If ``current`` is one bmk will not act on, or its
            release segment has more than three parts.

    Example:
        >>> next_version("1.2.3", BumpPart.PATCH)
        '1.2.4'
        >>> next_version("1.2.3rc1", BumpPart.PATCH)
        '1.2.3'
        >>> next_version("1.2.3.post1", BumpPart.PATCH)
        '1.2.4'
        >>> next_version("1!2.0.0", BumpPart.PATCH)
        '1!2.0.1'
    """
    parsed = parse_project_version(current)
    # is_prerelease covers a dev release as well as a/b/rc; a POST release is final.
    major, minor, patch = _advance(_release_triple(parsed, current), part, non_final=parsed.is_prerelease)
    epoch = f"{parsed.epoch}!" if parsed.epoch else ""
    return f"{epoch}{major}.{minor}.{patch}"
