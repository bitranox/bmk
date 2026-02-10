"""Behaviour tests for makescripts._release: semver validation, default remote, command existence."""

from __future__ import annotations

import pytest

from bmk.makescripts._release import _cmd_exists, _get_default_remote, _looks_like_semver
from bmk.makescripts._toml_config import PyprojectConfig

# ---------------------------------------------------------------------------
# _looks_like_semver
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_looks_like_semver_accepts_stable_version() -> None:
    """Standard X.Y.Z version strings are accepted."""
    assert _looks_like_semver("1.0.0") is True


@pytest.mark.os_agnostic
def test_looks_like_semver_accepts_zero_minor() -> None:
    """Version with zero minor component is accepted."""
    assert _looks_like_semver("0.1.0") is True


@pytest.mark.os_agnostic
def test_looks_like_semver_accepts_large_numbers() -> None:
    """Multi-digit version components are accepted."""
    assert _looks_like_semver("10.20.30") is True


@pytest.mark.os_agnostic
def test_looks_like_semver_rejects_two_part_version() -> None:
    """Two-part version string is rejected."""
    assert _looks_like_semver("1.0") is False


@pytest.mark.os_agnostic
def test_looks_like_semver_rejects_v_prefix() -> None:
    """Version with 'v' prefix is rejected."""
    assert _looks_like_semver("v1.0.0") is False


@pytest.mark.os_agnostic
def test_looks_like_semver_rejects_prerelease_suffix() -> None:
    """Version with prerelease suffix is rejected."""
    assert _looks_like_semver("1.0.0-beta") is False


@pytest.mark.os_agnostic
def test_looks_like_semver_rejects_alphabetic_string() -> None:
    """Non-numeric string is rejected."""
    assert _looks_like_semver("abc") is False


@pytest.mark.os_agnostic
def test_looks_like_semver_rejects_empty_string() -> None:
    """Empty string is rejected."""
    assert _looks_like_semver("") is False


# ---------------------------------------------------------------------------
# _get_default_remote
# ---------------------------------------------------------------------------


def _make_config(raw_data: dict) -> PyprojectConfig:
    """Build a PyprojectConfig with the given raw_data dict."""
    return PyprojectConfig.from_dict(raw_data)


@pytest.mark.os_agnostic
def test_get_default_remote_returns_origin_when_no_tool_section() -> None:
    """Falls back to 'origin' when [tool] section is absent."""
    config = _make_config({"project": {"name": "test", "version": "1.0.0"}})

    assert _get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_returns_origin_when_no_git_section() -> None:
    """Falls back to 'origin' when [tool.git] section is absent."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"clean": {"patterns": []}},
        }
    )

    assert _get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_returns_configured_remote() -> None:
    """Returns configured remote when tool.git.default-remote is set."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": "upstream"}},
        }
    )

    assert _get_default_remote(config) == "upstream"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_non_dict_tool_value() -> None:
    """Falls back to 'origin' when tool value is not a dict."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": "not-a-dict",
        }
    )

    assert _get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_non_dict_git_value() -> None:
    """Falls back to 'origin' when tool.git value is not a dict."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": "not-a-dict"},
        }
    )

    assert _get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_non_string_remote_value() -> None:
    """Falls back to 'origin' when default-remote is not a string."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": 42}},
        }
    )

    assert _get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_empty_string_remote() -> None:
    """Falls back to 'origin' when default-remote is an empty string."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": ""}},
        }
    )

    assert _get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_whitespace_only_remote() -> None:
    """Falls back to 'origin' when default-remote is whitespace only."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": "   "}},
        }
    )

    assert _get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_strips_whitespace_from_remote() -> None:
    """Strips surrounding whitespace from a valid remote name."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": "  upstream  "}},
        }
    )

    assert _get_default_remote(config) == "upstream"


# ---------------------------------------------------------------------------
# _cmd_exists
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cmd_exists_returns_true_for_python3() -> None:
    """python3 is always available in the test environment."""
    assert _cmd_exists("python3") is True


@pytest.mark.os_agnostic
def test_cmd_exists_returns_false_for_nonexistent_command() -> None:
    """A clearly nonexistent command returns False."""
    assert _cmd_exists("nonexistent_command_xyz_12345") is False
