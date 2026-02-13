"""Behaviour tests for makescripts._shellcheck: config reading and file discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmk.makescripts._shellcheck import (
    find_sh_files,
    get_bashate_config,
)

# ---------------------------------------------------------------------------
# get_bashate_config
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_bashate_config_returns_fallback_when_no_pyproject(tmp_path: Path) -> None:
    """Falls back to built-in defaults when pyproject.toml is absent."""
    max_len, ignores = get_bashate_config(tmp_path / "nonexistent.toml")

    assert max_len == 120
    assert isinstance(ignores, tuple)
    assert "E003" in ignores


@pytest.mark.os_agnostic
def test_get_bashate_config_returns_fallback_when_no_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falls back to built-in defaults and warns when [tool.bashate] is absent."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'test'\n")

    max_len, ignores = get_bashate_config(pyproject)

    assert max_len == 120
    assert "E003" in ignores
    captured = capsys.readouterr()
    assert "WARNING: No [tool.bashate] section found" in captured.err
    assert "[tool.bashate]" in captured.err


@pytest.mark.os_agnostic
def test_get_bashate_config_reads_from_pyproject(tmp_path: Path) -> None:
    """Reads custom values from [tool.bashate]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 100\nignores = ["E006", "E010"]\n'
    )

    max_len, ignores = get_bashate_config(pyproject)

    assert max_len == 100
    assert "E006" in ignores
    assert "E010" in ignores
    assert len(ignores) == 2


@pytest.mark.os_agnostic
def test_get_bashate_config_reads_ignores_from_pyproject(tmp_path: Path) -> None:
    """Verify ignores list parsing with single entry."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 80\nignores = ["E003"]\n')

    max_len, ignores = get_bashate_config(pyproject)

    assert max_len == 80
    assert ignores == ("E003",)


# ---------------------------------------------------------------------------
# find_sh_files
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_venv(tmp_path: Path) -> None:
    """Files under .venv are excluded from results."""
    venv_dir = tmp_path / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate.sh").write_text("# venv")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_node_modules(tmp_path: Path) -> None:
    """Files under node_modules are excluded from results."""
    nm_dir = tmp_path / "node_modules" / "pkg"
    nm_dir.mkdir(parents=True)
    (nm_dir / "script.sh").write_text("# npm")

    files = find_sh_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_git(tmp_path: Path) -> None:
    """Files under .git are excluded from results."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "pre-commit.sh").write_text("# hook")

    files = find_sh_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_sh_files_returns_empty_for_no_files(tmp_path: Path) -> None:
    """Returns empty list when no .sh files exist."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# python")

    files = find_sh_files(tmp_path)

    assert files == []


@pytest.mark.os_agnostic
def test_find_sh_files_returns_sorted(tmp_path: Path) -> None:
    """Results are sorted by path."""
    (tmp_path / "z_script.sh").write_text("# z")
    (tmp_path / "a_script.sh").write_text("# a")
    (tmp_path / "m_script.sh").write_text("# m")

    files = find_sh_files(tmp_path)

    assert len(files) == 3
    assert files[0].name == "a_script.sh"
    assert files[1].name == "m_script.sh"
    assert files[2].name == "z_script.sh"
