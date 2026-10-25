"""Behaviour tests for makescripts._release: version validation, default remote, command existence."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from fakes import fake_of

from bmk.adapters.stagerunner.helpers import _release
from bmk.adapters.stagerunner.helpers._release import cmd_exists, get_default_remote
from bmk.adapters.stagerunner.helpers._toml_config import PyprojectConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import CaptureFixture

# The version rules themselves are owned by bmk.domain.version and tested in
# tests/test_domain_version.py. What is tested HERE is that release() consults them and
# stops before tagging - see TestReleaseOrchestrator at the bottom of this file.


# ---------------------------------------------------------------------------
# get_default_remote
# ---------------------------------------------------------------------------


def _make_config(data: dict[str, Any]) -> PyprojectConfig:
    """Build a PyprojectConfig from a parsed pyproject document."""
    return PyprojectConfig.from_dict(data)


@pytest.mark.os_agnostic
def test_get_default_remote_returns_origin_when_no_tool_section() -> None:
    """Falls back to 'origin' when [tool] section is absent."""
    config = _make_config({"project": {"name": "test", "version": "1.0.0"}})

    assert get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_returns_origin_when_no_git_section() -> None:
    """Falls back to 'origin' when [tool.git] section is absent."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"clean": {"patterns": []}},
        }
    )

    assert get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_returns_configured_remote() -> None:
    """Returns configured remote when tool.git.default-remote is set."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": "upstream"}},
        }
    )

    assert get_default_remote(config) == "upstream"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_non_dict_tool_value() -> None:
    """Falls back to 'origin' when tool value is not a dict."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": "not-a-dict",
        }
    )

    assert get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_non_dict_git_value() -> None:
    """Falls back to 'origin' when tool.git value is not a dict."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": "not-a-dict"},
        }
    )

    assert get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_non_string_remote_value() -> None:
    """Falls back to 'origin' when default-remote is not a string."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": 42}},
        }
    )

    assert get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_empty_string_remote() -> None:
    """Falls back to 'origin' when default-remote is an empty string."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": ""}},
        }
    )

    assert get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_handles_whitespace_only_remote() -> None:
    """Falls back to 'origin' when default-remote is whitespace only."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": "   "}},
        }
    )

    assert get_default_remote(config) == "origin"


@pytest.mark.os_agnostic
def test_get_default_remote_strips_whitespace_from_remote() -> None:
    """Strips surrounding whitespace from a valid remote name."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {"git": {"default-remote": "  upstream  "}},
        }
    )

    assert get_default_remote(config) == "upstream"


# ---------------------------------------------------------------------------
# cmd_exists
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cmd_exists_returns_true_for_python3() -> None:
    """python3 is always available in the test environment."""
    assert cmd_exists("python3") is True


@pytest.mark.os_agnostic
def test_cmd_exists_returns_false_for_nonexistent_command() -> None:
    """A clearly nonexistent command returns False."""
    assert cmd_exists("nonexistent_command_xyz_12345") is False


# ---------------------------------------------------------------------------
# ensure_clean
# ---------------------------------------------------------------------------


class TestEnsureClean:
    """Tests for ensure_clean function."""

    @pytest.mark.os_agnostic
    def test_passes_on_clean_tree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No error when both diff commands return 0."""
        clean: subprocess.CompletedProcess[str] = subprocess.CompletedProcess([], 0)
        monkeypatch.setattr(_release, "run", fake_of(_release.run).returning(clean))

        _release.ensure_clean()  # Should not raise

    @pytest.mark.os_agnostic
    def test_raises_on_unstaged_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SystemExit when unstaged changes are detected."""
        results: Iterator[subprocess.CompletedProcess[str]] = iter(
            [
                subprocess.CompletedProcess[str]([], 1),  # unstaged = dirty
                subprocess.CompletedProcess[str]([], 0),  # staged = clean
            ]
        )

        def run_next(
            _args: list[str], *, check: bool = True, capture: bool = False
        ) -> subprocess.CompletedProcess[str]:
            return next(results)

        monkeypatch.setattr(_release, "run", run_next)

        with pytest.raises(SystemExit):
            _release.ensure_clean()

    @pytest.mark.os_agnostic
    def test_raises_on_staged_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SystemExit when staged changes are detected."""
        results: Iterator[subprocess.CompletedProcess[str]] = iter(
            [
                subprocess.CompletedProcess[str]([], 0),  # unstaged = clean
                subprocess.CompletedProcess[str]([], 1),  # staged = dirty
            ]
        )

        def run_next(
            _args: list[str], *, check: bool = True, capture: bool = False
        ) -> subprocess.CompletedProcess[str]:
            return next(results)

        monkeypatch.setattr(_release, "run", run_next)

        with pytest.raises(SystemExit):
            _release.ensure_clean()


# ---------------------------------------------------------------------------
# release() orchestrator
# ---------------------------------------------------------------------------


class TestReleaseOrchestrator:
    """Tests for release() orchestrator function."""

    @pytest.fixture
    def mock_release_deps(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
        """Patch all external dependencies of release() and return call tracker."""
        calls: dict[str, list[Any]] = {"push": [], "tag_create": [], "gh_create": [], "gh_edit": []}

        config = _make_config({"project": {"name": "test", "version": "1.2.3"}})

        monkeypatch.setattr(
            _release, "load_pyproject_config", fake_of(_release.load_pyproject_config).returning(config)
        )
        monkeypatch.setattr(_release, "ensure_clean", fake_of(_release.ensure_clean).returning(None))
        monkeypatch.setattr(_release, "git_branch", fake_of(_release.git_branch).returning("main"))

        def git_push(remote: str, ref: str) -> None:
            calls["push"].append((remote, ref))

        def git_create_annotated_tag(name: str, _message: str) -> None:
            calls["tag_create"].append(name)

        def gh_release_create(tag: str, _title: str, _body: str) -> None:
            calls["gh_create"].append(tag)

        def gh_release_edit(tag: str, _title: str, _body: str) -> None:
            calls["gh_edit"].append(tag)

        monkeypatch.setattr(_release, "git_push", git_push)
        monkeypatch.setattr(_release, "git_tag_exists", fake_of(_release.git_tag_exists).returning(False))
        monkeypatch.setattr(_release, "git_create_annotated_tag", git_create_annotated_tag)
        monkeypatch.setattr(_release, "gh_available", fake_of(_release.gh_available).returning(True))
        monkeypatch.setattr(_release, "gh_release_exists", fake_of(_release.gh_release_exists).returning(False))
        monkeypatch.setattr(_release, "gh_release_create", gh_release_create)
        monkeypatch.setattr(_release, "gh_release_edit", gh_release_edit)

        return calls

    @pytest.mark.os_agnostic
    def test_returns_one_for_invalid_version(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Returns 1 when the version is not a version at all.

        Not "1.0": that is a legal PEP 440 version and is now released normally.
        """
        config = _make_config({"project": {"name": "test", "version": "not-a-version"}})
        monkeypatch.setattr(
            _release, "load_pyproject_config", fake_of(_release.load_pyproject_config).returning(config)
        )

        result = _release.release(project_dir=tmp_path)

        assert result == 1

    @pytest.mark.os_agnostic
    def test_happy_path_pushes_and_tags(self, mock_release_deps: dict[str, list[Any]], tmp_path: Path) -> None:
        """Happy path: pushes branch, creates tag, pushes tag."""
        result = _release.release(project_dir=tmp_path)

        assert result == 0
        assert ("origin", "main") in mock_release_deps["push"]
        assert ("origin", "v1.2.3") in mock_release_deps["push"]
        assert "v1.2.3" in mock_release_deps["tag_create"]

    @pytest.mark.os_agnostic
    def test_uses_configured_remote(
        self,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Honors tool.git.default-remote from config."""
        config_upstream = _make_config(
            {
                "project": {"name": "test", "version": "1.2.3"},
                "tool": {"git": {"default-remote": "upstream"}},
            }
        )
        monkeypatch.setattr(
            _release, "load_pyproject_config", fake_of(_release.load_pyproject_config).returning(config_upstream)
        )

        result = _release.release(project_dir=tmp_path)

        assert result == 0
        assert ("upstream", "main") in mock_release_deps["push"]

    @pytest.mark.os_agnostic
    def test_explicit_remote_overrides_config(self, mock_release_deps: dict[str, list[Any]], tmp_path: Path) -> None:
        """Explicit remote= parameter overrides config."""
        result = _release.release(project_dir=tmp_path, remote="custom")

        assert result == 0
        assert ("custom", "main") in mock_release_deps["push"]

    @pytest.mark.os_agnostic
    def test_skips_tag_creation_when_exists(
        self,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Skips tag creation when tag already exists locally."""
        monkeypatch.setattr(_release, "git_tag_exists", fake_of(_release.git_tag_exists).returning(True))

        result = _release.release(project_dir=tmp_path)

        assert result == 0
        assert mock_release_deps["tag_create"] == []

    @pytest.mark.os_agnostic
    def test_creates_github_release(self, mock_release_deps: dict[str, list[Any]], tmp_path: Path) -> None:
        """Creates GitHub release when gh is available and no existing release."""
        result = _release.release(project_dir=tmp_path)

        assert result == 0
        assert "v1.2.3" in mock_release_deps["gh_create"]

    @pytest.mark.os_agnostic
    def test_edits_existing_github_release(
        self,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Edits existing GitHub release instead of creating new one."""
        monkeypatch.setattr(_release, "gh_release_exists", fake_of(_release.gh_release_exists).returning(True))

        result = _release.release(project_dir=tmp_path)

        assert result == 0
        assert "v1.2.3" in mock_release_deps["gh_edit"]
        assert mock_release_deps["gh_create"] == []

    @pytest.mark.os_agnostic
    def test_skips_github_when_unavailable(
        self,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        """Prints message and continues when gh CLI is unavailable."""
        monkeypatch.setattr(_release, "gh_available", fake_of(_release.gh_available).returning(False))

        result = _release.release(project_dir=tmp_path)

        assert result == 0
        assert "gh CLI not found" in capsys.readouterr().out
        assert mock_release_deps["gh_create"] == []
        assert mock_release_deps["gh_edit"] == []

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize("version", ["0.1.0rc1", "1.0.0a1", "1.3.0b2", "1.2.3.dev4", "1.2.3.post1", "1!2.0.0"])
    def test_a_canonical_pep440_version_is_released_and_tagged(
        self,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        version: str,
    ) -> None:
        """hatchling builds these and PyPI accepts them, so bmk must not be the one to refuse."""
        config = _make_config({"project": {"name": "test", "version": version}})
        monkeypatch.setattr(
            _release, "load_pyproject_config", fake_of(_release.load_pyproject_config).returning(config)
        )

        result = _release.release(project_dir=tmp_path)

        assert result == 0
        assert f"v{version}" in mock_release_deps["tag_create"]
        assert ("origin", f"v{version}") in mock_release_deps["push"]

    @pytest.mark.os_agnostic
    def test_a_v_prefixed_version_is_refused_before_it_can_tag_vv(
        self,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        """packaging PARSES "v1.0.0"; accepting it would tag "vv1.0.0" (tag = f"v{version}")."""
        config = _make_config({"project": {"name": "test", "version": "v1.0.0"}})
        monkeypatch.setattr(
            _release, "load_pyproject_config", fake_of(_release.load_pyproject_config).returning(config)
        )

        result = _release.release(project_dir=tmp_path)

        assert result == 1
        assert mock_release_deps["tag_create"] == []
        assert "1.0.0" in capsys.readouterr().err

    @pytest.mark.os_agnostic
    def test_a_local_version_is_refused_because_pypi_would_reject_the_upload(
        self,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A local version tags fine and then dies in CI at publish; refuse it here instead."""
        config = _make_config({"project": {"name": "test", "version": "1.2.3+local"}})
        monkeypatch.setattr(
            _release, "load_pyproject_config", fake_of(_release.load_pyproject_config).returning(config)
        )

        result = _release.release(project_dir=tmp_path)

        assert result == 1
        assert mock_release_deps["tag_create"] == []
