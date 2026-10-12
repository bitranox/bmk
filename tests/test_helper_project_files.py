"""Behaviour tests for the shared lint-stage file discovery in helpers._project_files."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner.helpers._project_files import _git_listed_files, find_project_files

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.mark.os_agnostic
def test_case_insensitive_listing_finds_an_upper_case_suffix(tmp_path: Path, git_project: Callable[..., None]) -> None:
    """On Windows the walk matched ``Build.PS1``; git's pathspec must do the same there."""
    (tmp_path / "Build.PS1").write_text("# upper")
    (tmp_path / "a.ps1").write_text("# lower")
    git_project("add", "Build.PS1", "a.ps1")

    listed = _git_listed_files(tmp_path, ".ps1", case_insensitive=True)

    assert listed is not None
    assert sorted(p.name for p in listed) == ["Build.PS1", "a.ps1"]


@pytest.mark.os_agnostic
def test_case_sensitive_listing_keeps_the_exact_suffix_only(tmp_path: Path, git_project: Callable[..., None]) -> None:
    """On POSIX the walk was case-sensitive, and the listing stays so."""
    (tmp_path / "Build.PS1").write_text("# upper")
    (tmp_path / "a.ps1").write_text("# lower")
    git_project("add", "Build.PS1", "a.ps1")

    listed = _git_listed_files(tmp_path, ".ps1", case_insensitive=False)

    assert listed is not None
    assert [p.name for p in listed] == ["a.ps1"]


def _names(files: list[Path], root: Path) -> list[str]:
    return [f.relative_to(root).as_posix() for f in files]


@pytest.mark.os_windows
def test_find_project_files_matches_an_upper_case_suffix_on_windows(
    tmp_path: Path, git_project: Callable[..., None]
) -> None:
    """The real wiring, not only the parameter: on Windows ``Build.PS1`` is found."""
    (tmp_path / "Build.PS1").write_text("# upper")
    git_project("add", "Build.PS1")

    assert _names(find_project_files(tmp_path, ".ps1"), tmp_path) == ["Build.PS1"]


@pytest.mark.os_agnostic
def test_an_ignored_project_holding_a_tracked_file_is_still_walked(
    tmp_path: Path, git_project: Callable[..., None]
) -> None:
    """git does not report a directory as ignored once the index tracks a file inside it."""
    (tmp_path / ".gitignore").write_text("work/\n")
    project = tmp_path / "work" / "proj"
    (project / "s").mkdir(parents=True)
    (project / "README").write_text("readme")
    (project / "s" / "a.sh").write_text("# a")
    (project / "s" / "z.sh").write_text("# z")
    git_project("add", "-f", "work/proj/README", "work/proj/s/a.sh")

    assert _names(find_project_files(project, ".sh"), project) == ["s/a.sh", "s/z.sh"]


@pytest.mark.os_agnostic
def test_a_repository_root_is_never_treated_as_ignored(tmp_path: Path, git_project: Callable[..., None]) -> None:
    """A root ``.gitignore`` of ``*`` matches ``.`` too; the root's ignored scripts stay unlinted."""
    (tmp_path / ".gitignore").write_text("*\n!.gitignore\n")
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "e.sh").write_text("# ignored")

    assert find_project_files(tmp_path, ".sh") == []


@pytest.mark.os_agnostic
def test_a_missing_git_inside_a_checkout_is_reported(
    tmp_path: Path,
    git_project: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With git absent the walk lints ignored scripts again, so that must not be silent."""
    (tmp_path / "ok.sh").write_text("# ok")
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-bin"))

    find_project_files(tmp_path, ".sh")

    assert "WARNING" in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_a_stray_empty_git_directory_is_not_a_checkout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An empty ``.git`` directory above the project is no repository, so no warning."""
    (tmp_path / ".git").mkdir()
    project = tmp_path / "plain"
    project.mkdir()
    (project / "x.sh").write_text("# x")

    assert _names(find_project_files(project, ".sh"), project) == ["x.sh"]
    assert capsys.readouterr().err == ""
