"""Behaviour tests for makescripts._shellcheck: config reading, file discovery, and orchestration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bmk.makescripts._shellcheck import (
    find_sh_files,
    get_bashate_config,
    main,
    run_bashate,
    run_shellcheck,
    run_shfmt,
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


# ---------------------------------------------------------------------------
# run_shellcheck
# ---------------------------------------------------------------------------


def _make_completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.mark.os_agnostic
def test_run_shellcheck_returns_zero_on_clean(tmp_path: Path) -> None:
    """Returns 0 when shellcheck reports no violations."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)) as mock_run:
        result = run_shellcheck(files=[script])

    assert result == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "shellcheck"
    assert str(script) in cmd


@pytest.mark.os_agnostic
def test_run_shellcheck_returns_nonzero_on_violations(tmp_path: Path) -> None:
    """Returns non-zero when shellcheck finds violations."""
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(1)):
        result = run_shellcheck(files=[script])

    assert result == 1


@pytest.mark.os_agnostic
def test_run_shellcheck_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)):
        run_shellcheck(files=[script], verbose=True)

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_shfmt
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_shfmt_returns_zero_when_no_diffs(tmp_path: Path) -> None:
    """Returns 0 when shfmt finds no formatting differences."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)):
        result = run_shfmt(files=[script])

    assert result == 0


@pytest.mark.os_agnostic
def test_run_shfmt_returns_one_when_diffs_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 1 and prints diff when shfmt finds formatting differences."""
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/bash\n")
    with patch(
        "bmk.makescripts._shellcheck.subprocess.run",
        return_value=_make_completed(0, stdout="--- a/bad.sh\n+++ b/bad.sh\n"),
    ):
        result = run_shfmt(files=[script])

    assert result == 1
    captured = capsys.readouterr()
    assert "bad.sh" in captured.out
    assert "shfmt found formatting differences" in captured.err


@pytest.mark.os_agnostic
def test_run_shfmt_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)):
        run_shfmt(files=[script], verbose=True)

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_bashate
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_bashate_returns_zero_on_clean(tmp_path: Path) -> None:
    """Returns 0 when bashate reports no style issues."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)) as mock_run:
        result = run_bashate(files=[script], max_line_length=120, ignores=("E003",))

    assert result == 0
    cmd = mock_run.call_args[0][0]
    assert "--max-line-length=120" in cmd
    assert "--ignore=E003" in cmd


@pytest.mark.os_agnostic
def test_run_bashate_returns_nonzero_on_violations(tmp_path: Path) -> None:
    """Returns non-zero when bashate finds style issues."""
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(1)):
        result = run_bashate(files=[script], max_line_length=120, ignores=())

    assert result == 1


@pytest.mark.os_agnostic
def test_run_bashate_omits_ignore_flag_when_empty(tmp_path: Path) -> None:
    """No --ignore flag when ignores tuple is empty."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)) as mock_run:
        run_bashate(files=[script], max_line_length=80, ignores=())

    cmd = mock_run.call_args[0][0]
    assert not any(arg.startswith("--ignore") for arg in cmd)


@pytest.mark.os_agnostic
def test_run_bashate_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)):
        run_bashate(files=[script], max_line_length=120, ignores=(), verbose=True)

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_returns_zero_when_no_sh_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 and prints skip message when no .sh files exist."""
    result = main(project_dir=tmp_path)

    assert result == 0
    assert "No .sh files found" in capsys.readouterr().out


@pytest.mark.os_agnostic
def test_main_returns_zero_when_all_tools_pass(tmp_path: Path) -> None:
    """Returns 0 when all three linters pass."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    with patch("bmk.makescripts._shellcheck.subprocess.run", return_value=_make_completed(0)):
        result = main(project_dir=tmp_path)

    assert result == 0


@pytest.mark.os_agnostic
def test_main_returns_one_when_shellcheck_fails(tmp_path: Path) -> None:
    """Returns 1 when shellcheck reports violations."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "shellcheck":
            return _make_completed(1)
        return _make_completed(0)

    with patch("bmk.makescripts._shellcheck.subprocess.run", side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1


@pytest.mark.os_agnostic
def test_main_returns_one_when_shfmt_fails(tmp_path: Path) -> None:
    """Returns 1 when shfmt finds formatting differences."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "shfmt":
            return _make_completed(0, stdout="--- diff output\n")
        return _make_completed(0)

    with patch("bmk.makescripts._shellcheck.subprocess.run", side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1


@pytest.mark.os_agnostic
def test_main_returns_one_when_bashate_fails(tmp_path: Path) -> None:
    """Returns 1 when bashate reports style issues."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "bashate":
            return _make_completed(1)
        return _make_completed(0)

    with patch("bmk.makescripts._shellcheck.subprocess.run", side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1


@pytest.mark.os_agnostic
def test_main_aggregates_failures_from_multiple_tools(tmp_path: Path) -> None:
    """Returns 1 when multiple tools fail (runs all tools, doesn't short-circuit)."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )
    call_count = 0

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        return _make_completed(1)

    with patch("bmk.makescripts._shellcheck.subprocess.run", side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1
    assert call_count == 3
