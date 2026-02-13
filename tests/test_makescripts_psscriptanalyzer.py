"""Behaviour tests for makescripts._psscriptanalyzer: config reading, pwsh detection, file discovery."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bmk.makescripts._psscriptanalyzer import (
    check_pwsh,
    find_ps1_files,
    get_excluded_rules,
)

# ---------------------------------------------------------------------------
# get_excluded_rules
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_excluded_rules_returns_fallback_when_no_pyproject(tmp_path: Path) -> None:
    """Falls back to built-in rules when pyproject.toml is absent."""
    rules = get_excluded_rules(tmp_path / "nonexistent.toml")

    assert isinstance(rules, tuple)
    assert len(rules) > 0
    assert "PSAvoidUsingWriteHost" in rules


@pytest.mark.os_agnostic
def test_get_excluded_rules_returns_fallback_when_no_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falls back to built-in rules and warns when [tool.psscriptanalyzer] is absent."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'test'\n")

    rules = get_excluded_rules(pyproject)

    assert "PSAvoidUsingWriteHost" in rules
    captured = capsys.readouterr()
    assert "WARNING: No [tool.psscriptanalyzer] section found" in captured.err
    assert "[tool.psscriptanalyzer]" in captured.err


@pytest.mark.os_agnostic
def test_get_excluded_rules_reads_from_pyproject(tmp_path: Path) -> None:
    """Reads custom rules from [tool.psscriptanalyzer].exclude-rules."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n[tool.psscriptanalyzer]\nexclude-rules = ["PSCustomRule", "PSAnotherRule"]\n'
    )

    rules = get_excluded_rules(pyproject)

    assert "PSCustomRule" in rules
    assert "PSAnotherRule" in rules
    assert len(rules) == 2


# ---------------------------------------------------------------------------
# check_pwsh
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_check_pwsh_returns_path_when_available() -> None:
    """Returns a path string when pwsh is on PATH."""
    with patch("bmk.makescripts._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"):
        result = check_pwsh()

    assert result == "/usr/bin/pwsh"


@pytest.mark.os_agnostic
def test_check_pwsh_returns_none_when_missing() -> None:
    """Returns None when pwsh is not on PATH."""
    with patch("bmk.makescripts._psscriptanalyzer.shutil.which", return_value=None):
        result = check_pwsh()

    assert result is None


# ---------------------------------------------------------------------------
# find_ps1_files
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_ps1_files_excludes_venv(tmp_path: Path) -> None:
    """Files under .venv are excluded from results."""
    venv_dir = tmp_path / ".venv" / "scripts"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate.ps1").write_text("# venv")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.ps1").write_text("# build")

    files = find_ps1_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.ps1"


@pytest.mark.os_agnostic
def test_find_ps1_files_excludes_node_modules(tmp_path: Path) -> None:
    """Files under node_modules are excluded from results."""
    nm_dir = tmp_path / "node_modules" / "pkg"
    nm_dir.mkdir(parents=True)
    (nm_dir / "script.ps1").write_text("# npm")

    files = find_ps1_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_ps1_files_excludes_git(tmp_path: Path) -> None:
    """Files under .git are excluded from results."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "pre-commit.ps1").write_text("# hook")

    files = find_ps1_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_ps1_files_returns_empty_for_no_files(tmp_path: Path) -> None:
    """Returns empty list when no .ps1 files exist."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# python")

    files = find_ps1_files(tmp_path)

    assert files == []


@pytest.mark.os_agnostic
def test_find_ps1_files_returns_sorted(tmp_path: Path) -> None:
    """Results are sorted by path."""
    (tmp_path / "z_script.ps1").write_text("# z")
    (tmp_path / "a_script.ps1").write_text("# a")
    (tmp_path / "m_script.ps1").write_text("# m")

    files = find_ps1_files(tmp_path)

    assert len(files) == 3
    assert files[0].name == "a_script.ps1"
    assert files[1].name == "m_script.ps1"
    assert files[2].name == "z_script.ps1"
