"""Unit tests for _bump_version.py version bumping logic."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import pytest

from bmk.domain.enums import BumpPart

if TYPE_CHECKING:
    from pathlib import Path


# Import the module under test
@pytest.fixture
def bump_module() -> Any:
    """The version-bump helper module."""
    from bmk.adapters.stagerunner.helpers import _bump_version

    return _bump_version


# =============================================================================
# parse_version tests
# =============================================================================


@pytest.mark.os_agnostic
class TestParseVersion:
    """Tests for parse_version function."""

    def test_parse_version_valid(self, bump_module: Any) -> None:
        """Valid semantic version string is parsed correctly."""
        assert bump_module.parse_version("1.2.3") == (1, 2, 3)

    def test_parse_version_zeros(self, bump_module: Any) -> None:
        """Version with zeros is parsed correctly."""
        assert bump_module.parse_version("0.0.0") == (0, 0, 0)

    def test_parse_version_large_numbers(self, bump_module: Any) -> None:
        """Large version numbers are parsed correctly."""
        assert bump_module.parse_version("100.200.300") == (100, 200, 300)

    def test_parse_version_invalid_format_two_parts(self, bump_module: Any) -> None:
        """Version with two parts raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version format"):
            bump_module.parse_version("1.2")

    def test_parse_version_invalid_format_four_parts(self, bump_module: Any) -> None:
        """Version with four parts raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version format"):
            bump_module.parse_version("1.2.3.4")

    def test_parse_version_invalid_format_non_numeric(self, bump_module: Any) -> None:
        """Version with non-numeric parts raises ValueError."""
        with pytest.raises(ValueError):
            bump_module.parse_version("1.2.a")


# =============================================================================
# bump_version tests
# =============================================================================


@pytest.mark.os_agnostic
class TestBumpVersion:
    """Tests for bump_version function."""

    def test_bump_major(self, bump_module: Any) -> None:
        """Major bump resets minor and patch to zero."""
        result = bump_module.bump_version((1, 2, 3), BumpPart.MAJOR)
        assert result == "2.0.0"

    def test_bump_major_from_zero(self, bump_module: Any) -> None:
        """Major bump from 0.x.y produces 1.0.0."""
        result = bump_module.bump_version((0, 5, 10), BumpPart.MAJOR)
        assert result == "1.0.0"

    def test_bump_minor(self, bump_module: Any) -> None:
        """Minor bump resets patch to zero."""
        result = bump_module.bump_version((1, 2, 3), BumpPart.MINOR)
        assert result == "1.3.0"

    def test_bump_minor_from_zero(self, bump_module: Any) -> None:
        """Minor bump from x.0.y produces x.1.0."""
        result = bump_module.bump_version((1, 0, 5), BumpPart.MINOR)
        assert result == "1.1.0"

    def test_bump_patch(self, bump_module: Any) -> None:
        """Patch bump increments only the patch number."""
        result = bump_module.bump_version((1, 2, 3), BumpPart.PATCH)
        assert result == "1.2.4"

    def test_bump_patch_from_zero(self, bump_module: Any) -> None:
        """Patch bump from x.y.0 produces x.y.1."""
        result = bump_module.bump_version((1, 2, 0), BumpPart.PATCH)
        assert result == "1.2.1"

    def test_bumppart_rejects_unknown_value(self) -> None:
        """An unknown bump part is rejected at the enum boundary, not in bump_version."""
        with pytest.raises(ValueError, match="is not a valid BumpPart"):
            BumpPart("invalid")


# =============================================================================
# find_unreleased_line tests
# =============================================================================


@pytest.mark.os_agnostic
class TestFindUnreleasedLine:
    """Tests for find_unreleased_line function."""

    def test_finds_unreleased_exact(self, bump_module: Any) -> None:
        """Finds exact ## [Unreleased] line."""
        lines = ["# Changelog", "", "## [Unreleased]", "", "## [1.0.0]"]
        assert bump_module.find_unreleased_line(lines) == 2

    def test_finds_unreleased_lowercase(self, bump_module: Any) -> None:
        """Finds ## [unreleased] line (case-insensitive)."""
        lines = ["# Changelog", "", "## [unreleased]", ""]
        assert bump_module.find_unreleased_line(lines) == 2

    def test_finds_unreleased_mixed_case(self, bump_module: Any) -> None:
        """Finds ## [UnReleAsed] line (case-insensitive)."""
        lines = ["# Changelog", "", "## [UnReleAsed]", ""]
        assert bump_module.find_unreleased_line(lines) == 2

    def test_finds_unreleased_with_trailing_content(self, bump_module: Any) -> None:
        """Finds ## [Unreleased] line with trailing content."""
        lines = ["# Changelog", "", "## [Unreleased] - Some text", ""]
        assert bump_module.find_unreleased_line(lines) == 2

    def test_returns_none_when_missing(self, bump_module: Any) -> None:
        """Returns None when no Unreleased section exists."""
        lines = ["# Changelog", "", "## [1.0.0]", ""]
        assert bump_module.find_unreleased_line(lines) is None


# =============================================================================
# find_first_version_line tests
# =============================================================================


@pytest.mark.os_agnostic
class TestFindFirstVersionLine:
    """Tests for find_first_version_line function."""

    def test_finds_first_version(self, bump_module: Any) -> None:
        """Finds first ## [X.Y.Z] version line."""
        lines = ["# Changelog", "", "## [Unreleased]", "", "## [1.0.0]"]
        assert bump_module.find_first_version_line(lines) == 4

    def test_skips_unreleased(self, bump_module: Any) -> None:
        """Does not return Unreleased as a version line."""
        lines = ["## [Unreleased]", "## [2.0.0]", "## [1.0.0]"]
        assert bump_module.find_first_version_line(lines) == 1

    def test_returns_none_when_no_versions(self, bump_module: Any) -> None:
        """Returns None when no version sections exist."""
        lines = ["# Changelog", "", "## [Unreleased]", ""]
        assert bump_module.find_first_version_line(lines) is None

    def test_finds_version_with_date(self, bump_module: Any) -> None:
        """Finds version line with date suffix."""
        lines = ["# Changelog", "", "## [1.0.0] - 2026-01-15", ""]
        assert bump_module.find_first_version_line(lines) == 2


# =============================================================================
# update_pyproject tests
# =============================================================================


@pytest.mark.os_agnostic
class TestUpdatePyproject:
    """Tests for update_pyproject function."""

    def test_updates_version_double_quotes(self, bump_module: Any, tmp_path: Path) -> None:
        """Updates version with double-quoted string."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

        old = bump_module.update_pyproject(tmp_path, "2.0.0")

        assert old == "1.0.0"
        content = pyproject.read_text()
        assert 'version = "2.0.0"' in content

    def test_updates_version_single_quotes(self, bump_module: Any, tmp_path: Path) -> None:
        """Updates version with single-quoted string."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'test'\nversion = '1.0.0'\n")

        old = bump_module.update_pyproject(tmp_path, "2.0.0")

        assert old == "1.0.0"
        content = pyproject.read_text()
        assert "version = '2.0.0'" in content

    def test_preserves_other_content(self, bump_module: Any, tmp_path: Path) -> None:
        """Preserves other content in pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        original = '[project]\nname = "test"\nversion = "1.0.0"\ndescription = "A test"\n'
        pyproject.write_text(original)

        bump_module.update_pyproject(tmp_path, "2.0.0")

        content = pyproject.read_text()
        assert 'description = "A test"' in content
        assert 'name = "test"' in content

    def test_raises_when_no_version(self, bump_module: Any, tmp_path: Path) -> None:
        """Raises ValueError when no version field exists."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\n')

        with pytest.raises(ValueError, match="Could not find"):
            bump_module.update_pyproject(tmp_path, "2.0.0")


# =============================================================================
# update_changelog tests
# =============================================================================


@pytest.mark.os_agnostic
class TestUpdateChangelog:
    """Tests for update_changelog function."""

    def test_inserts_version_after_unreleased(self, bump_module: Any, tmp_path: Path) -> None:
        """Inserts new version entry after Unreleased section."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [Unreleased]\n\n### Added\n- Feature\n\n## [1.0.0]\n")

        bump_module.update_changelog(tmp_path, "1.1.0")

        content = changelog.read_text()
        lines = content.split("\n")
        # Find positions
        unreleased_idx = next(i for i, line in enumerate(lines) if "[Unreleased]" in line)
        new_version_idx = next(i for i, line in enumerate(lines) if "[1.1.0]" in line)
        old_version_idx = next(i for i, line in enumerate(lines) if "[1.0.0]" in line)

        # Unreleased should come before new version
        assert unreleased_idx < new_version_idx
        # New version should come before old version
        assert new_version_idx < old_version_idx

    def test_adds_timestamp_to_new_version(self, bump_module: Any, tmp_path: Path) -> None:
        """New version entry includes timestamp."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n")

        bump_module.update_changelog(tmp_path, "1.1.0")

        content = changelog.read_text()
        # Should have timestamp in format YYYY-MM-DD HH:MM:SS
        import re

        pattern = r"\[1\.1\.0\] \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        assert re.search(pattern, content) is not None

    def test_creates_unreleased_when_missing(self, bump_module: Any, tmp_path: Path) -> None:
        """Creates Unreleased section when missing."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [1.0.0]\n")

        bump_module.update_changelog(tmp_path, "1.1.0")

        content = changelog.read_text()
        assert "## [Unreleased]" in content

    def test_does_nothing_when_changelog_missing(self, bump_module: Any, tmp_path: Path) -> None:
        """Does nothing when CHANGELOG.md doesn't exist."""
        # Should not raise
        bump_module.update_changelog(tmp_path, "1.1.0")

        # Changelog should still not exist
        assert not (tmp_path / "CHANGELOG.md").exists()

    def test_preserves_unreleased_content(self, bump_module: Any, tmp_path: Path) -> None:
        """Preserves content under Unreleased section."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [Unreleased]\n\n### Added\n- New feature\n\n## [1.0.0]\n")

        bump_module.update_changelog(tmp_path, "1.1.0")

        content = changelog.read_text()
        # The original content should still be there between Unreleased and the new version
        assert "### Added" in content
        assert "- New feature" in content


@pytest.mark.os_agnostic
def test_update_changelog_inserts_before_first_version_when_no_unreleased(bump_module: Any, tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [1.0.0] - 2020-01-01\n\n- initial\n", encoding="utf-8")
    bump_module.update_changelog(tmp_path, "1.1.0")
    text = changelog.read_text(encoding="utf-8")
    assert "[Unreleased]" in text
    assert "1.1.0" in text
    assert text.index("1.1.0") < text.index("1.0.0")  # new version before the old one


@pytest.mark.os_agnostic
def test_main_bumps_version(bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])
    assert bump_module.main() == 0
    assert 'version = "1.2.4"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_main_returns_one_when_no_version(bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])
    assert bump_module.main() == 1


@pytest.mark.os_agnostic
def test_main_returns_one_when_pyproject_missing(
    bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path / "nope")])
    assert bump_module.main() == 1


@pytest.mark.os_agnostic
def test_main_returns_one_on_invalid_version(bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "not.a.version"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])
    assert bump_module.main() == 1
