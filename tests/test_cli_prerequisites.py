"""Prerequisite checking: tool detection and report formatting."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from bmk.adapters.cli.commands._prerequisites import (
    ToolCheck,
    ToolName,
    check_prerequisites,
    format_prerequisites_report,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner


def _fake_which_all_found(name: str) -> str:
    """Pretend every tool is on PATH."""
    return f"/usr/bin/{name}"


def _fake_which_some_missing(name: str) -> str | None:
    """Return a path only for git and pwsh."""
    found = {"git", "pwsh"}
    if name in found:
        return f"/usr/bin/{name}"
    return None


def _fake_psscriptanalyzer_found(
    cmd: list[str],
    *,
    capture_output: bool = False,
    text: bool = False,
    check: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Simulate PSScriptAnalyzer module available."""
    return subprocess.CompletedProcess(cmd, returncode=0, stdout="PSScriptAnalyzer\n", stderr="")


@pytest.mark.os_agnostic
def test_check_prerequisites_posix_all_found() -> None:
    """All POSIX tools present returns all found=True."""
    with (
        patch("bmk.adapters.cli.commands._prerequisites.sys") as mock_sys,
        patch("bmk.adapters.cli.commands._prerequisites.shutil") as mock_shutil,
        patch("bmk.adapters.cli.commands._prerequisites.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "linux"
        mock_shutil.which.side_effect = _fake_which_all_found
        mock_subprocess.run.side_effect = _fake_psscriptanalyzer_found
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        results = check_prerequisites()

    names = {r.name for r in results}
    assert {
        ToolName.GIT,
        ToolName.PWSH,
        ToolName.SHELLCHECK,
        ToolName.SHFMT,
        ToolName.BASHATE,
        ToolName.PSSCRIPTANALYZER,
    } == names
    assert all(r.found for r in results)


@pytest.mark.os_agnostic
def test_check_prerequisites_posix_some_missing() -> None:
    """Mix of found/missing tools on POSIX."""
    with (
        patch("bmk.adapters.cli.commands._prerequisites.sys") as mock_sys,
        patch("bmk.adapters.cli.commands._prerequisites.shutil") as mock_shutil,
        patch("bmk.adapters.cli.commands._prerequisites.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "linux"
        mock_shutil.which.side_effect = _fake_which_some_missing
        mock_subprocess.run.side_effect = _fake_psscriptanalyzer_found
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        results = check_prerequisites()

    by_name = {r.name: r for r in results}
    assert by_name[ToolName.GIT].found is True
    assert by_name[ToolName.PWSH].found is True
    assert by_name[ToolName.SHELLCHECK].found is False
    assert by_name[ToolName.SHFMT].found is False
    assert by_name[ToolName.BASHATE].found is False
    assert by_name[ToolName.PSSCRIPTANALYZER].found is True


@pytest.mark.os_agnostic
def test_check_prerequisites_windows_all_found() -> None:
    """All Windows tools present returns all found=True."""
    with (
        patch("bmk.adapters.cli.commands._prerequisites.sys") as mock_sys,
        patch("bmk.adapters.cli.commands._prerequisites.shutil") as mock_shutil,
        patch("bmk.adapters.cli.commands._prerequisites.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "win32"
        mock_shutil.which.side_effect = _fake_which_all_found
        mock_subprocess.run.side_effect = _fake_psscriptanalyzer_found
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        results = check_prerequisites()

    names = {r.name for r in results}
    assert {ToolName.WINGET, ToolName.GIT, ToolName.PWSH, ToolName.PSSCRIPTANALYZER} == names
    assert all(r.found for r in results)


@pytest.mark.os_agnostic
def test_check_prerequisites_windows_pwsh_missing_skips_psscriptanalyzer() -> None:
    """PSScriptAnalyzer is marked not found when pwsh is absent."""

    def which_no_pwsh(name: str) -> str | None:
        if name == "pwsh":
            return None
        return f"/usr/bin/{name}"

    with (
        patch("bmk.adapters.cli.commands._prerequisites.sys") as mock_sys,
        patch("bmk.adapters.cli.commands._prerequisites.shutil") as mock_shutil,
        patch("bmk.adapters.cli.commands._prerequisites.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "win32"
        mock_shutil.which.side_effect = which_no_pwsh
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        results = check_prerequisites()

    by_name = {r.name: r for r in results}
    assert by_name[ToolName.PWSH].found is False
    assert by_name[ToolName.PSSCRIPTANALYZER].found is False
    # subprocess.run should not be called when pwsh is missing
    mock_subprocess.run.assert_not_called()


@pytest.mark.os_agnostic
def test_check_prerequisites_linux_vs_macos_hints() -> None:
    """Linux hints use apt, macOS hints use brew."""
    with (
        patch("bmk.adapters.cli.commands._prerequisites.sys") as mock_sys,
        patch("bmk.adapters.cli.commands._prerequisites.shutil") as mock_shutil,
        patch("bmk.adapters.cli.commands._prerequisites.subprocess") as mock_subprocess,
    ):
        mock_shutil.which.return_value = None
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        # Linux
        mock_sys.platform = "linux"
        linux_results = check_prerequisites()

        # macOS
        mock_sys.platform = "darwin"
        macos_results = check_prerequisites()

    linux_by_name = {r.name: r for r in linux_results}
    macos_by_name = {r.name: r for r in macos_results}

    assert "apt" in linux_by_name[ToolName.SHELLCHECK].install_hint
    assert "brew" in macos_by_name[ToolName.SHELLCHECK].install_hint
    assert "apt" in linux_by_name[ToolName.GIT].install_hint
    assert "brew" in macos_by_name[ToolName.GIT].install_hint


@pytest.mark.os_agnostic
def test_format_report_shows_checkmarks_and_hints() -> None:
    """Report uses checkmark for found, cross + hint for missing."""
    results = [
        ToolCheck(name=ToolName.GIT, found=True, install_hint="sudo apt install git"),
        ToolCheck(name=ToolName.SHELLCHECK, found=False, install_hint="sudo apt install shellcheck"),
        ToolCheck(name=ToolName.PWSH, found=True, install_hint="brew install powershell"),
    ]

    report = format_prerequisites_report(results)

    assert "Prerequisites:" in report
    assert "\u2713 git" in report
    assert "\u2713 pwsh" in report
    assert "\u2717 shellcheck" in report
    assert "Install: sudo apt install shellcheck" in report
    assert "\u2717 git" not in report
    assert "\u2717 pwsh" not in report


@pytest.mark.os_agnostic
def test_format_report_renders_the_tool_name_value_byte_for_byte() -> None:
    """The whole report is pinned, not probed with ``in``.

    ToolCheck.name is a str-mixin Enum: f"{member}" renders its value on 3.10 but
    ``ToolName.X`` on 3.11+, so a substring check could pass on one interpreter while
    the report changed on another. Comparing the full text catches either drift.
    """
    check, cross = chr(0x2713), chr(0x2717)
    results = [
        ToolCheck(name=ToolName.GIT, found=True, install_hint="sudo apt install git"),
        ToolCheck(name=ToolName.PSSCRIPTANALYZER, found=False, install_hint="Install-Module PSScriptAnalyzer"),
    ]

    report = format_prerequisites_report(results)

    assert report == (
        f"Prerequisites:\n  {check} git\n  {cross} PSScriptAnalyzer - not found\n"
        "      Install: Install-Module PSScriptAnalyzer"
    )


@pytest.mark.os_agnostic
def test_install_command_shows_prerequisites(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bmk install output includes prerequisites section."""
    monkeypatch.chdir(tmp_path)

    with (
        patch("bmk.adapters.cli.commands._prerequisites.shutil") as mock_shutil,
        patch("bmk.adapters.cli.commands._prerequisites.subprocess") as mock_subprocess,
    ):
        mock_shutil.which.return_value = "/usr/bin/fake"
        mock_subprocess.run.side_effect = _fake_psscriptanalyzer_found
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        from bmk.adapters.cli import cli

        result = cli_runner.invoke(cli, ["install"], obj=production_factory)

    assert result.exit_code == 0
    assert "Prerequisites:" in result.output


@pytest.mark.os_agnostic
def test_install_shows_prerequisites_even_when_makefile_skipped(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prerequisites report appears even when Makefile is not managed by bmk."""
    monkeypatch.chdir(tmp_path)
    Path("Makefile").write_text("# custom makefile\n", encoding="utf-8")

    with (
        patch("bmk.adapters.cli.commands._prerequisites.shutil") as mock_shutil,
        patch("bmk.adapters.cli.commands._prerequisites.subprocess") as mock_subprocess,
    ):
        mock_shutil.which.return_value = "/usr/bin/fake"
        mock_subprocess.run.side_effect = _fake_psscriptanalyzer_found
        mock_subprocess.TimeoutExpired = subprocess.TimeoutExpired

        from bmk.adapters.cli import cli

        result = cli_runner.invoke(cli, ["install"], obj=production_factory)

    assert result.exit_code != 0
    assert "skipping" in result.output
    assert "Prerequisites:" in result.output
