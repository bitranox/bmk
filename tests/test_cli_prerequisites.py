"""Prerequisite checking: tool detection and report formatting."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bmk.adapters.cli.commands._prerequisites import (
    ToolCheck,
    check_prerequisites,
    format_prerequisites_report,
)


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
    assert {"git", "pwsh", "shellcheck", "shfmt", "bashate", "PSScriptAnalyzer"} == names
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
    assert by_name["git"].found is True
    assert by_name["pwsh"].found is True
    assert by_name["shellcheck"].found is False
    assert by_name["shfmt"].found is False
    assert by_name["bashate"].found is False
    assert by_name["PSScriptAnalyzer"].found is True


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
    assert {"winget", "git", "pwsh", "PSScriptAnalyzer"} == names
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
    assert by_name["pwsh"].found is False
    assert by_name["PSScriptAnalyzer"].found is False
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

    assert "apt" in linux_by_name["shellcheck"].install_hint
    assert "brew" in macos_by_name["shellcheck"].install_hint
    assert "apt" in linux_by_name["git"].install_hint
    assert "brew" in macos_by_name["git"].install_hint


@pytest.mark.os_agnostic
def test_format_report_shows_checkmarks_and_hints() -> None:
    """Report uses checkmark for found, cross + hint for missing."""
    results = [
        ToolCheck(name="git", found=True, install_hint="sudo apt install git"),
        ToolCheck(name="shellcheck", found=False, install_hint="sudo apt install shellcheck"),
        ToolCheck(name="pwsh", found=True, install_hint="brew install powershell"),
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
