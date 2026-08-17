"""Behaviour tests for makescripts._release: version validation, default remote, command existence."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters.stagerunner.helpers._release import _cmd_exists, _get_default_remote
from bmk.adapters.stagerunner.helpers._toml_config import PyprojectConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import CaptureFixture

# The version rules themselves are owned by bmk.domain.version and tested in
# tests/test_domain_version.py. What is tested HERE is that release() consults them and
# stops before tagging - see TestReleaseOrchestrator at the bottom of this file.


# ---------------------------------------------------------------------------
# _get_default_remote
# ---------------------------------------------------------------------------


def _make_config(raw_data: dict[str, Any]) -> PyprojectConfig:
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


# ---------------------------------------------------------------------------
# _ensure_clean
# ---------------------------------------------------------------------------


class TestEnsureClean:
    """Tests for _ensure_clean function."""

    @pytest.fixture
    def release_module(self) -> Any:
        """Import release module."""
        from bmk.adapters.stagerunner.helpers import _release

        return _release

    @pytest.mark.os_agnostic
    def test_passes_on_clean_tree(self, release_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """No error when both diff commands return 0."""
        clean: subprocess.CompletedProcess[str] = subprocess.CompletedProcess([], 0)
        monkeypatch.setattr(release_module, "_run", lambda _args, **_kw: clean)  # type: ignore[reportUnknownLambdaType]

        release_module._ensure_clean()  # Should not raise

    @pytest.mark.os_agnostic
    def test_raises_on_unstaged_changes(self, release_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """SystemExit when unstaged changes are detected."""
        results: Iterator[subprocess.CompletedProcess[str]] = iter(
            [
                subprocess.CompletedProcess[str]([], 1),  # unstaged = dirty
                subprocess.CompletedProcess[str]([], 0),  # staged = clean
            ]
        )
        monkeypatch.setattr(release_module, "_run", lambda _args, **_kw: next(results))  # type: ignore[reportUnknownLambdaType]

        with pytest.raises(SystemExit):
            release_module._ensure_clean()

    @pytest.mark.os_agnostic
    def test_raises_on_staged_changes(self, release_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """SystemExit when staged changes are detected."""
        results: Iterator[subprocess.CompletedProcess[str]] = iter(
            [
                subprocess.CompletedProcess[str]([], 0),  # unstaged = clean
                subprocess.CompletedProcess[str]([], 1),  # staged = dirty
            ]
        )
        monkeypatch.setattr(release_module, "_run", lambda _args, **_kw: next(results))  # type: ignore[reportUnknownLambdaType]

        with pytest.raises(SystemExit):
            release_module._ensure_clean()


# ---------------------------------------------------------------------------
# release() orchestrator
# ---------------------------------------------------------------------------


class TestReleaseOrchestrator:
    """Tests for release() orchestrator function."""

    @pytest.fixture
    def release_module(self) -> Any:
        """Import release module."""
        from bmk.adapters.stagerunner.helpers import _release

        return _release

    @pytest.fixture
    def mock_release_deps(self, release_module: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
        """Patch all external dependencies of release() and return call tracker."""
        calls: dict[str, list[Any]] = {"push": [], "tag_create": [], "gh_create": [], "gh_edit": []}

        config = _make_config({"project": {"name": "test", "version": "1.2.3"}})

        monkeypatch.setattr(release_module, "load_pyproject_config", lambda _path: config)  # type: ignore[reportUnknownLambdaType]
        monkeypatch.setattr(release_module, "_ensure_clean", lambda: None)
        monkeypatch.setattr(release_module, "_git_branch", lambda: "main")
        monkeypatch.setattr(release_module, "_git_push", lambda remote, ref: calls["push"].append((remote, ref)))  # type: ignore[reportUnknownLambdaType]
        monkeypatch.setattr(release_module, "_git_tag_exists", lambda _tag: False)  # type: ignore[reportUnknownLambdaType]
        monkeypatch.setattr(
            release_module,
            "_git_create_annotated_tag",
            lambda tag, _msg: calls["tag_create"].append(tag),  # type: ignore[reportUnknownLambdaType]
        )
        monkeypatch.setattr(release_module, "_gh_available", lambda: True)
        monkeypatch.setattr(release_module, "_gh_release_exists", lambda _tag: False)  # type: ignore[reportUnknownLambdaType]
        monkeypatch.setattr(
            release_module,
            "_gh_release_create",
            lambda tag, _title, _body: calls["gh_create"].append(tag),  # type: ignore[reportUnknownLambdaType]
        )
        monkeypatch.setattr(release_module, "_gh_release_edit", lambda tag, _title, _body: calls["gh_edit"].append(tag))  # type: ignore[reportUnknownLambdaType]

        return calls

    @pytest.mark.os_agnostic
    def test_returns_one_for_invalid_version(
        self, release_module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Returns 1 when the version is not a version at all.

        Not "1.0": that is a legal PEP 440 version and is now released normally.
        """
        config = _make_config({"project": {"name": "test", "version": "not-a-version"}})
        monkeypatch.setattr(release_module, "load_pyproject_config", lambda _path: config)  # type: ignore[reportUnknownLambdaType]

        result = release_module.release(project_dir=tmp_path)

        assert result == 1

    @pytest.mark.os_agnostic
    def test_happy_path_pushes_and_tags(
        self, release_module: Any, mock_release_deps: dict[str, list[Any]], tmp_path: Path
    ) -> None:
        """Happy path: pushes branch, creates tag, pushes tag."""
        result = release_module.release(project_dir=tmp_path)

        assert result == 0
        assert ("origin", "main") in mock_release_deps["push"]
        assert ("origin", "v1.2.3") in mock_release_deps["push"]
        assert "v1.2.3" in mock_release_deps["tag_create"]

    @pytest.mark.os_agnostic
    def test_uses_configured_remote(
        self,
        release_module: Any,
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
        monkeypatch.setattr(release_module, "load_pyproject_config", lambda _path: config_upstream)  # type: ignore[reportUnknownLambdaType]

        result = release_module.release(project_dir=tmp_path)

        assert result == 0
        assert ("upstream", "main") in mock_release_deps["push"]

    @pytest.mark.os_agnostic
    def test_explicit_remote_overrides_config(
        self, release_module: Any, mock_release_deps: dict[str, list[Any]], tmp_path: Path
    ) -> None:
        """Explicit remote= parameter overrides config."""
        result = release_module.release(project_dir=tmp_path, remote="custom")

        assert result == 0
        assert ("custom", "main") in mock_release_deps["push"]

    @pytest.mark.os_agnostic
    def test_skips_tag_creation_when_exists(
        self,
        release_module: Any,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Skips tag creation when tag already exists locally."""
        monkeypatch.setattr(release_module, "_git_tag_exists", lambda _tag: True)  # type: ignore[reportUnknownLambdaType]

        result = release_module.release(project_dir=tmp_path)

        assert result == 0
        assert mock_release_deps["tag_create"] == []

    @pytest.mark.os_agnostic
    def test_creates_github_release(
        self, release_module: Any, mock_release_deps: dict[str, list[Any]], tmp_path: Path
    ) -> None:
        """Creates GitHub release when gh is available and no existing release."""
        result = release_module.release(project_dir=tmp_path)

        assert result == 0
        assert "v1.2.3" in mock_release_deps["gh_create"]

    @pytest.mark.os_agnostic
    def test_edits_existing_github_release(
        self,
        release_module: Any,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Edits existing GitHub release instead of creating new one."""
        monkeypatch.setattr(release_module, "_gh_release_exists", lambda _tag: True)  # type: ignore[reportUnknownLambdaType]

        result = release_module.release(project_dir=tmp_path)

        assert result == 0
        assert "v1.2.3" in mock_release_deps["gh_edit"]
        assert mock_release_deps["gh_create"] == []

    @pytest.mark.os_agnostic
    def test_skips_github_when_unavailable(
        self,
        release_module: Any,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        """Prints message and continues when gh CLI is unavailable."""
        monkeypatch.setattr(release_module, "_gh_available", lambda: False)

        result = release_module.release(project_dir=tmp_path)

        assert result == 0
        assert "gh CLI not found" in capsys.readouterr().out
        assert mock_release_deps["gh_create"] == []
        assert mock_release_deps["gh_edit"] == []

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize("version", ["0.1.0rc1", "1.0.0a1", "1.3.0b2", "1.2.3.dev4", "1.2.3.post1", "1!2.0.0"])
    def test_a_canonical_pep440_version_is_released_and_tagged(
        self,
        release_module: Any,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        version: str,
    ) -> None:
        """hatchling builds these and PyPI accepts them, so bmk must not be the one to refuse."""
        config = _make_config({"project": {"name": "test", "version": version}})
        monkeypatch.setattr(release_module, "load_pyproject_config", lambda _path: config)  # type: ignore[reportUnknownLambdaType]

        result = release_module.release(project_dir=tmp_path)

        assert result == 0
        assert f"v{version}" in mock_release_deps["tag_create"]
        assert ("origin", f"v{version}") in mock_release_deps["push"]

    @pytest.mark.os_agnostic
    def test_a_v_prefixed_version_is_refused_before_it_can_tag_vv(
        self,
        release_module: Any,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        """packaging PARSES "v1.0.0"; accepting it would tag "vv1.0.0" (tag = f"v{version}")."""
        config = _make_config({"project": {"name": "test", "version": "v1.0.0"}})
        monkeypatch.setattr(release_module, "load_pyproject_config", lambda _path: config)  # type: ignore[reportUnknownLambdaType]

        result = release_module.release(project_dir=tmp_path)

        assert result == 1
        assert mock_release_deps["tag_create"] == []
        assert "1.0.0" in capsys.readouterr().err

    @pytest.mark.os_agnostic
    def test_a_local_version_is_refused_because_pypi_would_reject_the_upload(
        self,
        release_module: Any,
        mock_release_deps: dict[str, list[Any]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A local version tags fine and then dies in CI at publish; refuse it here instead."""
        config = _make_config({"project": {"name": "test", "version": "1.2.3+local"}})
        monkeypatch.setattr(release_module, "load_pyproject_config", lambda _path: config)  # type: ignore[reportUnknownLambdaType]

        result = release_module.release(project_dir=tmp_path)

        assert result == 1
        assert mock_release_deps["tag_create"] == []
