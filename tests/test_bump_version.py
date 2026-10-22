"""Unit tests for _bump_version.py version bumping logic."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
import rtoml

from bmk.domain.enums import BumpPart
from bmk.domain.version import next_version

if TYPE_CHECKING:
    from pathlib import Path


# Import the module under test
@pytest.fixture
def bump_module() -> Any:
    """The version-bump helper module."""
    from bmk.adapters.stagerunner.helpers import _bump_version

    return _bump_version


# =============================================================================
# Version arithmetic
#
# The rules live in bmk.domain.version (tested in tests/test_domain_version.py).
# These cover the ordinary final-version cases as this helper drives them, plus the
# enum boundary; the non-final cases are exercised end to end through main() below.
# =============================================================================


@pytest.mark.os_agnostic
class TestBumpVersion:
    """Tests for the version arithmetic the bump helper drives."""

    def test_bump_major(self) -> None:
        """Major bump resets minor and patch to zero."""
        assert next_version("1.2.3", BumpPart.MAJOR) == "2.0.0"

    def test_bump_major_from_zero(self) -> None:
        """Major bump from 0.x.y produces 1.0.0."""
        assert next_version("0.5.10", BumpPart.MAJOR) == "1.0.0"

    def test_bump_minor(self) -> None:
        """Minor bump resets patch to zero."""
        assert next_version("1.2.3", BumpPart.MINOR) == "1.3.0"

    def test_bump_minor_from_zero(self) -> None:
        """Minor bump from x.0.y produces x.1.0."""
        assert next_version("1.0.5", BumpPart.MINOR) == "1.1.0"

    def test_bump_patch(self) -> None:
        """Patch bump increments only the patch number."""
        assert next_version("1.2.3", BumpPart.PATCH) == "1.2.4"

    def test_bump_patch_from_zero(self) -> None:
        """Patch bump from x.y.0 produces x.y.1."""
        assert next_version("1.2.0", BumpPart.PATCH) == "1.2.1"

    def test_bump_large_numbers(self) -> None:
        """Multi-digit components survive the round trip."""
        assert next_version("100.200.300", BumpPart.PATCH) == "100.200.301"

    def test_bumppart_rejects_unknown_value(self) -> None:
        """An unknown bump part is rejected at the enum boundary, not in next_version."""
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

    def test_updates_a_version_written_without_spaces(self, bump_module: Any, tmp_path: Path) -> None:
        """``version="0.1.0"`` is bumped too: a text match on ``version = "..."`` changed nothing and said it did."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\nversion="0.1.0"\n', encoding="utf-8")

        bump_module.update_pyproject(tmp_path, "0.1.1")

        assert rtoml.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"] == "0.1.1"

    def test_updates_only_the_project_version(self, bump_module: Any, tmp_path: Path) -> None:
        """A ``version`` key in a table before ``[project]`` is not the project's and stays as it is."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.other]\nversion = "1.0.0"\n\n[project]\nname = "test"\nversion = "1.0.0"\n', encoding="utf-8"
        )

        bump_module.update_pyproject(tmp_path, "2.0.0")

        document = rtoml.loads(pyproject.read_text(encoding="utf-8"))
        assert (document["tool"]["other"]["version"], document["project"]["version"]) == ("1.0.0", "2.0.0")

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


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("current", "part", "expected"),
    [
        ("1.2.3rc1", "patch", "1.2.3"),
        ("1.3.0b2", "patch", "1.3.0"),
        ("1.2.3.dev4", "patch", "1.2.3"),
        ("1.2.3.post1", "patch", "1.2.4"),
        ("2.0.0rc1", "major", "2.0.0"),
        ("1.2.3rc1", "minor", "1.3.0"),
    ],
)
def test_main_finalizes_a_non_final_version_instead_of_crashing(
    bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, current: str, part: str, expected: str
) -> None:
    """Bumping used to die on int('3rc1'); a non-final version now finalizes to its release."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "x"\nversion = "{current}"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", part, "--project-dir", str(tmp_path)])

    assert bump_module.main() == 0
    assert f'version = "{expected}"' in pyproject.read_text(encoding="utf-8")
    assert f"## [{expected}]" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")


# A bump changes [project].version, and uv.lock records the project's own version. Left stale,
# the lock fails `uv export --locked` in default_cicd CI and `uv sync --locked` locally on the
# release commit (bmk OPEN-WORK [101]: lib_cli_exit_tools 2.4.1 in the fleet sweep).


def _is_root() -> bool:
    """POSIX root ignores file and directory modes. Windows has no euid, and pyright checks one
    platform per run, so the platform test must come first for it to see geteuid as unreachable."""
    if sys.platform == "win32":
        return False
    return os.geteuid() == 0


def _uv_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\nrequires-python = ">=3.10"\ndependencies = []\n', encoding="utf-8"
    )


@pytest.mark.os_agnostic
def test_main_relocks_a_committed_uv_lock(bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    _uv_project(tmp_path)
    subprocess.run(["uv", "lock", "-q"], cwd=tmp_path, check=True)
    assert 'version = "1.2.3"' in (tmp_path / "uv.lock").read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])

    assert bump_module.main() == 0

    assert 'version = "1.2.4"' in (tmp_path / "uv.lock").read_text(encoding="utf-8")
    assert subprocess.run(["uv", "lock", "--check", "-q"], cwd=tmp_path, check=False).returncode == 0


@pytest.mark.os_agnostic
def test_main_writes_no_lock_where_the_project_has_none(
    bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _uv_project(tmp_path)
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])

    assert bump_module.main() == 0

    assert not (tmp_path / "uv.lock").exists()


@pytest.mark.os_agnostic
def test_a_failed_relock_leaves_no_half_applied_bump(
    bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """When the re-lock fails the bump must not stay written: re-running it would skip a version.

    Measured trigger: offline with a cold cache, uv cannot resolve a dependency it never fetched.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    _uv_project(tmp_path)
    subprocess.run(["uv", "lock", "-q"], cwd=tmp_path, check=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace("dependencies = []", 'dependencies = ["idna>=3"]'),
        encoding="utf-8",
    )
    # CRLF on purpose: the undo must give back the exact bytes, not a re-encoded copy
    pyproject.write_bytes(pyproject.read_bytes().replace(b"\n", b"\r\n"))
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"# Changelog\r\n\r\n## [Unreleased]\r\n\r\n- something\r\n\r\n## [1.2.3] 2026-01-01\r\n")
    before = (pyproject.read_bytes(), changelog.read_bytes())
    (tmp_path / "cold-cache").mkdir()
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cold-cache"))
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])

    assert bump_module.main() == 1

    assert (pyproject.read_bytes(), changelog.read_bytes()) == before
    err = capfd.readouterr().err
    assert "idna" in err, "uv's own reason must reach the user, not only 'fix the lock'"
    assert "was undone" in err


@pytest.mark.os_agnostic
def test_a_bump_whose_changelog_cannot_be_updated_is_undone(
    bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any failure after pyproject.toml was written undoes it, not only a failed re-lock.

    An undecodable CHANGELOG.md fails after the pyproject write for root and on Windows alike,
    where a read-only file would not stop root.
    """
    _uv_project(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"# Changelog\n\n## [Unreleased]\n\n- caf\xe9\n")
    before = (pyproject.read_bytes(), changelog.read_bytes())
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])

    assert bump_module.main() == 1

    assert (pyproject.read_bytes(), changelog.read_bytes()) == before


@pytest.mark.os_agnostic
def test_the_snapshot_includes_a_committed_uv_lock(bump_module: Any, tmp_path: Path) -> None:
    """The re-lock rewrites uv.lock; a Ctrl-C after that write must not leave it on the new version."""
    _uv_project(tmp_path)
    (tmp_path / "uv.lock").write_bytes(b"version = 1\r\n")

    snapshot = bump_module._snapshot(tmp_path)

    assert snapshot[tmp_path / "uv.lock"] == b"version = 1\r\n"


@pytest.mark.os_agnostic
def test_one_failed_restore_does_not_stop_the_others(bump_module: Any, tmp_path: Path) -> None:
    (tmp_path / "blocker").write_text("a file where a directory is expected", encoding="utf-8")
    unrestorable = tmp_path / "blocker" / "pyproject.toml"
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes(b"bumped")

    failed = bump_module._restore({unrestorable: b"old", changelog: b"original"})

    assert [path for path, _reason in failed] == [unrestorable]
    assert changelog.read_bytes() == b"original"


@pytest.mark.os_agnostic
def test_an_undo_that_could_not_restore_everything_does_not_claim_it_did(
    bump_module: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Saying "undone" over a still-bumped file sends the user into a second bump and a skipped version."""
    (tmp_path / "blocker").write_text("x", encoding="utf-8")
    unrestorable = tmp_path / "blocker" / "pyproject.toml"

    assert bump_module._undo_bump({unrestorable: b"old"}, "1.2.4") == 1

    err = capsys.readouterr().err
    assert "was undone" not in err
    assert str(unrestorable) in err
    assert "1.2.4" in err


@pytest.mark.os_agnostic
def test_a_complete_undo_says_so(bump_module: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_bytes(b"bumped")

    assert bump_module._undo_bump({pyproject: b"old"}, "1.2.4") == 1

    assert pyproject.read_bytes() == b"old"
    assert "the bump to 1.2.4 was undone" in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_a_ctrl_c_during_the_relock_restores_every_file_and_still_interrupts(
    bump_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uv rewrote uv.lock, then the user pressed Ctrl-C: all three files go back, and the interrupt stands."""
    _uv_project(tmp_path)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\n- x\n", encoding="utf-8")
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"version = 1\n# demo 1.2.3\n")
    before = {path: path.read_bytes() for path in (tmp_path / "pyproject.toml", changelog, lock)}

    def relock_then_interrupt(project_dir: Path, *, quiet: bool = True) -> bool:
        _ = quiet
        (project_dir / "uv.lock").write_bytes(b"version = 1\n# demo 1.2.4\n")
        raise KeyboardInterrupt

    # the re-lock is the one collaborator that runs uv; a real Ctrl-C cannot be timed into it
    monkeypatch.setattr(bump_module, "lock_project", relock_then_interrupt)
    monkeypatch.setattr(sys, "argv", ["_bump_version.py", "patch", "--project-dir", str(tmp_path)])

    with pytest.raises(KeyboardInterrupt):
        bump_module.main()

    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.os_agnostic
def test_the_undo_writes_through_a_symlink(bump_module: Any, tmp_path: Path) -> None:
    """Replacing the link would leave the real file bumped while the report said "undone"."""
    (tmp_path / "docs").mkdir()
    target = tmp_path / "docs" / "CHANGELOG.md"
    target.write_bytes(b"bumped")
    link = tmp_path / "CHANGELOG.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("this platform or account cannot create symlinks")

    assert bump_module._restore({link: b"original"}) == []

    assert link.is_symlink()
    assert target.read_bytes() == b"original"


@pytest.mark.os_agnostic
def test_a_file_the_bump_never_changed_is_not_reported_as_still_bumped(bump_module: Any, tmp_path: Path) -> None:
    """uv.lock is snapshotted but only rewritten by a lock that got that far; untouched, there is nothing to undo."""
    if _is_root():
        pytest.skip("root writes a read-only file, so a needless rewrite would go unnoticed")
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"unchanged")
    lock.chmod(0o444)
    try:
        failed = bump_module._restore({lock: b"unchanged"})
    finally:
        lock.chmod(0o644)

    assert failed == []


@pytest.mark.os_posix
def test_the_undo_needs_no_write_access_to_the_project_directory(bump_module: Any, tmp_path: Path) -> None:
    """A temp-file-and-rename undo fails in a directory the user may write files in but not create them."""
    if _is_root():
        pytest.skip("root ignores the directory's mode")
    project = tmp_path / "project"
    project.mkdir()
    pyproject = project / "pyproject.toml"
    pyproject.write_bytes(b"bumped")
    project.chmod(0o555)
    try:
        failed = bump_module._restore({pyproject: b"original"})
    finally:
        project.chmod(0o755)

    assert failed == []
    assert pyproject.read_bytes() == b"original"


@pytest.mark.os_agnostic
def test_a_file_deleted_during_the_bump_is_recreated(bump_module: Any, tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"

    assert bump_module._restore({lock: b"version = 1\n"}) == []

    assert lock.read_bytes() == b"version = 1\n"


@pytest.mark.os_agnostic
def test_a_failed_rewrite_is_reported_as_possibly_incomplete_not_as_still_bumped(
    bump_module: Any, tmp_path: Path
) -> None:
    """An in-place write that fails midway (disk full) leaves neither version: say so."""
    if _is_root():
        pytest.skip("root writes a read-only file")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_bytes(b"bumped")
    pyproject.chmod(0o444)
    try:
        failed = bump_module._restore({pyproject: b"original"})
    finally:
        pyproject.chmod(0o644)

    assert [path for path, _reason in failed] == [pyproject]
    assert "may be incomplete" in failed[0][1]


@pytest.mark.os_agnostic
def test_an_unreadable_file_is_reported_as_unread_not_as_rewritten(bump_module: Any, tmp_path: Path) -> None:
    """A directory where the file belongs: IsADirectoryError on POSIX, PermissionError on Windows.

    Not a path under a regular file: Windows reports that as FileNotFoundError, the deleted-file case.
    """
    unreadable = tmp_path / "pyproject.toml"
    unreadable.mkdir()

    [(path, reason)] = bump_module._restore({unreadable: b"original"})

    assert path == unreadable
    assert "could not be read" in reason
