"""Behaviour tests for makescripts._psscriptanalyzer: config reading, pwsh detection, file discovery, and orchestration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bmk.makescripts._psscriptanalyzer import (
    check_pwsh,
    ensure_psscriptanalyzer,
    find_ps1_files,
    get_excluded_rules,
    main,
    run_psscriptanalyzer,
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


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# ensure_psscriptanalyzer
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_ensure_psscriptanalyzer_skips_install_when_present() -> None:
    """Does not install when PSScriptAnalyzer is already available."""
    with patch(
        "bmk.makescripts._psscriptanalyzer.subprocess.run",
        return_value=_make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
    ) as mock_run:
        ensure_psscriptanalyzer("/usr/bin/pwsh")

    mock_run.assert_called_once()
    assert "Get-Module" in mock_run.call_args[0][0][3]


@pytest.mark.os_agnostic
def test_ensure_psscriptanalyzer_installs_when_missing() -> None:
    """Installs module when PSScriptAnalyzer is not found."""
    with patch("bmk.makescripts._psscriptanalyzer.subprocess.run") as mock_run:
        mock_run.side_effect = [
            _make_completed(0, stdout=""),
            _make_completed(0),
        ]
        ensure_psscriptanalyzer("/usr/bin/pwsh")

    assert mock_run.call_count == 2
    install_cmd = mock_run.call_args_list[1][0][0]
    assert "Install-Module" in install_cmd[3]


# ---------------------------------------------------------------------------
# run_psscriptanalyzer
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_returns_zero_on_clean(tmp_path: Path) -> None:
    """Returns 0 when PSScriptAnalyzer reports no violations."""
    with patch("bmk.makescripts._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)) as mock_run:
        result = run_psscriptanalyzer(
            pwsh="/usr/bin/pwsh",
            project_dir=tmp_path,
            exclude_rules=("PSAvoidUsingWriteHost",),
        )

    assert result == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "/usr/bin/pwsh"
    assert "Invoke-ScriptAnalyzer" in cmd[3]
    assert "PSAvoidUsingWriteHost" in cmd[3]


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_returns_nonzero_on_violations(tmp_path: Path) -> None:
    """Returns non-zero when PSScriptAnalyzer finds violations."""
    with patch("bmk.makescripts._psscriptanalyzer.subprocess.run", return_value=_make_completed(3)):
        result = run_psscriptanalyzer(
            pwsh="/usr/bin/pwsh",
            project_dir=tmp_path,
            exclude_rules=(),
        )

    assert result == 3


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    with patch("bmk.makescripts._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)):
        run_psscriptanalyzer(
            pwsh="/usr/bin/pwsh",
            project_dir=tmp_path,
            exclude_rules=("PSAvoidUsingWriteHost",),
            verbose=True,
        )

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_returns_zero_when_pwsh_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 and prints skip message when pwsh is absent."""
    with patch("bmk.makescripts._psscriptanalyzer.shutil.which", return_value=None):
        result = main(project_dir=Path("/nonexistent"))

    assert result == 0
    assert "pwsh not found" in capsys.readouterr().out


@pytest.mark.os_agnostic
def test_main_returns_zero_when_no_ps1_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 and prints skip message when no .ps1 files exist."""
    with (
        patch("bmk.makescripts._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"),
        patch(
            "bmk.makescripts._psscriptanalyzer.subprocess.run",
            return_value=_make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
        ),
    ):
        result = main(project_dir=tmp_path)

    assert result == 0
    assert "No .ps1 files found" in capsys.readouterr().out


@pytest.mark.os_agnostic
def test_main_returns_zero_when_lint_passes(tmp_path: Path) -> None:
    """Returns 0 when PSScriptAnalyzer finds no violations."""
    (tmp_path / "script.ps1").write_text("Write-Output 'hello'\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.psscriptanalyzer]\nexclude-rules = ["PSAvoidUsingWriteHost"]\n'
    )

    with (
        patch("bmk.makescripts._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"),
        patch("bmk.makescripts._psscriptanalyzer.subprocess.run") as mock_run,
    ):
        mock_run.side_effect = [
            _make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
            _make_completed(0),
        ]
        result = main(project_dir=tmp_path)

    assert result == 0


@pytest.mark.os_agnostic
def test_main_returns_nonzero_when_lint_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns non-zero and prints error when PSScriptAnalyzer finds violations."""
    (tmp_path / "script.ps1").write_text("Write-Output 'hello'\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.psscriptanalyzer]\nexclude-rules = ["PSAvoidUsingWriteHost"]\n'
    )

    with (
        patch("bmk.makescripts._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"),
        patch("bmk.makescripts._psscriptanalyzer.subprocess.run") as mock_run,
    ):
        mock_run.side_effect = [
            _make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
            _make_completed(2),
        ]
        result = main(project_dir=tmp_path)

    assert result == 2
    assert "PSScriptAnalyzer found lint violations" in capsys.readouterr().err
