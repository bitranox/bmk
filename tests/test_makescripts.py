"""Unit tests for makescripts modules.

Tests pure functions and logic that can be unit tested without external
dependencies (subprocess calls, network requests, etc.).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pytest import CaptureFixture


# =============================================================================
# _coverage.py tests
# =============================================================================


class TestCoverageConfig:
    """Tests for CoverageConfig dataclass."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_from_pyproject_returns_defaults_when_file_missing(self, coverage_module: Any, tmp_path: Path) -> None:
        """CoverageConfig returns defaults when pyproject.toml doesn't exist."""
        config = coverage_module.CoverageConfig.from_pyproject(tmp_path)

        assert config.pytest_verbosity == "-v"
        assert config.coverage_report_file == "coverage.xml"
        assert config.src_path == "src"
        assert config.fail_under == 80
        assert config.coverage_source == ["src"]
        assert config.exclude_markers == "integration"

    @pytest.mark.os_agnostic
    def test_from_pyproject_loads_values_from_toml(self, coverage_module: Any, tmp_path: Path) -> None:
        """CoverageConfig loads values from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.scripts]
pytest_verbosity = "-vv"
coverage_report_file = "custom.xml"
src_path = "lib"
exclude_markers = "slow"

[tool.coverage.run]
source = ["lib/mypackage"]

[tool.coverage.report]
fail_under = 95
"""
        )

        config = coverage_module.CoverageConfig.from_pyproject(tmp_path)

        assert config.pytest_verbosity == "-vv"
        assert config.coverage_report_file == "custom.xml"
        assert config.src_path == "lib"
        assert config.fail_under == 95
        assert config.coverage_source == ["lib/mypackage"]
        assert config.exclude_markers == "slow"

    @pytest.mark.os_agnostic
    def test_from_pyproject_uses_defaults_for_missing_keys(self, coverage_module: Any, tmp_path: Path) -> None:
        """CoverageConfig uses defaults for missing keys in pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.coverage.report]
fail_under = 85
"""
        )

        config = coverage_module.CoverageConfig.from_pyproject(tmp_path)

        assert config.pytest_verbosity == "-v"
        assert config.fail_under == 85
        assert config.coverage_source == ["src"]


class TestCoverageFileManagement:
    """Tests for coverage file cleanup functions."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_prune_coverage_data_files_removes_coverage_files(self, coverage_module: Any, tmp_path: Path) -> None:
        """prune_coverage_data_files removes .coverage* files."""
        # Create test files
        (tmp_path / ".coverage").write_text("data")
        (tmp_path / ".coverage.abc123").write_text("data")
        (tmp_path / ".coverage.xml").write_text("data")  # Should NOT be removed

        coverage_module.prune_coverage_data_files(tmp_path)

        assert not (tmp_path / ".coverage").exists()
        assert not (tmp_path / ".coverage.abc123").exists()
        assert (tmp_path / ".coverage.xml").exists()  # XML preserved

    @pytest.mark.os_agnostic
    def test_prune_coverage_data_files_ignores_directories(self, coverage_module: Any, tmp_path: Path) -> None:
        """prune_coverage_data_files doesn't remove directories."""
        coverage_dir = tmp_path / ".coverage_dir"
        coverage_dir.mkdir()
        (coverage_dir / "file.txt").write_text("data")

        coverage_module.prune_coverage_data_files(tmp_path)

        assert coverage_dir.exists()
        assert (coverage_dir / "file.txt").exists()

    @pytest.mark.os_agnostic
    def test_remove_report_artifacts_removes_report_files(self, coverage_module: Any, tmp_path: Path) -> None:
        """remove_report_artifacts removes coverage report files."""
        (tmp_path / "coverage.xml").write_text("data")
        (tmp_path / "codecov.xml").write_text("data")
        (tmp_path / "other.xml").write_text("data")  # Should NOT be removed

        coverage_module.remove_report_artifacts(tmp_path)

        assert not (tmp_path / "coverage.xml").exists()
        assert not (tmp_path / "codecov.xml").exists()
        assert (tmp_path / "other.xml").exists()

    @pytest.mark.os_agnostic
    def test_remove_report_artifacts_uses_custom_report_name(self, coverage_module: Any, tmp_path: Path) -> None:
        """remove_report_artifacts removes custom-named report file."""
        (tmp_path / "custom.xml").write_text("data")
        (tmp_path / "coverage.xml").write_text("data")  # Should NOT be removed

        coverage_module.remove_report_artifacts(tmp_path, "custom.xml")

        assert not (tmp_path / "custom.xml").exists()
        assert (tmp_path / "coverage.xml").exists()


class TestBuildEnv:
    """Tests for _build_env function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_build_env_adds_src_to_pythonpath(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_build_env adds src path to PYTHONPATH."""
        monkeypatch.delenv("PYTHONPATH", raising=False)

        env = coverage_module._build_env(tmp_path, "src")

        assert str(tmp_path / "src") in env["PYTHONPATH"]

    @pytest.mark.os_agnostic
    def test_build_env_preserves_existing_pythonpath(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_build_env preserves existing PYTHONPATH."""
        monkeypatch.setenv("PYTHONPATH", "/existing/path")

        env = coverage_module._build_env(tmp_path, "src")

        assert "/existing/path" in env["PYTHONPATH"]
        assert str(tmp_path / "src") in env["PYTHONPATH"]


class TestEnsureCodecovToken:
    """Tests for ensure_codecov_token function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_returns_existing_token_from_environment(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ensure_codecov_token returns token when CODECOV_TOKEN is set."""
        monkeypatch.setenv("CODECOV_TOKEN", "existing-token")

        result = coverage_module.ensure_codecov_token(tmp_path)

        assert result == "existing-token"

    @pytest.mark.os_agnostic
    def test_returns_none_when_env_file_missing(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ensure_codecov_token returns None when no .env file in hierarchy."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.setattr(coverage_module, "_find_dotenv_upward", lambda _start: None)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module.ensure_codecov_token(tmp_path)

        assert result is None

    @pytest.mark.os_agnostic
    def test_loads_token_from_env_file(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ensure_codecov_token loads token from .env file without mutating os.environ."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("CODECOV_TOKEN=my-secret-token\n")

        result = coverage_module.ensure_codecov_token(tmp_path)

        assert result == "my-secret-token"
        assert os.environ.get("CODECOV_TOKEN") is None

    @pytest.mark.os_agnostic
    def test_handles_quoted_token_values(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ensure_codecov_token handles quoted token values."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text('CODECOV_TOKEN="quoted-token"\n')

        result = coverage_module.ensure_codecov_token(tmp_path)

        assert result == "quoted-token"
        assert os.environ.get("CODECOV_TOKEN") is None

    @pytest.mark.os_agnostic
    def test_skips_comments_and_empty_lines(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

        result = coverage_module.ensure_codecov_token(tmp_path)

        assert result == "found-token"
        assert os.environ.get("CODECOV_TOKEN") is None

    @pytest.mark.os_agnostic
    def test_finds_env_file_in_parent_directory(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ensure_codecov_token finds .env in a parent directory."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("CODECOV_TOKEN=parent-token\n")
        child_dir = tmp_path / "sub" / "deep"
        child_dir.mkdir(parents=True)

        result = coverage_module.ensure_codecov_token(child_dir)

        assert result == "parent-token"
        assert os.environ.get("CODECOV_TOKEN") is None


class TestFindDotenvUpward:
    """Tests for _find_dotenv_upward helper."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_finds_env_in_start_dir(self, coverage_module: Any, tmp_path: Path) -> None:
        """_find_dotenv_upward finds .env in the start directory."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")

        result = coverage_module._find_dotenv_upward(tmp_path)

        assert result == env_file

    @pytest.mark.os_agnostic
    def test_finds_env_in_parent(self, coverage_module: Any, tmp_path: Path) -> None:
        """_find_dotenv_upward finds .env in a parent directory."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        child = tmp_path / "a" / "b"
        child.mkdir(parents=True)

        result = coverage_module._find_dotenv_upward(child)

        assert result == env_file

    @pytest.mark.os_agnostic
    def test_returns_none_when_no_env_file(self, coverage_module: Any, tmp_path: Path) -> None:
        """_find_dotenv_upward returns None when no .env exists in hierarchy."""
        child = tmp_path / "empty"
        child.mkdir()

        result = coverage_module._find_dotenv_upward(child)

        # May return None or find a .env above tmp_path — assert type is correct
        assert result is None or result.name == ".env"


class TestGitServiceHelpers:
    """Tests for git service helper functions."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

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
    def test_resolve_git_service_maps_hosts(self, coverage_module: Any, host: str | None, expected: str | None) -> None:
        """_resolve_git_service maps host names to service identifiers."""
        assert coverage_module._resolve_git_service(host) == expected

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("owner", "name", "expected"),
        [
            ("myorg", "myrepo", "myorg/myrepo"),
            ("user", "project", "user/project"),
            (None, "myrepo", None),
            ("myorg", None, None),
            (None, None, None),
            ("", "myrepo", None),
            ("myorg", "", None),
        ],
    )
    def test_get_repo_slug_builds_slug(
        self, coverage_module: Any, owner: str | None, name: str | None, expected: str | None
    ) -> None:
        """_get_repo_slug builds owner/name slug."""
        assert coverage_module._get_repo_slug(owner, name) == expected


class TestBuildCodecovEnv:
    """Tests for _build_codecov_env function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_always_sets_no_combine(self, coverage_module: Any) -> None:
        """_build_codecov_env always sets CODECOV_NO_COMBINE."""
        env = coverage_module._build_codecov_env(None, None)

        assert env["CODECOV_NO_COMBINE"] == "1"

    @pytest.mark.os_agnostic
    def test_sets_slug_when_owner_and_name_provided(self, coverage_module: Any) -> None:
        """_build_codecov_env sets CODECOV_SLUG when owner and name provided."""
        env = coverage_module._build_codecov_env("myorg", "myrepo")

        assert env["CODECOV_SLUG"] == "myorg/myrepo"


class TestHandleCodecovResult:
    """Tests for _handle_codecov_result function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_returns_true_on_success(self, coverage_module: Any, capsys: CaptureFixture[str]) -> None:
        """_handle_codecov_result returns True on exit code 0."""
        result = coverage_module._handle_codecov_result(0)

        assert result is True
        captured = capsys.readouterr()
        assert "upload succeeded" in captured.out

    @pytest.mark.os_agnostic
    def test_returns_false_on_failure(self, coverage_module: Any, capsys: CaptureFixture[str]) -> None:
        """_handle_codecov_result returns False on non-zero exit code."""
        result = coverage_module._handle_codecov_result(1)

        assert result is False
        captured = capsys.readouterr()
        assert "upload failed" in captured.err


class TestMain:
    """Tests for main() orchestrator function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_main_returns_zero_when_token_missing(
        self,
        coverage_module: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        """main() returns 0 and prints warning when CODECOV_TOKEN is missing."""
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.setattr(coverage_module, "_find_dotenv_upward", lambda _start: None)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module.main(
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

    @pytest.fixture
    def clean_module(self) -> Any:
        """Import clean module."""
        from bmk.makescripts import _clean

        return _clean

    @pytest.mark.os_agnostic
    def test_get_clean_patterns_returns_fallback_when_no_pyproject(self, clean_module: Any, tmp_path: Path) -> None:
        """get_clean_patterns returns fallback patterns when pyproject.toml missing."""
        patterns = clean_module.get_clean_patterns(tmp_path / "pyproject.toml")

        assert ".pytest_cache" in patterns
        assert ".ruff_cache" in patterns
        assert "build" in patterns
        assert "dist" in patterns

    @pytest.mark.os_agnostic
    def test_get_clean_patterns_loads_from_pyproject(self, clean_module: Any, tmp_path: Path) -> None:
        """get_clean_patterns loads patterns from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            """
[tool.clean]
patterns = ["custom_cache", "*.tmp"]
"""
        )

        patterns = clean_module.get_clean_patterns(pyproject)

        assert "custom_cache" in patterns
        assert "*.tmp" in patterns


class TestCleanFunction:
    """Tests for clean function."""

    @pytest.fixture
    def clean_module(self) -> Any:
        """Import clean module."""
        from bmk.makescripts import _clean

        return _clean

    @pytest.mark.os_agnostic
    def test_clean_removes_matching_directories(self, clean_module: Any, tmp_path: Path) -> None:
        """clean removes directories matching patterns."""
        cache_dir = tmp_path / ".pytest_cache"
        cache_dir.mkdir()
        (cache_dir / "data.txt").write_text("cached")

        clean_module.clean(project_dir=tmp_path, patterns=[".pytest_cache"], verbose=False)

        assert not cache_dir.exists()

    @pytest.mark.os_agnostic
    def test_clean_removes_matching_files(self, clean_module: Any, tmp_path: Path) -> None:
        """clean removes files matching patterns."""
        (tmp_path / "coverage.xml").write_text("data")

        clean_module.clean(project_dir=tmp_path, patterns=["coverage.xml"], verbose=False)

        assert not (tmp_path / "coverage.xml").exists()

    @pytest.mark.os_agnostic
    def test_clean_dry_run_does_not_remove(
        self, clean_module: Any, tmp_path: Path, capsys: CaptureFixture[str]
    ) -> None:
        """clean with dry_run=True doesn't remove anything."""
        cache_dir = tmp_path / ".pytest_cache"
        cache_dir.mkdir()

        clean_module.clean(project_dir=tmp_path, patterns=[".pytest_cache"], dry_run=True)

        assert cache_dir.exists()
        captured = capsys.readouterr()
        assert "[DRY RUN]" in captured.out

    @pytest.mark.os_agnostic
    def test_clean_verbose_outputs_each_removal(
        self, clean_module: Any, tmp_path: Path, capsys: CaptureFixture[str]
    ) -> None:
        """clean with verbose=True outputs each removal."""
        (tmp_path / "coverage.xml").write_text("data")

        clean_module.clean(project_dir=tmp_path, patterns=["coverage.xml"], verbose=True)

        captured = capsys.readouterr()
        assert "Removing file:" in captured.out


# =============================================================================
# _dependencies.py tests
# =============================================================================


class TestDependencyVersionParsing:
    """Tests for version parsing functions."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

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
    def test_normalize_name_handles_variations(self, deps_module: Any, name: str, expected: str) -> None:
        """_normalize_name normalizes package names per PEP 503."""
        assert deps_module._normalize_name(name) == expected

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
        deps_module: Any,
        spec: str,
        expected_name: str,
        expected_constraint: str,
        expected_min: str,
        expected_upper: str,
    ) -> None:
        """_parse_version_constraint extracts name, constraint, min, and upper bound."""
        name, constraint, min_ver, upper = deps_module._parse_version_constraint(spec)

        assert name == expected_name
        assert constraint == expected_constraint
        assert min_ver == expected_min
        assert upper == expected_upper

    @pytest.mark.os_agnostic
    def test_parse_version_constraint_handles_empty_string(self, deps_module: Any) -> None:
        """_parse_version_constraint handles empty string."""
        name, constraint, min_ver, upper = deps_module._parse_version_constraint("")

        assert name == ""
        assert constraint == ""
        assert min_ver == ""
        assert upper == ""


class TestVersionComparison:
    """Tests for version comparison functions."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

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
    def test_parse_version_tuple_extracts_numeric_parts(
        self, deps_module: Any, version: str, expected: tuple[int, ...]
    ) -> None:
        """_parse_version_tuple extracts numeric version parts."""
        assert deps_module._parse_version_tuple(version) == expected

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
    def test_version_gte_compares_correctly(
        self, deps_module: Any, version_a: str, version_b: str, expected: bool
    ) -> None:
        """_version_gte correctly compares versions."""
        assert deps_module._version_gte(version_a, version_b) == expected

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
    def test_compare_versions_returns_correct_status(
        self, deps_module: Any, current: str, latest: str, expected: str
    ) -> None:
        """compare_versions returns correct status."""
        assert deps_module.compare_versions(current, latest) == expected


class TestStatusIcon:
    """Tests for _get_status_icon function."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("up-to-date", "[ok]"),
            ("outdated", "[!!]"),
            ("pinned", "[==]"),
            ("unknown", "[??]"),
            ("error", "[XX]"),
            ("invalid", "[??]"),
        ],
    )
    def test_get_status_icon_returns_correct_icon(self, deps_module: Any, status: str, expected: str) -> None:
        """_get_status_icon returns correct icon for status."""
        assert deps_module._get_status_icon(status) == expected


class TestBuildUpdatedSpec:
    """Tests for _build_updated_spec function."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

    @pytest.mark.os_agnostic
    def test_updates_version_constraint(self, deps_module: Any) -> None:
        """_build_updated_spec updates version in constraint."""
        dep = deps_module.DependencyInfo(
            name="pytest",
            source="test",
            constraint=">=8.0.0",
            current_min="8.0.0",
            latest="9.0.0",
            status="outdated",
            original_spec="pytest>=8.0.0",
        )

        result = deps_module._build_updated_spec(dep)

        assert result == "pytest>=9.0.0"

    @pytest.mark.os_agnostic
    def test_preserves_environment_markers(self, deps_module: Any) -> None:
        """_build_updated_spec preserves environment markers."""
        dep = deps_module.DependencyInfo(
            name="tomli",
            source="test",
            constraint=">=2.0.0",
            current_min="2.0.0",
            latest="2.1.0",
            status="outdated",
            original_spec="tomli>=2.0.0; python_version<'3.11'",
        )

        result = deps_module._build_updated_spec(dep)

        assert "; python_version<'3.11'" in result
        assert ">=2.1.0" in result

    @pytest.mark.os_agnostic
    def test_returns_original_when_latest_not_found(self, deps_module: Any) -> None:
        """_build_updated_spec returns original when latest is 'not found'."""
        dep = deps_module.DependencyInfo(
            name="unknown",
            source="test",
            constraint=">=1.0.0",
            current_min="1.0.0",
            latest="not found",
            status="error",
            original_spec="unknown>=1.0.0",
        )

        result = deps_module._build_updated_spec(dep)

        assert result == "unknown>=1.0.0"


class TestBuildUpdatedSpecExtended:
    """Additional edge cases for _build_updated_spec."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

    @pytest.mark.os_agnostic
    def test_preserves_extras(self, deps_module: Any) -> None:
        """_build_updated_spec preserves extras bracket notation."""
        dep = deps_module.DependencyInfo(
            name="pkg",
            source="test",
            constraint=">=1.0",
            current_min="1.0",
            latest="2.0",
            status="outdated",
            original_spec="pkg[extra]>=1.0",
        )

        result = deps_module._build_updated_spec(dep)

        assert "[extra]" in result
        assert ">=2.0" in result

    @pytest.mark.os_agnostic
    def test_adds_constraint_to_bare_name(self, deps_module: Any) -> None:
        """_build_updated_spec adds >=latest to a bare package name."""
        dep = deps_module.DependencyInfo(
            name="mypackage",
            source="test",
            constraint="",
            current_min="",
            latest="2.0",
            status="outdated",
            original_spec="mypackage",
        )

        result = deps_module._build_updated_spec(dep)

        assert "mypackage" in result
        assert ">=2.0" in result

    @pytest.mark.os_agnostic
    def test_double_equals(self, deps_module: Any) -> None:
        """_build_updated_spec updates == constraints."""
        dep = deps_module.DependencyInfo(
            name="pkg",
            source="test",
            constraint="==1.0",
            current_min="1.0",
            latest="2.0",
            status="outdated",
            original_spec="pkg==1.0",
        )

        result = deps_module._build_updated_spec(dep)

        assert "==2.0" in result

    @pytest.mark.os_agnostic
    def test_tilde_equals(self, deps_module: Any) -> None:
        """_build_updated_spec updates ~= constraints."""
        dep = deps_module.DependencyInfo(
            name="pkg",
            source="test",
            constraint="~=1.4",
            current_min="1.4",
            latest="2.0",
            status="outdated",
            original_spec="pkg~=1.4",
        )

        result = deps_module._build_updated_spec(dep)

        assert "~=2.0" in result


class TestPrintReport:
    """Tests for print_report function."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

    def _make_dep(self, deps_module: Any, **overrides: Any) -> Any:
        """Build a DependencyInfo with sensible defaults."""
        defaults = {
            "name": "pkg",
            "source": "[project].dependencies",
            "constraint": ">=1.0.0",
            "current_min": "1.0.0",
            "latest": "1.0.0",
            "status": "up-to-date",
            "original_spec": "pkg>=1.0.0",
            "upper_bound": "",
        }
        defaults.update(overrides)
        return deps_module.DependencyInfo(**defaults)

    @pytest.mark.os_agnostic
    def test_returns_zero_when_no_deps(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """print_report returns 0 for empty list."""
        result = deps_module.print_report([])

        assert result == 0
        assert "No dependencies found" in capsys.readouterr().out

    @pytest.mark.os_agnostic
    def test_returns_zero_when_all_up_to_date(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """print_report returns 0 when all deps are up-to-date."""
        deps = [self._make_dep(deps_module)]

        result = deps_module.print_report(deps)

        assert result == 0

    @pytest.mark.os_agnostic
    def test_returns_one_when_any_outdated(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """print_report returns 1 when any dep is outdated."""
        deps = [self._make_dep(deps_module, name="old-pkg", latest="2.0.0", status="outdated")]

        result = deps_module.print_report(deps)

        assert result == 1

    @pytest.mark.os_agnostic
    def test_verbose_shows_all_deps(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """print_report verbose mode shows up-to-date deps too."""
        deps = [
            self._make_dep(deps_module, name="ok-pkg"),
            self._make_dep(deps_module, name="old-pkg", latest="2.0.0", status="outdated"),
        ]

        deps_module.print_report(deps, verbose=True)
        out = capsys.readouterr().out

        assert "ok-pkg" in out
        assert "old-pkg" in out

    @pytest.mark.os_agnostic
    def test_non_verbose_hides_up_to_date(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """print_report non-verbose mode hides up-to-date deps."""
        deps = [
            self._make_dep(deps_module, name="ok-pkg"),
            self._make_dep(deps_module, name="old-pkg", latest="2.0.0", status="outdated"),
        ]

        deps_module.print_report(deps, verbose=False)
        out = capsys.readouterr().out

        assert "ok-pkg" not in out
        assert "old-pkg" in out

    @pytest.mark.os_agnostic
    def test_prints_summary_counts(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """print_report includes a summary section with counts."""
        deps = [
            self._make_dep(deps_module, name="ok"),
            self._make_dep(deps_module, name="old", latest="2.0.0", status="outdated"),
            self._make_dep(deps_module, name="pinned", status="pinned"),
        ]

        deps_module.print_report(deps)
        out = capsys.readouterr().out

        assert "Summary: 3 dependencies checked" in out
        assert "Up-to-date: 1" in out
        assert "Outdated:   1" in out
        assert "Pinned:     1" in out


class TestPrintInstallReport:
    """Tests for _print_install_report function."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

    @pytest.mark.os_agnostic
    def test_shows_not_installed_label(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """_print_install_report shows NOT INSTALLED for missing packages."""
        deps_module._print_install_report([("mypkg", None, "1.0")], dry_run=False)
        out = capsys.readouterr().out

        assert "NOT INSTALLED" in out

    @pytest.mark.os_agnostic
    def test_shows_current_version(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """_print_install_report shows installed version."""
        deps_module._print_install_report([("mypkg", "0.9", "1.0")], dry_run=False)
        out = capsys.readouterr().out

        assert "0.9" in out
        assert ">=1.0" in out

    @pytest.mark.os_agnostic
    def test_dry_run_prefix(self, deps_module: Any, capsys: CaptureFixture[str]) -> None:
        """_print_install_report prefixes output with [DRY RUN] in dry run mode."""
        deps_module._print_install_report([("mypkg", None, "1.0")], dry_run=True)
        out = capsys.readouterr().out

        assert "[DRY RUN]" in out


class TestExtractDependenciesFromList:
    """Tests for _extract_dependencies_from_list function."""

    @pytest.fixture
    def deps_module(self) -> Any:
        """Import dependencies module."""
        from bmk.makescripts import _dependencies

        return _dependencies

    @pytest.mark.os_agnostic
    def test_simple_up_to_date(self, deps_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Up-to-date when latest equals minimum."""
        monkeypatch.setattr(deps_module, "fetch_latest_version", lambda _name: "1.0.0")  # type: ignore[reportUnknownLambdaType]

        results = deps_module._extract_dependencies_from_list(["pkg>=1.0.0"], "test")

        assert len(results) == 1
        assert results[0].status == "up-to-date"

    @pytest.mark.os_agnostic
    def test_simple_outdated(self, deps_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outdated when latest exceeds minimum."""
        monkeypatch.setattr(deps_module, "fetch_latest_version", lambda _name: "2.0.0")  # type: ignore[reportUnknownLambdaType]

        results = deps_module._extract_dependencies_from_list(["pkg>=1.0.0"], "test")

        assert results[0].status == "outdated"

    @pytest.mark.os_agnostic
    def test_package_not_found(self, deps_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error status when fetch returns None."""
        monkeypatch.setattr(deps_module, "fetch_latest_version", lambda _name: None)  # type: ignore[reportUnknownLambdaType]

        results = deps_module._extract_dependencies_from_list(["pkg>=1.0.0"], "test")

        assert results[0].status == "error"
        assert results[0].latest == "not found"

    @pytest.mark.os_agnostic
    def test_no_constraint_is_unknown(self, deps_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown status for bare package name without constraint."""
        monkeypatch.setattr(deps_module, "fetch_latest_version", lambda _name: "1.0.0")  # type: ignore[reportUnknownLambdaType]

        results = deps_module._extract_dependencies_from_list(["mypackage"], "test")

        assert results[0].status == "unknown"

    @pytest.mark.os_agnostic
    def test_skips_empty_strings(self, deps_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty strings in the dependency list are skipped."""
        monkeypatch.setattr(deps_module, "fetch_latest_version", lambda _name: "1.0.0")  # type: ignore[reportUnknownLambdaType]

        results = deps_module._extract_dependencies_from_list(["", "pkg>=1.0.0"], "test")

        assert len(results) == 1

    @pytest.mark.os_agnostic
    def test_upper_bound_pinned(self, deps_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pinned when latest exceeds upper bound and no version in range."""
        monkeypatch.setattr(deps_module, "fetch_latest_version", lambda _name: "9.0.0")  # type: ignore[reportUnknownLambdaType]
        monkeypatch.setattr(deps_module, "_fetch_latest_version_below", lambda _name, _bound: None)  # type: ignore[reportUnknownLambdaType]

        results = deps_module._extract_dependencies_from_list(["pkg>=8.0.0,<9"], "test")

        assert results[0].status == "pinned"

    @pytest.mark.os_agnostic
    def test_upper_bound_outdated_within_range(self, deps_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Outdated when a newer version exists within the allowed range."""
        monkeypatch.setattr(deps_module, "fetch_latest_version", lambda _name: "9.0.0")  # type: ignore[reportUnknownLambdaType]
        monkeypatch.setattr(deps_module, "_fetch_latest_version_below", lambda _name, _bound: "8.5.0")  # type: ignore[reportUnknownLambdaType]

        results = deps_module._extract_dependencies_from_list(["pkg>=8.0.0,<9"], "test")

        assert results[0].status == "outdated"


# =============================================================================
# _coverage.py — MIXED function tests
# =============================================================================


class TestResolveCommitSha:
    """Tests for _resolve_commit_sha function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_returns_github_sha_env(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns GITHUB_SHA env var when set."""
        monkeypatch.setenv("GITHUB_SHA", "abc123")

        result = coverage_module._resolve_commit_sha()

        assert result == "abc123"

    @pytest.mark.os_agnostic
    def test_strips_whitespace_from_github_sha(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Strips whitespace from GITHUB_SHA."""
        monkeypatch.setenv("GITHUB_SHA", "  abc123  \n")

        result = coverage_module._resolve_commit_sha()

        assert result == "abc123"

    @pytest.mark.os_agnostic
    def test_falls_back_to_git(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to git rev-parse when no GITHUB_SHA."""
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="def456\n")
        monkeypatch.setattr(coverage_module.subprocess, "run", lambda *_a, **_kw: fake)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._resolve_commit_sha()

        assert result == "def456"

    @pytest.mark.os_agnostic
    def test_returns_none_on_git_failure(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git rev-parse fails."""
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="fatal")
        monkeypatch.setattr(coverage_module.subprocess, "run", lambda *_a, **_kw: fake)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._resolve_commit_sha()

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_on_empty_output(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git output is empty."""
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="   \n")
        monkeypatch.setattr(coverage_module.subprocess, "run", lambda *_a, **_kw: fake)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._resolve_commit_sha()

        assert result is None


class TestResolveGitBranch:
    """Tests for _resolve_git_branch function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_returns_github_ref_name_env(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns GITHUB_REF_NAME env var when set."""
        monkeypatch.setenv("GITHUB_REF_NAME", "main")

        result = coverage_module._resolve_git_branch()

        assert result == "main"

    @pytest.mark.os_agnostic
    def test_falls_back_to_git(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to git rev-parse --abbrev-ref when no GITHUB_REF_NAME."""
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="develop\n")
        monkeypatch.setattr(coverage_module.subprocess, "run", lambda *_a, **_kw: fake)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._resolve_git_branch()

        assert result == "develop"

    @pytest.mark.os_agnostic
    def test_returns_none_for_detached_head(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git reports detached HEAD."""
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
        fake = subprocess.CompletedProcess([], 0, stdout="HEAD\n")
        monkeypatch.setattr(coverage_module.subprocess, "run", lambda *_a, **_kw: fake)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._resolve_git_branch()

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_on_failure(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when git command fails."""
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
        fake = subprocess.CompletedProcess([], 1, stdout="", stderr="fatal")
        monkeypatch.setattr(coverage_module.subprocess, "run", lambda *_a, **_kw: fake)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._resolve_git_branch()

        assert result is None


class TestCheckCodecovPrerequisites:
    """Tests for _check_codecov_prerequisites function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_returns_none_when_report_missing(self, coverage_module: Any, tmp_path: Path) -> None:
        """Returns None when coverage report file does not exist."""
        result = coverage_module._check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_when_no_token_no_ci(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns None when no token and not in CI."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.delenv("CI", raising=False)

        result = coverage_module._check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_none_when_codecovcli_missing(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns None when codecovcli is not on PATH."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.setenv("CODECOV_TOKEN", "tok")
        monkeypatch.setattr(coverage_module.shutil, "which", lambda _name: None)  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result is None

    @pytest.mark.os_agnostic
    def test_returns_path_when_all_met(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns uploader path when all prerequisites are met."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.setenv("CODECOV_TOKEN", "tok")
        monkeypatch.setattr(coverage_module.shutil, "which", lambda _name: "/usr/bin/codecovcli")  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result == "/usr/bin/codecovcli"

    @pytest.mark.os_agnostic
    def test_accepts_ci_env_without_token(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CI environment is sufficient without explicit token."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.setenv("CI", "true")
        monkeypatch.setattr(coverage_module.shutil, "which", lambda _name: "/usr/bin/codecovcli")  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._check_codecov_prerequisites(tmp_path, "coverage.xml")

        assert result == "/usr/bin/codecovcli"

    @pytest.mark.os_agnostic
    def test_accepts_passed_token_param(
        self, coverage_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Accepts codecov_token kwarg as alternative to env var."""
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        monkeypatch.delenv("CODECOV_TOKEN", raising=False)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setattr(coverage_module.shutil, "which", lambda _name: "/usr/bin/codecovcli")  # type: ignore[reportUnknownLambdaType]

        result = coverage_module._check_codecov_prerequisites(tmp_path, "coverage.xml", codecov_token="my-token")

        assert result == "/usr/bin/codecovcli"


class TestBuildCodecovArgs:
    """Tests for _build_codecov_args function."""

    @pytest.fixture
    def coverage_module(self) -> Any:
        """Import coverage module."""
        from bmk.makescripts import _coverage

        return _coverage

    @pytest.mark.os_agnostic
    def test_includes_required_args(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Required args (file, sha, name) are always present."""
        monkeypatch.setattr(coverage_module, "_resolve_git_branch", lambda: None)

        args = coverage_module._build_codecov_args(
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
    def test_includes_branch_when_resolved(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Includes --branch when git branch is resolved."""
        monkeypatch.setattr(coverage_module, "_resolve_git_branch", lambda: "main")

        args = coverage_module._build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
        )

        assert "--branch" in args
        assert "main" in args

    @pytest.mark.os_agnostic
    def test_includes_git_service_for_known_host(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Includes --git-service for known hosts."""
        monkeypatch.setattr(coverage_module, "_resolve_git_branch", lambda: None)

        args = coverage_module._build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            repo_host="github.com",
        )

        assert "--git-service" in args
        assert "github" in args

    @pytest.mark.os_agnostic
    def test_includes_slug_when_complete(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Includes --slug when owner and name are both present."""
        monkeypatch.setattr(coverage_module, "_resolve_git_branch", lambda: None)

        args = coverage_module._build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            repo_owner="myorg",
            repo_name="myrepo",
        )

        assert "--slug" in args
        assert "myorg/myrepo" in args

    @pytest.mark.os_agnostic
    def test_excludes_optional_when_none(self, coverage_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Omits --branch, --git-service, --slug when values are None."""
        monkeypatch.setattr(coverage_module, "_resolve_git_branch", lambda: None)

        args = coverage_module._build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            repo_host="unknown.example.com",
            repo_owner=None,
            repo_name=None,
        )

        assert "--branch" not in args
        assert "--git-service" not in args
        assert "--slug" not in args
