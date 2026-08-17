"""Unit tests for the PEP 440 project-version rules in ``bmk.domain.version``.

Two rules are under test and they are easy to conflate:

* what bmk will ACCEPT as a project version (``version_problem`` /
  ``parse_project_version``) - any canonical PEP 440 version, which is wider than
  ``X.Y.Z`` but narrower than "whatever ``packaging`` parses";
* what a bump PRODUCES from one (``next_version``) - a plain three-part release,
  finalizing a non-final version rather than stepping past it.
"""

from __future__ import annotations

import re

import pytest

from bmk.domain.enums import BumpPart
from bmk.domain.errors import InvalidProjectVersionError
from bmk.domain.version import next_version, parse_project_version, version_problem

# ---------------------------------------------------------------------------
# What bmk accepts
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "raw",
    [
        "1.2.3",  # the ordinary case
        "0.1.0rc1",  # the pre-release that used to be refused outright
        "1.0.0a1",
        "1.3.0b2",
        "1.2.3.dev4",
        "1.2.3.post1",
        "1.0",  # PEP 440 does not require three components
        "1.2.3.4",
        "1!2.0.0",  # epoch
        "10.20.30",
    ],
)
def test_a_canonical_pep440_version_is_accepted(raw: str) -> None:
    assert version_problem(raw) is None
    assert str(parse_project_version(raw)) == raw


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("v1.0.0", "1.0.0"),  # accepted by packaging; would tag vv1.0.0
        ("1.0.0-beta", "1.0.0b0"),
        ("1.2.3RC1", "1.2.3rc1"),
        ("1.2.3-rc1", "1.2.3rc1"),
    ],
)
def test_a_respelled_version_is_refused_and_the_message_names_the_canonical_form(raw: str, canonical: str) -> None:
    # packaging PARSES all of these, so accepting them would silently disagree with the
    # artifact hatchling builds - and the v-prefix would tag vv1.0.0.
    problem = version_problem(raw)

    assert problem is not None
    assert canonical in problem
    with pytest.raises(InvalidProjectVersionError, match=re.escape(canonical)):
        parse_project_version(raw)


@pytest.mark.os_agnostic
def test_a_local_version_is_refused_because_pypi_rejects_it() -> None:
    problem = version_problem("1.2.3+local")

    assert problem is not None
    assert "local" in problem.lower()


@pytest.mark.os_agnostic
@pytest.mark.parametrize("raw", ["abc", "", "   ", "not-a-version"])
def test_a_string_that_is_not_a_version_at_all_is_refused(raw: str) -> None:
    assert version_problem(raw) is not None
    with pytest.raises(InvalidProjectVersionError):
        parse_project_version(raw)


# ---------------------------------------------------------------------------
# What a bump produces
# ---------------------------------------------------------------------------

#: The agreed rule, as a table. A non-final version (pre-release or dev release) is
#: FINALIZED rather than stepped past, so the release an rc was rehearsing stays
#: reachable. A post-release is final, so it increments normally.
_BUMP_TABLE: tuple[tuple[str, str, str, str], ...] = (
    # current        patch      minor      major
    ("1.2.3", "1.2.4", "1.3.0", "2.0.0"),
    ("1.2.3rc1", "1.2.3", "1.3.0", "2.0.0"),
    ("1.3.0b2", "1.3.0", "1.3.0", "2.0.0"),
    ("1.2.3.dev4", "1.2.3", "1.3.0", "2.0.0"),
    ("1.2.3.post1", "1.2.4", "1.3.0", "2.0.0"),
    ("2.0.0rc1", "2.0.0", "2.0.0", "2.0.0"),
)


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("current", "patch", "minor", "major"), _BUMP_TABLE)
def test_the_bump_table_holds(current: str, patch: str, minor: str, major: str) -> None:
    assert next_version(current, BumpPart.PATCH) == patch
    assert next_version(current, BumpPart.MINOR) == minor
    assert next_version(current, BumpPart.MAJOR) == major


@pytest.mark.os_agnostic
def test_a_short_release_segment_is_padded_rather_than_refused() -> None:
    # "1.0" is a legal PEP 440 version; bumping it means bumping 1.0.0.
    assert next_version("1.0", BumpPart.PATCH) == "1.0.1"


@pytest.mark.os_agnostic
def test_an_epoch_survives_a_bump() -> None:
    assert next_version("1!2.0.0", BumpPart.PATCH) == "1!2.0.1"


@pytest.mark.os_agnostic
def test_a_release_segment_longer_than_three_is_refused_rather_than_truncated() -> None:
    # Silently dropping the ".4" would lose data, and bump is a three-part operation.
    with pytest.raises(InvalidProjectVersionError, match=re.escape("1.2.3.4")):
        next_version("1.2.3.4", BumpPart.PATCH)


@pytest.mark.os_agnostic
def test_bumping_a_version_bmk_would_not_accept_is_refused() -> None:
    with pytest.raises(InvalidProjectVersionError):
        next_version("v1.0.0", BumpPart.PATCH)
