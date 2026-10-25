"""Unit tests for makescripts modules.

Tests pure functions and logic that can be unit tested without external
dependencies (subprocess calls, network requests, etc.).
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from fakes import fake_of

from bmk.adapters.stagerunner.helpers import _clean, _coverage, _dependencies

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest import CaptureFixture


# subprocess.run and shutil.which are overloaded, and pyright binds fake_of to whichever overload
# fits the platform and Python it checks (on Windows below 3.12 that made shutil.which's return
# NoReturn), so their fakes are plain typed functions instead.
def _run_returning(result: subprocess.CompletedProcess[str]) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return result

    return run


def _which_returning(path: str | None) -> Callable[[str], str | None]:
    def which(_cmd: str) -> str | None:
        return path

    return which


# =============================================================================
# _coverage.py tests
# =============================================================================


class TestCoverageConfig:
    """Tests for CoverageConfig dataclass."""

    @pytest.mark.os_agnostic
    def test_from_pyproject_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        """CoverageConfig returns defaults when pyproject.toml doesn't exist."""
        config = _coverage.CoverageConfig.from_pyproject(tmp_path)

        assert config.pytest_verbosity == "-v"
        assert config.coverage_report_file == "coverage.xml"
        assert config.src_path == "src"
        assert config.fail_under == 80
        assert config.coverage_source == ["src"]
        assert config.exclude_markers == "integration"

    @pytest.mark.os_agnostic
    def test_from_pyproject_loads_values_from_toml(self, tmp_path: Path) -> None:
        """CoverageConfig loads values from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.scripts.test]
pytest-verbosity = "-vv"
coverage-report-file = "custom.xml"
src-path = "lib"
exclude-markers = "slow"

[tool.coverage.run]
source = ["lib/mypackage"]

[tool.coverage.report]
fail_under = 95
"""
        )

        config = _coverage.CoverageConfig.from_pyproject(tmp_path)

        assert config.pytest_verbosity == "-vv"
        assert config.coverage_report_file == "custom.xml"
        assert config.src_path == "lib"
        assert config.fail_under == 95
        assert config.coverage_source == ["lib/mypackage"]
        assert config.exclude_markers == "slow"

    @pytest.mark.os_agnostic
    def test_from_pyproject_uses_defaults_for_missing_keys(self, tmp_path: Path) -> None:
        """CoverageConfig uses defaults for missing keys in pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.coverage.report]
fail_under = 85
"""
        )

        config = _coverage.CoverageConfig.from_pyproject(tmp_path)

        assert config.pytest_verbosity == "-v"
        assert config.fail_under == 85
        assert config.coverage_source == ["src"]


class TestCoverageFileManagement:
    """Tests for coverage file cleanup functions."""

    @pytest.mark.os_agnostic
    def test_prune_coverage_data_files_removes_coverage_files(self, tmp_path: Path) -> None:
        """prune_coverage_data_files removes .coverage* files."""
        # Create test files
        (tmp_path / ".coverage").write_text("data")
        (tmp_path / ".coverage.abc123").write_text("data")
        (tmp_path / ".coverage.xml").write_text("data")  # Should NOT be removed

        _coverage.prune_coverage_data_files(tmp_path)

        assert not (tmp_path / ".coverage").exists()
        assert not (tmp_path / ".coverage.abc123").exists()
        assert (tmp_path / ".coverage.xml").exists()  # XML preserved

    @pytest.mark.os_agnostic
    def test_prune_coverage_data_files_ignores_directories(self, tmp_path: Path) -> None:
        """prune_coverage_data_files doesn't remove directories."""
        coverage_dir = tmp_path / ".coverage_dir"
        coverage_dir.mkdir()
        (coverage_dir / "file.txt").write_text("data")

        _coverage.prune_coverage_data_files(tmp_path)

        assert coverage_dir.exists()
        assert (coverage_dir / "file.txt").exists()

    @pytest.mark.os_agnostic
    def test_remove_report_artifacts_removes_report_files(self, tmp_path: Path) -> None:
        """remove_report_artifacts removes coverage report files."""
        (tmp_path / "coverage.xml").write_text("data")
        (tmp_path / "codecov.xml").write_text("data")
        (tmp_path / "other.xml").write_text("data")  # Should NOT be removed

        _coverage.remove_report_artifacts(tmp_path)

        assert not (tmp_path / "coverage.xml").exists()
        assert not (tmp_path / "codecov.xml").exists()
        assert (tmp_path / "other.xml").exists()

    @pytest.mark.os_agnostic
    def test_remove_report_artifacts_uses_custom_report_name(self, tmp_path: Path) -> None:
        """remove_report_artifacts removes custom-named report file."""
        (tmp_path / "custom.xml").write_text("data")
        (tmp_path / "coverage.xml").write_text("data")  # Should NOT be removed

        _coverage.remove_report_artifacts(tmp_path, "custom.xml")

        assert not (tmp_path / "custom.xml").exists()
        assert (tmp_path / "coverage.xml").exists()


class TestBuildEnv:
    """Tests for build_env function."""

    @pytest.mark.os_agnostic
    def test_build_env_adds_src_to_pythonpath(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_env adds src path to PYTHONPATH."""
        monkeypatch.delenv("PYTHONPATH", raising=False)

        env = _coverage.build_env(tmp_path, "src")

        assert str(tmp_path / "src") in env["PYTHONPATH"]

    @pytest.mark.os_agnostic
    def test_build_env_preserves_existing_pythonpath(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_env preserves existing PYTHONPATH."""
        monkeypatch.setenv("PYTHONPATH", "/existing/path")

        env = _coverage.build_env(tmp_path, "src")

        assert "/existing/path" in env["PYTHONPATH"]
        assert str(tmp_path / "src") in env["PYTHONPATH"]


class TestEnsureCodecovToken:
    """Tests for ensure_codecov_token function."""

    @pytest.mark.os_agnostic
    def test_returns_existing_token_from_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_codecov_token returns token when CODECOV_TOKEN is set."""
        monkeypatch.setenv("CODECOV_TOKEN", "existing-token")

        result = _coverage.ensure_codecov_token(tmp_path)

        assert result == "existing-token"

    @pytest.mark.os_agnostic
    def test_returns_none_when_env_file_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_codecov_token returns None when no .env file in hierarchy."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.setattr(_coverage, "find_dotenv_upward", fake_of(_coverage.find_dotenv_upward).returning(None))

        result = _coverage.ensure_codecov_token(tmp_path)

        assert result is None

    @pytest.mark.os_agnostic
    def test_loads_token_from_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_codecov_token loads token from .env file without mutating os.environ."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("CODECOV_TOKEN=my-secret-token\n")

        result = _coverage.ensure_codecov_token(tmp_path)

        assert result == "my-secret-token"
        assert os.environ.get("CODECOV_TOKEN") is None

    @pytest.mark.os_agnostic
    def test_handles_quoted_token_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_codecov_token handles quoted token values."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text('CODECOV_TOKEN="quoted-token"\n')

        result = _coverage.ensure_codecov_token(tmp_path)

        assert result == "quoted-token"
        assert os.environ.get("CODECOV_TOKEN") is None

    @pytest.mark.os_agnostic
    def test_skips_comments_and_empty_lines(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_codecov_token skips comments and empty lines."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            """
# This is a comment
OTHER_VAR=value

CODECOV_TOKEN=found-token
"""
        )

        result = _coverage.ensure_codecov_token(tmp_path)

        assert result == "found-token"
        assert os.environ.get("CODECOV_TOKEN") is None

    @pytest.mark.os_agnostic
    def test_finds_env_file_in_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_codecov_token finds .env in a parent directory."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("CODECOV_TOKEN=parent-token\n")
        child_dir = tmp_path / "sub" / "deep"
        child_dir.mkdir(parents=True)

        result = _coverage.ensure_codecov_token(child_dir)

        assert result == "parent-token"
        assert os.environ.get("CODECOV_TOKEN") is None


class TestFindDotenvUpward:
    """Tests for find_dotenv_upward helper."""

    @pytest.mark.os_agnostic
    def test_finds_env_in_start_dir(self, tmp_path: Path) -> None:
        """find_dotenv_upward finds .env in the start directory."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")

        result = _coverage.find_dotenv_upward(tmp_path)

        assert result == env_file

    @pytest.mark.os_agnostic
    def test_finds_env_in_parent(self, tmp_path: Path) -> None:
        """find_dotenv_upward finds .env in a parent directory."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        child = tmp_path / "a" / "b"
        child.mkdir(parents=True)

        result = _coverage.find_dotenv_upward(child)

        assert result == env_file

    @pytest.mark.os_agnostic
    def test_returns_none_when_no_env_file(self, tmp_path: Path) -> None:
        """find_dotenv_upward returns None when no .env exists in hierarchy."""
        child = tmp_path / "empty"
        child.mkdir()

        result = _coverage.find_dotenv_upward(child)

        # May return None or find a .env above tmp_path - assert type is correct
        assert result is None or result.name == ".env"


class TestGitServiceHelpers:
    """Tests for git service helper functions."""

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("github.com", "github"),
            ("GITHUB.COM", "github"),
            ("gitlab.com", "gitlab"),
            ("bitbucket.org", "bitbucket"),
            ("unknown.com", None),
            (None, None),
            ("", None),
        ],
    )
    def test_resolve_git_service_maps_hosts(self, host: str | None, expected: str | None) -> None:
        """resolve_git_service maps host names to service identifiers."""
        assert _coverage.resolve_git_service(host) == expected

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("owner", "name", "expected"),
        [
            ("myorg", "myrepo", "myorg/myrepo"),
            ("user", "project", "user/project"),
            ("", "myrepo", None),
            ("myorg", "", None),
            ("", "", None),
        ],
    )
    def test_repo_remote_builds_slug(self, owner: str, name: str, expected: str | None) -> None:
        """RepoRemote.slug builds the owner/name slug, None when either part is empty."""
        assert _coverage.RepoRemote("github.com", owner, name).slug == expected


class TestBuildCodecovEnv:
    """Tests for build_codecov_env function."""

    @pytest.mark.os_agnostic
    def test_always_sets_no_combine(self) -> None:
        """build_codecov_env always sets CODECOV_NO_COMBINE."""
        env = _coverage.build_codecov_env(None)

        assert env["CODECOV_NO_COMBINE"] == "1"

    @pytest.mark.os_agnostic
    def test_sets_slug_when_owner_and_name_provided(self) -> None:
        """build_codecov_env sets CODECOV_SLUG when owner and name provided."""
        env = _coverage.build_codecov_env(_coverage.RepoRemote("github.com", "myorg", "myrepo"))

        assert env["CODECOV_SLUG"] == "myorg/myrepo"


class TestHandleCodecovResult:
    """Tests for handle_codecov_result function."""

    @pytest.mark.os_agnostic
    def test_returns_true_on_success(self, capsys: CaptureFixture[str]) -> None:
        """handle_codecov_result returns True on exit code 0."""
        result = _coverage.handle_codecov_result(0)

        assert result is True
        captured = capsys.readouterr()
        assert "upload succeeded" in captured.out

    @pytest.mark.os_agnostic
    def test_returns_false_on_failure(self, capsys: CaptureFixture[str]) -> None:
        """handle_codecov_result returns False on non-zero exit code."""
        result = _coverage.handle_codecov_result(1)

        assert result is False
        captured = capsys.readouterr()
        assert "upload failed" in captured.err


class TestMain:
    """Tests for main() orchestrator function."""

    @pytest.mark.os_agnostic
    def test_main_returns_zero_when_token_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        """main() returns 0 and prints warning when CODECOV_TOKEN is missing."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.setattr(_coverage, "find_dotenv_upward", fake_of(_coverage.find_dotenv_upward).returning(None))

        result = _coverage.main(
            project_dir=tmp_path,
            run_tests=False,
            upload=True,
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "CODECOV_TOKEN not found" in captured.err
        assert "skipping upload" in captured.err


# =============================================================================
# _clean.py tests
# =============================================================================


class TestCleanPatterns:
    """Tests for clean patterns loading."""

    @pytest.mark.os_agnostic
    def test_get_clean_patterns_returns_fallback_when_no_pyproject(self, tmp_path: Path) -> None:
        """get_clean_patterns returns fallback patterns when pyproject.toml missing."""
        patterns = _clean.get_clean_patterns(tmp_path / "pyproject.toml")

        assert ".pytest_cache" in patterns
        assert ".ruff_cache" in patterns
        assert "build" in patterns
        assert "dist" in patterns

    @pytest.mark.os_agnostic
    def test_get_clean_patterns_loads_from_pyproject(self, tmp_path: Path) -> None:
        """get_clean_patterns loads patterns from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.clean]
patterns = ["custom_cache", "*.tmp"]
"""
        )

        patterns = _clean.get_clean_patterns(pyproject)

        assert "custom_cache" in patterns
        assert "*.tmp" in patterns


class TestCleanFunction:
    """Tests for clean function."""

    @pytest.mark.os_agnostic
    def test_clean_removes_matching_directories(self, tmp_path: Path) -> None:
        """clean removes directories matching patterns."""
        cache_dir = tmp_path / ".pytest_cache"
        cache_dir.mkdir()
        (cache_dir / "data.txt").write_text("cached")

        _clean.clean(project_dir=tmp_path, patterns=[".pytest_cache"], verbose=False)

        assert not cache_dir.exists()

    @pytest.mark.os_agnostic
    def test_clean_removes_matching_files(self, tmp_path: Path) -> None:
        """clean removes files matching patterns."""
        (tmp_path / "coverage.xml").write_text("data")

        _clean.clean(project_dir=tmp_path, patterns=["coverage.xml"], verbose=False)

        assert not (tmp_path / "coverage.xml").exists()

    @pytest.mark.os_agnostic
    def test_clean_dry_run_does_not_remove(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """clean with dry_run=True doesn't remove anything."""
        cache_dir = tmp_path / ".pytest_cache"
        cache_dir.mkdir()

        _clean.clean(project_dir=tmp_path, patterns=[".pytest_cache"], dry_run=True)

        assert cache_dir.exists()
        captured = capsys.readouterr()
        assert "[DRY RUN]" in captured.out

    @pytest.mark.os_agnostic
    def test_clean_verbose_outputs_each_removal(self, tmp_path: Path, capsys: CaptureFixture[str]) -> None:
        """clean with verbose=True outputs each removal."""
        (tmp_path / "coverage.xml").write_text("data")

        _clean.clean(project_dir=tmp_path, patterns=["coverage.xml"], verbose=True)

        captured = capsys.readouterr()
        assert "Removing file:" in captured.out


# =============================================================================
# _dependencies.py tests
# =============================================================================


class TestDependencyVersionParsing:
    """Tests for version parsing functions."""

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("rich-click", "rich-click"),
            ("Rich_Click", "rich-click"),
            ("rich.click", "rich-click"),
            ("RICH__CLICK", "rich-click"),
        ],
    )
    def test_normalize_name_handles_variations(self, name: str, expected: str) -> None:
        """normalize_name normalizes package names per PEP 503."""
        assert _dependencies.normalize_name(name) == expected

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("spec", "expected_name", "expected_constraint", "expected_min", "expected_upper"),
        [
            ("rich-click>=1.9.4", "rich-click", ">=1.9.4", "1.9.4", ""),
            ("pytest>=8.4.2,<9", "pytest", ">=8.4.2,<9", "8.4.2", "9"),
            ("tomli>=2.0.0; python_version<'3.11'", "tomli", ">=2.0.0", "2.0.0", ""),
            ("package[extra]>=1.0", "package", ">=1.0", "1.0", ""),
            ("simple-package", "simple-package", "", "", ""),
            ("pkg==1.2.3", "pkg", "==1.2.3", "1.2.3", ""),
            ("pkg~=1.4", "pkg", "~=1.4", "1.4", ""),
        ],
    )
    def test_parse_version_constraint_extracts_components(
        self,
        *,
        spec: str,
        expected_name: str,
        expected_constraint: str,
        expected_min: str,
        expected_upper: str,
    ) -> None:
        """parse_version_constraint extracts name, constraint, min, and upper bound."""
        parsed = _dependencies.parse_version_constraint(spec)

        assert parsed.name == expected_name
        assert parsed.constraint == expected_constraint
        assert parsed.min_version == expected_min
        assert parsed.upper_bound == expected_upper

    @pytest.mark.os_agnostic
    def test_parse_version_constraint_handles_empty_string(self) -> None:
        """parse_version_constraint handles empty string."""
        parsed = _dependencies.parse_version_constraint("")

        assert parsed.name == ""
        assert parsed.constraint == ""
        assert parsed.min_version == ""
        assert parsed.upper_bound == ""


class TestVersionComparison:
    """Tests for version comparison functions."""

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("1.2.3", (1, 2, 3)),
            ("2.0", (2, 0)),
            ("1.2.3.4", (1, 2, 3, 4)),
            ("1.2.3a1", (1, 2, 3)),
            ("invalid", ()),
        ],
    )
    def test_parse_version_tuple_extracts_numeric_parts(self, version: str, expected: tuple[int, ...]) -> None:
        """parse_version_tuple extracts numeric version parts."""
        assert _dependencies.parse_version_tuple(version) == expected

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("version_a", "version_b", "expected"),
        [
            ("1.2.3", "1.2.3", True),
            ("1.2.4", "1.2.3", True),
            ("2.0.0", "1.9.9", True),
            ("1.2.3", "1.2.4", False),
            ("1.2", "1.2.0", True),
            ("1.2.0", "1.2", True),
        ],
    )
    def test_version_gte_compares_correctly(self, version_a: str, version_b: str, expected: bool) -> None:
        """version_gte correctly compares versions."""
        assert _dependencies.version_gte(version_a, version_b) == expected

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("current", "latest", "expected"),
        [
            ("1.2.3", "1.2.3", "up-to-date"),
            ("1.2.4", "1.2.3", "up-to-date"),
            ("1.2.3", "1.2.4", "outdated"),
            ("", "1.0.0", "unknown"),
            ("1.0.0", "", "unknown"),
        ],
    )
    def test_compare_versions_returns_correct_status(self, current: str, latest: str, expected: str) -> None:
        """compare_versions returns correct status."""
        assert _dependencies.compare_versions(current, latest) == expected


class TestStatusIcon:
    """Tests for get_status_icon function."""

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (_dependencies.DependencyStatus.UP_TO_DATE, "[ok]"),
            (_dependencies.DependencyStatus.OUTDATED, "[!!]"),
            (_dependencies.DependencyStatus.PINNED, "[==]"),
            (_dependencies.DependencyStatus.UNKNOWN, "[??]"),
            (_dependencies.DependencyStatus.ERROR, "[XX]"),
        ],
    )
    def test_get_status_icon_returns_correct_icon(self, status: _dependencies.DependencyStatus, expected: str) -> None:
        """get_status_icon returns the icon for each status."""
        assert _dependencies.get_status_icon(status) == expected

    @pytest.mark.os_agnostic
    def test_every_status_has_an_icon_of_its_own(self) -> None:
        """A status added later without an icon would fall back to [??] and read as UNKNOWN."""
        icons = {status: _dependencies.get_status_icon(status) for status in _dependencies.DependencyStatus}
        assert len(set(icons.values())) == len(icons)


class TestBuildUpdatedSpec:
    """Tests for build_updated_spec function."""

    @pytest.mark.os_agnostic
    def test_updates_version_constraint(self) -> None:
        """build_updated_spec updates version in constraint."""
        dep = _dependencies.DependencyInfo(
            name="pytest",
            source="test",
            constraint=">=8.0.0",
            current_min="8.0.0",
            latest_version="9.0.0",
            status=_dependencies.DependencyStatus.OUTDATED,
            original_spec="pytest>=8.0.0",
        )

        result = _dependencies.build_updated_spec(dep)

        assert result == "pytest>=9.0.0"

    @pytest.mark.os_agnostic
    def test_preserves_environment_markers(self) -> None:
        """build_updated_spec preserves environment markers."""
        dep = _dependencies.DependencyInfo(
            name="tomli",
            source="test",
            constraint=">=2.0.0",
            current_min="2.0.0",
            latest_version="2.1.0",
            status=_dependencies.DependencyStatus.OUTDATED,
            original_spec="tomli>=2.0.0; python_version<'3.11'",
        )

        result = _dependencies.build_updated_spec(dep)

        assert "; python_version<'3.11'" in result
        assert ">=2.1.0" in result

    @pytest.mark.os_agnostic
    def test_returns_original_when_latest_not_found(self) -> None:
        """build_updated_spec returns original when PyPI did not answer (no latest version)."""
        dep = _dependencies.DependencyInfo(
            name="unknown",
            source="test",
            constraint=">=1.0.0",
            current_min="1.0.0",
            latest_version=None,
            status=_dependencies.DependencyStatus.ERROR,
            original_spec="unknown>=1.0.0",
        )

        result = _dependencies.build_updated_spec(dep)

        assert result == "unknown>=1.0.0"


class TestBuildUpdatedSpecExtended:
    """Additional edge cases for build_updated_spec."""

    @pytest.mark.os_agnostic
    def test_preserves_extras(self) -> None:
        """build_updated_spec preserves extras bracket notation."""
        dep = _dependencies.DependencyInfo(
            name="pkg",
            source="test",
            constraint=">=1.0",
            current_min="1.0",
            latest_version="2.0",
            status=_dependencies.DependencyStatus.OUTDATED,
            original_spec="pkg[extra]>=1.0",
        )

        result = _dependencies.build_updated_spec(dep)

        assert "[extra]" in result
        assert ">=2.0" in result

    @pytest.mark.os_agnostic
    def test_adds_constraint_to_bare_name(self) -> None:
        """build_updated_spec adds >=latest to a bare package name."""
        dep = _dependencies.DependencyInfo(
            name="mypackage",
            source="test",
            constraint="",
            current_min="",
            latest_version="2.0",
            status=_dependencies.DependencyStatus.OUTDATED,
            original_spec="mypackage",
        )

        result = _dependencies.build_updated_spec(dep)

        assert "mypackage" in result
        assert ">=2.0" in result

    @pytest.mark.os_agnostic
    def test_double_equals(self) -> None:
        """build_updated_spec updates == constraints."""
        dep = _dependencies.DependencyInfo(
            name="pkg",
            source="test",
            constraint="==1.0",
            current_min="1.0",
            latest_version="2.0",
            status=_dependencies.DependencyStatus.OUTDATED,
            original_spec="pkg==1.0",
        )

        result = _dependencies.build_updated_spec(dep)

        assert "==2.0" in result

    @pytest.mark.os_agnostic
    def test_tilde_equals(self) -> None:
        """build_updated_spec updates ~= constraints."""
        dep = _dependencies.DependencyInfo(
            name="pkg",
            source="test",
            constraint="~=1.4",
            current_min="1.4",
            latest_version="2.0",
            status=_dependencies.DependencyStatus.OUTDATED,
            original_spec="pkg~=1.4",
        )

        result = _dependencies.build_updated_spec(dep)

        assert "~=2.0" in result


class TestPrintReport:
    """Tests for print_report function."""

    def _make_dep(self, **overrides: Any) -> Any:
        """Build a DependencyInfo with sensible defaults."""
        defaults: dict[str, Any] = {
            "name": "pkg",
            "source": "[project].dependencies",
            "constraint": ">=1.0.0",
            "current_min": "1.0.0",
            "latest_version": "1.0.0",
            "status": _dependencies.DependencyStatus.UP_TO_DATE,
            "original_spec": "pkg>=1.0.0",
            "upper_bound": "",
        }
        defaults.update(overrides)
        return _dependencies.DependencyInfo(**defaults)

    @pytest.mark.os_agnostic
    def test_returns_zero_when_no_deps(self, capsys: CaptureFixture[str]) -> None:
        """print_report returns 0 for empty list."""
        result = _dependencies.print_report([])

        assert result == 0
        assert "No dependencies found" in capsys.readouterr().out

    @pytest.mark.os_agnostic
    def test_returns_zero_when_all_up_to_date(self, capsys: CaptureFixture[str]) -> None:
        """print_report returns 0 when all deps are up-to-date."""
        deps = [self._make_dep()]

        result = _dependencies.print_report(deps)

        assert result == 0

    @pytest.mark.os_agnostic
    def test_returns_one_when_any_outdated(self, capsys: CaptureFixture[str]) -> None:
        """print_report returns 1 when any dep is outdated."""
        deps = [self._make_dep(name="old-pkg", latest_version="2.0.0", status=_dependencies.DependencyStatus.OUTDATED)]

        result = _dependencies.print_report(deps)

        assert result == 1

    @pytest.mark.os_agnostic
    def test_verbose_shows_all_deps(self, capsys: CaptureFixture[str]) -> None:
        """print_report verbose mode shows up-to-date deps too."""
        deps = [
            self._make_dep(name="ok-pkg"),
            self._make_dep(name="old-pkg", latest_version="2.0.0", status=_dependencies.DependencyStatus.OUTDATED),
        ]

        _dependencies.print_report(deps, verbose=True)
        out = capsys.readouterr().out

        assert "ok-pkg" in out
        assert "old-pkg" in out

    @pytest.mark.os_agnostic
    def test_non_verbose_hides_up_to_date(self, capsys: CaptureFixture[str]) -> None:
        """print_report non-verbose mode hides up-to-date deps."""
        deps = [
            self._make_dep(name="ok-pkg"),
            self._make_dep(name="old-pkg", latest_version="2.0.0", status=_dependencies.DependencyStatus.OUTDATED),
        ]

        _dependencies.print_report(deps, verbose=False)
        out = capsys.readouterr().out

        assert "ok-pkg" not in out
        assert "old-pkg" in out

    @pytest.mark.os_agnostic
    def test_prints_summary_counts(self, capsys: CaptureFixture[str]) -> None:
        """print_report includes a summary section with counts."""
        deps = [
            self._make_dep(name="ok"),
            self._make_dep(name="old", latest_version="2.0.0", status=_dependencies.DependencyStatus.OUTDATED),
            self._make_dep(name="pinned", status=_dependencies.DependencyStatus.PINNED),
        ]

        _dependencies.print_report(deps)
        out = capsys.readouterr().out

        assert "Summary: 3 dependencies checked" in out
        assert "Up-to-date: 1" in out
        assert "Outdated:   1" in out
        assert "Pinned:     1" in out


class TestPrintInstallReport:
    """Tests for print_install_report function."""

    @pytest.mark.os_agnostic
    def test_shows_not_installed_label(self, capsys: CaptureFixture[str]) -> None:
        """print_install_report shows NOT INSTALLED for missing packages."""
        _dependencies.print_install_report([_dependencies.PendingInstall("mypkg", None, "1.0", "")], dry_run=False)
        out = capsys.readouterr().out

        assert "NOT INSTALLED" in out

    @pytest.mark.os_agnostic
    def test_shows_current_version(self, capsys: CaptureFixture[str]) -> None:
        """print_install_report shows installed version."""
        _dependencies.print_install_report([_dependencies.PendingInstall("mypkg", "0.9", "1.0", "")], dry_run=False)
        out = capsys.readouterr().out

        assert "0.9" in out
        assert ">=1.0" in out

    @pytest.mark.os_agnostic
    def test_dry_run_prefix(self, capsys: CaptureFixture[str]) -> None:
        """print_install_report prefixes output with [DRY RUN] in dry run mode."""
        _dependencies.print_install_report([_dependencies.PendingInstall("mypkg", None, "1.0", "")], dry_run=True)
        out = capsys.readouterr().out

        assert "[DRY RUN]" in out


class TestExtractDependenciesFromList:
    """Tests for extract_dependencies_from_list function."""

    @pytest.mark.os_agnostic
    def test_simple_up_to_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Up-to-date when latest equals minimum."""
        monkeypatch.setattr(
            _dependencies, "fetch_latest_version", fake_of(_dependencies.fetch_latest_version).returning("1.0.0")
        )

        results = _dependencies.extract_dependencies_from_list(["pkg>=1.0.0"], "test")

        assert len(results) == 1
        assert results[0].status == "up-to-date"

    @pytest.mark.os_agnostic
    def test_simple_outdated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outdated when latest exceeds minimum."""
        monkeypatch.setattr(
            _dependencies, "fetch_latest_version", fake_of(_dependencies.fetch_latest_version).returning("2.0.0")
        )

        results = _dependencies.extract_dependencies_from_list(["pkg>=1.0.0"], "test")

        assert results[0].status == "outdated"

    @pytest.mark.os_agnostic
    def test_package_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error status when fetch returns None."""
        monkeypatch.setattr(
            _dependencies, "fetch_latest_version", fake_of(_dependencies.fetch_latest_version).returning(None)
        )

        results = _dependencies.extract_dependencies_from_list(["pkg>=1.0.0"], "test")

        assert results[0].status == "error"
        assert results[0].latest_version is None
        assert results[0].latest_display == "not found"

    @pytest.mark.os_agnostic
    def test_no_constraint_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown status for bare package name without constraint."""
        monkeypatch.setattr(
            _dependencies, "fetch_latest_version", fake_of(_dependencies.fetch_latest_version).returning("1.0.0")
        )

        results = _dependencies.extract_dependencies_from_list(["mypackage"], "test")

        assert results[0].status == "unknown"

    @pytest.mark.os_agnostic
    def test_skips_empty_strings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty strings in the dependency list are skipped."""
        monkeypatch.setattr(
            _dependencies, "fetch_latest_version", fake_of(_dependencies.fetch_latest_version).returning("1.0.0")
        )

        results = _dependencies.extract_dependencies_from_list(["", "pkg>=1.0.0"], "test")

        assert len(results) == 1

    @pytest.mark.os_agnostic
    def test_upper_bound_pinned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pinned when latest exceeds upper bound and no version in range."""
        monkeypatch.setattr(
            _dependencies, "fetch_latest_version", fake_of(_dependencies.fetch_latest_version).returning("9.0.0")
        )
        monkeypatch.setattr(
            _dependencies,
            "fetch_latest_version_within",
            fake_of(_dependencies.fetch_latest_version_within).returning(None),
        )

        results = _dependencies.extract_dependencies_from_list(["pkg>=8.0.0,<9"], "test")

        assert results[0].status == "pinned"

    @pytest.mark.os_agnostic
    def test_upper_bound_outdated_within_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outdated when a newer version exists within the allowed range."""
        monkeypatch.setattr(
            _dependencies, "fetch_latest_version", fake_of(_dependencies.fetch_latest_version).returning("9.0.0")
        )
        monkeypatch.setattr(
            _dependencies,
            "fetch_latest_version_within",
            fake_of(_dependencies.fetch_latest_version_within).returning("8.5.0"),
        )

        results = _dependencies.extract_dependencies_from_list(["pkg>=8.0.0,<9"], "test")

        assert results[0].status == "outdated"


# =============================================================================
# _coverage.py - MIXED function tests
# =============================================================================


class TestResolveCommitSha:
    """Tests for resolve_commit_sha function."""

    @pytest.mark.os_agnostic
    def test_returns_github_sha_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns GITHUB_SHA env var when set."""
        monkeypatch.setenv("GITHUB_SHA", "abc123")

        result = _coverage.resolve_commit_sha()

        assert result == "abc123"

    @pytest.mark.os_agnostic
    def test_strips_whitespace_from_github_sha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Strips whitespace from GITHUB_SHA."""
        monkeypatch.setenv("GITHUB_SHA", "  abc123  \n")

        result = _coverage.resolve_commit_sha()

        assert result == "abc123"

    @pytest.mark.os_agnostic
    def test_falls_back_to_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to git rev-parse when no GITHUB_SHA."""
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="def456\n")
        monkeypatch.setattr(_coverage.subprocess, "run", _run_returning(fake))

        result = _coverage.resolve_commit_sha()

        assert result == "def456"

    @pytest.mark.os_agnostic
    def test_returns_none_on_git_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git rev-parse fails."""
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="fatal")
        monkeypatch.setattr(_coverage.subprocess, "run", _run_returning(fake))

        result = _coverage.resolve_commit_sha()

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_on_empty_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git output is empty."""
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="   \n")
        monkeypatch.setattr(_coverage.subprocess, "run", _run_returning(fake))

        result = _coverage.resolve_commit_sha()

        assert result is None


class TestResolveGitBranch:
    """Tests for resolve_git_branch function."""

    @pytest.mark.os_agnostic
    def test_returns_github_ref_name_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns GITHUB_REF_NAME env var when set."""
        monkeypatch.setenv("GITHUB_REF_NAME", "main")

        result = _coverage.resolve_git_branch()

        assert result == "main"

    @pytest.mark.os_agnostic
    def test_falls_back_to_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to git rev-parse --abbrev-ref when no GITHUB_REF_NAME."""
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="develop\n")
        monkeypatch.setattr(_coverage.subprocess, "run", _run_returning(fake))

        result = _coverage.resolve_git_branch()

        assert result == "develop"

    @pytest.mark.os_agnostic
    def test_returns_none_for_detached_head(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git reports detached HEAD."""
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="HEAD\n")
        monkeypatch.setattr(_coverage.subprocess, "run", _run_returning(fake))

        result = _coverage.resolve_git_branch()

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git command fails."""
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="fatal")
        monkeypatch.setattr(_coverage.subprocess, "run", _run_returning(fake))

        result = _coverage.resolve_git_branch()

        assert result is None


class TestCheckCodecovPrerequisites:
    """Tests for check_codecov_prerequisites function."""

    @pytest.mark.os_agnostic
    def test_returns_none_when_report_missing(self, tmp_path: Path) -> None:
        """Returns None when coverage report file does not exist."""
        result = _coverage.check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_when_no_token_no_ci(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when no token and not in CI."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.delenv("CI", raising=False)

        result = _coverage.check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_when_codecovcli_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when codecovcli is not on PATH."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.setenv("CODECOV_TOKEN", "tok")
        monkeypatch.setattr(_coverage.shutil, "which", _which_returning(None))

        result = _coverage.check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_path_when_all_met(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns uploader path when all prerequisites are met."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.setenv("CODECOV_TOKEN", "tok")
        monkeypatch.setattr(_coverage.shutil, "which", _which_returning("/usr/bin/codecovcli"))

        result = _coverage.check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result == "/usr/bin/codecovcli"

    @pytest.mark.os_agnostic
    def test_accepts_ci_env_without_token(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CI environment is sufficient without explicit token."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.setenv("CI", "true")
        monkeypatch.setattr(_coverage.shutil, "which", _which_returning("/usr/bin/codecovcli"))

        result = _coverage.check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result == "/usr/bin/codecovcli"

    @pytest.mark.os_agnostic
    def test_accepts_passed_token_param(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accepts codecov_token kwarg as alternative to env var."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setattr(_coverage.shutil, "which", _which_returning("/usr/bin/codecovcli"))

        result = _coverage.check_codecov_prerequisites(tmp_path, "coverage.xml", codecov_token="my-token")

        assert result == "/usr/bin/codecovcli"


class TestBuildCodecovArgs:
    """Tests for build_codecov_args function."""

    @pytest.mark.os_agnostic
    def test_includes_required_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Required args (file, sha, name) are always present."""
        monkeypatch.setattr(_coverage, "resolve_git_branch", fake_of(_coverage.resolve_git_branch).returning(None))

        args = _coverage.build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            coverage_report_file="coverage.xml",
        )

        assert "--file" in args
        assert "coverage.xml" in args
        assert "--sha" in args
        assert "abc123" in args
        assert "--name" in args

    @pytest.mark.os_agnostic
    def test_includes_branch_when_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Includes --branch when git branch is resolved."""
        monkeypatch.setattr(_coverage, "resolve_git_branch", fake_of(_coverage.resolve_git_branch).returning("main"))

        args = _coverage.build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
        )

        assert "--branch" in args
        assert "main" in args

    @pytest.mark.os_agnostic
    def test_includes_git_service_for_known_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Includes --git-service for known hosts."""
        monkeypatch.setattr(_coverage, "resolve_git_branch", fake_of(_coverage.resolve_git_branch).returning(None))

        args = _coverage.build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            remote=_coverage.RepoRemote("github.com", "", ""),
        )

        assert "--git-service" in args
        assert "github" in args

    @pytest.mark.os_agnostic
    def test_includes_slug_when_complete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Includes --slug when owner and name are both present."""
        monkeypatch.setattr(_coverage, "resolve_git_branch", fake_of(_coverage.resolve_git_branch).returning(None))

        args = _coverage.build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            remote=_coverage.RepoRemote("", "myorg", "myrepo"),
        )

        assert "--slug" in args
        assert "myorg/myrepo" in args

    @pytest.mark.os_agnostic
    def test_excludes_optional_when_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Omits --branch, --git-service, --slug when values are None."""
        monkeypatch.setattr(_coverage, "resolve_git_branch", fake_of(_coverage.resolve_git_branch).returning(None))

        args = _coverage.build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            remote=_coverage.RepoRemote("unknown.example.com", "", ""),
        )

        assert "--branch" not in args
        assert "--git-service" not in args
        assert "--slug" not in args
