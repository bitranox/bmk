"""Tests for the daily bmk upgrade check.

Contract: at most once a day, ask PyPI for the latest bmk; if it is newer, delete
the install stamp so the next `make` rebuilds the tool env. It must never raise
and never fail a build.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bmk.adapters.stagerunner.selfupgrade import (
    CHECK_INTERVAL_SECONDS,
    CHECK_MARKER_NAME,
    STAMP_NAME,
    TOOL_DIR_NAME,
    check_for_upgrade,
)

_LATEST = "bmk.adapters.stagerunner.selfupgrade.fetch_latest_version"
_INSTALLED = "bmk.adapters.stagerunner.selfupgrade._installed_version"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project whose Makefile-managed tool env already exists."""
    tool_dir = tmp_path / TOOL_DIR_NAME
    tool_dir.mkdir()
    (tool_dir / STAMP_NAME).write_text("")
    return tmp_path


def _stamp(project: Path) -> Path:
    return project / TOOL_DIR_NAME / STAMP_NAME


# --- the upgrade path -------------------------------------------------------


@pytest.mark.os_agnostic
def test_newer_version_invalidates_the_stamp(project: Path) -> None:
    """A newer release deletes the stamp so the next make reinstalls."""
    with patch(_INSTALLED, "1.0.0"), patch(_LATEST, return_value="2.0.0"):
        result = check_for_upgrade(project, env={})

    assert result == "2.0.0"
    assert not _stamp(project).exists()


@pytest.mark.os_agnostic
def test_same_version_leaves_the_stamp(project: Path) -> None:
    """Up to date: nothing is rebuilt."""
    with patch(_INSTALLED, "2.0.0"), patch(_LATEST, return_value="2.0.0"):
        assert check_for_upgrade(project, env={}) is None
    assert _stamp(project).exists()


@pytest.mark.os_agnostic
def test_older_pypi_version_leaves_the_stamp(project: Path) -> None:
    """A locally-built newer bmk is not downgraded."""
    with patch(_INSTALLED, "9.9.9"), patch(_LATEST, return_value="2.0.0"):
        assert check_for_upgrade(project, env={}) is None
    assert _stamp(project).exists()


# --- rate limiting ----------------------------------------------------------


@pytest.mark.os_agnostic
def test_checks_at_most_once_a_day(project: Path) -> None:
    """A recent check short-circuits before any network call."""
    (project / TOOL_DIR_NAME / CHECK_MARKER_NAME).write_text("")

    with patch(_INSTALLED, "1.0.0"), patch(_LATEST) as fetch:
        assert check_for_upgrade(project, env={}) is None

    fetch.assert_not_called()
    assert _stamp(project).exists()


@pytest.mark.os_agnostic
def test_checks_again_once_the_interval_has_passed(project: Path) -> None:
    """An old marker lets the next check through."""
    (project / TOOL_DIR_NAME / CHECK_MARKER_NAME).write_text("")
    later = Path(project / TOOL_DIR_NAME / CHECK_MARKER_NAME).stat().st_mtime + CHECK_INTERVAL_SECONDS + 1

    with patch(_INSTALLED, "1.0.0"), patch(_LATEST, return_value="2.0.0"):
        assert check_for_upgrade(project, env={}, now=later) == "2.0.0"


@pytest.mark.os_agnostic
def test_a_failed_check_still_marks_the_attempt(project: Path) -> None:
    """A network failure must not retry on every single make."""
    with patch(_INSTALLED, "1.0.0"), patch(_LATEST, side_effect=OSError("no network")):
        assert check_for_upgrade(project, env={}) is None

    assert (project / TOOL_DIR_NAME / CHECK_MARKER_NAME).exists(), "the attempt must be recorded"


# --- it must never break a build --------------------------------------------


@pytest.mark.os_agnostic
def test_network_failure_is_silent(project: Path) -> None:
    """PyPI unreachable: return quietly, leave the env alone."""
    with patch(_INSTALLED, "1.0.0"), patch(_LATEST, side_effect=OSError("boom")):
        assert check_for_upgrade(project, env={}) is None
    assert _stamp(project).exists()


@pytest.mark.os_agnostic
def test_unparseable_response_is_silent(project: Path) -> None:
    """No version in the response: do nothing."""
    with patch(_INSTALLED, "1.0.0"), patch(_LATEST, return_value=""):
        assert check_for_upgrade(project, env={}) is None
    assert _stamp(project).exists()


@pytest.mark.os_agnostic
def test_no_tool_dir_is_a_noop(tmp_path: Path) -> None:
    """A project not managed by the bmk Makefile is left alone, with no network call."""
    with patch(_LATEST) as fetch:
        assert check_for_upgrade(tmp_path, env={}) is None
    fetch.assert_not_called()


@pytest.mark.os_agnostic
def test_opt_out_skips_the_check(project: Path) -> None:
    """BMK_NO_UPGRADE_CHECK=1 never contacts PyPI."""
    with patch(_LATEST) as fetch:
        assert check_for_upgrade(project, env={"BMK_NO_UPGRADE_CHECK": "1"}) is None
    fetch.assert_not_called()
    assert _stamp(project).exists()


@pytest.mark.os_agnostic
def test_missing_stamp_does_not_raise(project: Path) -> None:
    """Someone already removed the stamp: still fine."""
    _stamp(project).unlink()

    with patch(_INSTALLED, "1.0.0"), patch(_LATEST, return_value="2.0.0"):
        assert check_for_upgrade(project, env={}) == "2.0.0"
