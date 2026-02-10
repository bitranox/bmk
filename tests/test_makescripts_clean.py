"""Behaviour tests for makescripts._clean: clean patterns, file removal, dry-run."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmk.makescripts._clean import clean, get_clean_patterns, main


# ---------------------------------------------------------------------------
# get_clean_patterns
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_clean_patterns_returns_fallback_when_no_pyproject(tmp_path: Path) -> None:
    """Falls back to built-in patterns when pyproject.toml is absent."""
    patterns = get_clean_patterns(tmp_path / "nonexistent.toml")

    assert isinstance(patterns, tuple)
    assert len(patterns) > 0
    assert ".pytest_cache" in patterns


@pytest.mark.os_agnostic
def test_get_clean_patterns_returns_fallback_when_no_clean_section(tmp_path: Path) -> None:
    """Falls back to built-in patterns when [tool.clean] is absent."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'test'\n")

    patterns = get_clean_patterns(pyproject)

    assert ".pytest_cache" in patterns


@pytest.mark.os_agnostic
def test_get_clean_patterns_reads_from_pyproject(tmp_path: Path) -> None:
    """Reads custom patterns from [tool.clean].patterns."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n'
        '[tool.clean]\npatterns = ["custom_cache", "*.tmp"]\n'
    )

    patterns = get_clean_patterns(pyproject)

    assert "custom_cache" in patterns
    assert "*.tmp" in patterns


# ---------------------------------------------------------------------------
# clean — directory removal
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_clean_removes_matching_directories(tmp_path: Path) -> None:
    """Directories matching patterns are removed."""
    cache_dir = tmp_path / ".pytest_cache"
    cache_dir.mkdir()
    (cache_dir / "v" / "cache").mkdir(parents=True)
    (cache_dir / "v" / "cache" / "data.json").write_text("{}")

    result = clean(project_dir=tmp_path, patterns=[".pytest_cache"])

    assert result == 0
    assert not cache_dir.exists()


@pytest.mark.os_agnostic
def test_clean_removes_matching_files(tmp_path: Path) -> None:
    """Files matching patterns are removed."""
    coverage_file = tmp_path / ".coverage"
    coverage_file.write_text("data")

    result = clean(project_dir=tmp_path, patterns=[".coverage"])

    assert result == 0
    assert not coverage_file.exists()


@pytest.mark.os_agnostic
def test_clean_verbose_prints_directory_removal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints directory removal."""
    cache_dir = tmp_path / ".ruff_cache"
    cache_dir.mkdir()

    clean(project_dir=tmp_path, patterns=[".ruff_cache"], verbose=True)

    captured = capsys.readouterr()
    assert "Removing directory:" in captured.out
    assert ".ruff_cache" in captured.out


@pytest.mark.os_agnostic
def test_clean_verbose_prints_file_removal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints file removal."""
    cov_file = tmp_path / "coverage.xml"
    cov_file.write_text("<xml/>")

    clean(project_dir=tmp_path, patterns=["coverage.xml"], verbose=True)

    captured = capsys.readouterr()
    assert "Removing file:" in captured.out
    assert "coverage.xml" in captured.out


@pytest.mark.os_agnostic
def test_clean_prints_count_when_items_removed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Summary line printed when items were removed."""
    (tmp_path / ".cache").mkdir()

    clean(project_dir=tmp_path, patterns=[".cache"])

    captured = capsys.readouterr()
    assert "Removed 1 items" in captured.out


@pytest.mark.os_agnostic
def test_clean_no_output_when_nothing_to_remove(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No output when no patterns match."""
    clean(project_dir=tmp_path, patterns=["nonexistent_*"])

    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# clean — dry run
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_clean_dry_run_does_not_delete(tmp_path: Path) -> None:
    """Dry run does not delete files or directories."""
    cache_dir = tmp_path / ".pytest_cache"
    cache_dir.mkdir()
    cov_file = tmp_path / ".coverage"
    cov_file.write_text("data")

    result = clean(project_dir=tmp_path, patterns=[".pytest_cache", ".coverage"], dry_run=True)

    assert result == 0
    assert cache_dir.exists()
    assert cov_file.exists()


@pytest.mark.os_agnostic
def test_clean_dry_run_prints_would_remove(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dry run prints what would be removed."""
    (tmp_path / "build").mkdir()

    clean(project_dir=tmp_path, patterns=["build"], dry_run=True)

    captured = capsys.readouterr()
    assert "[DRY RUN] Would remove:" in captured.out
    assert "[DRY RUN] Would remove 1 items" in captured.out


# ---------------------------------------------------------------------------
# clean — path containment (security)
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_clean_rejects_traversal_pattern(tmp_path: Path) -> None:
    """Patterns with ../ must not delete files outside project directory."""
    project = tmp_path / "project"
    project.mkdir()
    outside_file = tmp_path / "precious.txt"
    outside_file.write_text("do not delete")

    result = clean(project_dir=project, patterns=["../precious.txt"])

    assert result == 0
    assert outside_file.exists(), "File outside project was deleted!"


@pytest.mark.os_agnostic
def test_clean_rejects_traversal_directory(tmp_path: Path) -> None:
    """Directories matched via ../ must not be removed."""
    project = tmp_path / "project"
    project.mkdir()
    outside_dir = tmp_path / "important_data"
    outside_dir.mkdir()
    (outside_dir / "file.txt").write_text("keep")

    result = clean(project_dir=project, patterns=["../important_data"])

    assert result == 0
    assert outside_dir.exists(), "Directory outside project was deleted!"


@pytest.mark.os_agnostic
def test_clean_prints_skip_message_for_traversal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Skipped paths are reported in output."""
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.txt").write_text("x")

    clean(project_dir=project, patterns=["../outside.txt"], verbose=True)

    captured = capsys.readouterr()
    assert "Skipping (outside project)" in captured.out
    assert "Skipped 1 paths outside project directory" in captured.out


@pytest.mark.os_agnostic
def test_clean_allows_nested_paths_inside_project(tmp_path: Path) -> None:
    """Deeply nested paths inside the project are allowed."""
    nested = tmp_path / "src" / "pkg" / "__pycache__"
    nested.mkdir(parents=True)

    result = clean(project_dir=tmp_path, patterns=["**/__pycache__"])

    assert result == 0
    assert not nested.exists()


@pytest.mark.os_agnostic
def test_clean_rejects_double_star_traversal(tmp_path: Path) -> None:
    """Pattern **/../<target> must not escape project boundary."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "subdir").mkdir()
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret")

    result = clean(project_dir=project, patterns=["**/../secret.txt"])

    assert result == 0
    assert outside_file.exists(), "File outside project was deleted via **/../ traversal!"


# ---------------------------------------------------------------------------
# clean — glob wildcards
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_clean_handles_glob_patterns(tmp_path: Path) -> None:
    """Glob wildcards like *.egg-info work."""
    egg_dir = tmp_path / "mypackage.egg-info"
    egg_dir.mkdir()
    (egg_dir / "PKG-INFO").write_text("metadata")

    result = clean(project_dir=tmp_path, patterns=["*.egg-info"])

    assert result == 0
    assert not egg_dir.exists()


# ---------------------------------------------------------------------------
# clean — defaults to cwd and pyproject patterns
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_clean_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """project_dir defaults to cwd when not specified."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    (tmp_path / ".hypothesis").mkdir()

    result = clean(patterns=[".hypothesis"])

    assert result == 0
    assert not (tmp_path / ".hypothesis").exists()


@pytest.mark.os_agnostic
def test_clean_reads_patterns_from_pyproject_when_none(tmp_path: Path) -> None:
    """Reads patterns from pyproject.toml when patterns=None."""
    (tmp_path / ".pytest_cache").mkdir()
    # No pyproject.toml → uses fallback which includes .pytest_cache

    result = clean(project_dir=tmp_path)

    assert result == 0
    assert not (tmp_path / ".pytest_cache").exists()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_prints_cleaning_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main() prints the project directory being cleaned."""
    result = main(project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert f"Cleaning build artifacts in {tmp_path}" in captured.out


@pytest.mark.os_agnostic
def test_main_defaults_to_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main() defaults project_dir to cwd."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    result = main()

    assert result == 0
    captured = capsys.readouterr()
    assert str(tmp_path) in captured.out


@pytest.mark.os_agnostic
def test_main_passes_dry_run_and_verbose(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main() passes dry_run and verbose through to clean()."""
    (tmp_path / "dist").mkdir()

    main(project_dir=tmp_path, dry_run=True, verbose=True)

    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out
