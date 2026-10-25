"""Tests for the ``bmk ensure`` backend (install missing external tools per-OS)."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.commands import _ensure
from bmk.adapters.cli.commands._ensure import (
    EnsureResult,
    InstallKind,
    InstallOutcome,
    PkgManager,
    action_for,
    ensure_tools,
    format_ensure_report,
    pip_install_argv,
    run_ensure,
    run_install,
)
from bmk.adapters.cli.commands._prerequisites import ToolCheck, ToolName

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner, Result


def _completed(returncode: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=[], returncode=returncode)


def _fake_run(returncode: int) -> Callable[..., subprocess.CompletedProcess[bytes]]:
    """A typed subprocess.run replacement that returns a fixed exit code."""

    def _run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return _completed(returncode)

    return _run


def _noop_install(_pwsh: str) -> None:
    """A typed ensure_psscriptanalyzer replacement that succeeds."""
    return None


def _missing(name: ToolName, hint: str = "hint") -> ToolCheck:
    return ToolCheck(name=name, found=False, install_hint=hint)


# --- action_for: pip tools -------------------------------------------------


@pytest.mark.os_agnostic
def test_action_for_pip_tool_builds_pip_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ensure, "_externally_managed", lambda: False)
    action = action_for(_missing(ToolName.SHELLCHECK))
    assert action.kind is InstallKind.ARGV
    assert action.argv == (sys.executable, "-m", "pip", "install", "shellcheck-py")


@pytest.mark.os_agnostic
def test_pip_install_argv_adds_break_system_packages_when_managed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_ensure, "_externally_managed", lambda: True)
    argv = pip_install_argv("bashate")
    assert argv[-1] == "--break-system-packages"


@pytest.mark.os_agnostic
def test_pip_install_argv_no_flag_when_not_managed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_ensure, "_externally_managed", lambda: False)
    assert "--break-system-packages" not in pip_install_argv("bashate")


# --- action_for: git across OSes ------------------------------------------


@pytest.mark.os_agnostic
def test_action_for_git_linux_uses_pkg_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_ensure, "_detect_linux_pkg_manager", lambda: PkgManager("apt-get", ("install", "-y")))
    monkeypatch.setattr(_ensure, "_privilege_prefix", lambda: ("sudo",))
    action = action_for(_missing(ToolName.GIT))
    assert action.kind is InstallKind.ARGV
    assert action.argv == ("sudo", "apt-get", "install", "-y", "git")


@pytest.mark.os_agnostic
def test_action_for_git_linux_root_has_no_sudo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_ensure, "_detect_linux_pkg_manager", lambda: PkgManager("dnf", ("install", "-y")))
    monkeypatch.setattr(_ensure, "_privilege_prefix", lambda: ())
    action = action_for(_missing(ToolName.GIT))
    assert action.argv == ("dnf", "install", "-y", "git")


@pytest.mark.os_agnostic
def test_action_for_git_linux_no_pkg_manager_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_ensure, "_detect_linux_pkg_manager", lambda: None)
    action = action_for(_missing(ToolName.GIT))
    assert action.kind is InstallKind.NONE


@pytest.mark.os_agnostic
def test_action_for_git_linux_no_privilege_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_ensure, "_detect_linux_pkg_manager", lambda: PkgManager("apt-get", ("install", "-y")))
    monkeypatch.setattr(_ensure, "_privilege_prefix", lambda: None)
    action = action_for(_missing(ToolName.GIT))
    assert action.kind is InstallKind.NONE
    assert "sudo" in action.reason


@pytest.mark.os_agnostic
def test_action_for_git_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert action_for(_missing(ToolName.GIT)).argv == ("brew", "install", "git")


@pytest.mark.os_agnostic
def test_action_for_git_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    action = action_for(_missing(ToolName.GIT))
    assert action.argv == ("winget", "install", "--id", "Git.Git", "-e", "--source", "winget")


# --- action_for: pwsh / winget / psscriptanalyzer -------------------------


@pytest.mark.os_agnostic
def test_action_for_pwsh_linux_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    action = action_for(_missing(ToolName.PWSH, "see docs"))
    assert action.kind is InstallKind.NONE
    assert action.reason == "see docs"


@pytest.mark.os_agnostic
def test_action_for_pwsh_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    action = action_for(_missing(ToolName.PWSH))
    assert action.argv == ("winget", "install", "--id", "Microsoft.PowerShell", "-e", "--source", "winget")


@pytest.mark.os_agnostic
def test_action_for_winget_has_no_installer() -> None:
    action = action_for(_missing(ToolName.WINGET, "install App Installer"))
    assert action.kind is InstallKind.NONE
    assert action.reason == "install App Installer"


@pytest.mark.os_agnostic
def test_action_for_psscriptanalyzer_is_module() -> None:
    assert action_for(_missing(ToolName.PSSCRIPTANALYZER)).kind is InstallKind.MODULE


# --- run_install: execution outcomes --------------------------------------


@pytest.mark.os_agnostic
def test_run_install_argv_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ensure.subprocess, "run", _fake_run(0))
    action = _ensure.InstallAction(InstallKind.ARGV, ("brew", "install", "git"))
    result = run_install(_missing(ToolName.GIT), action, dry_run=False)
    assert result.outcome is InstallOutcome.INSTALLED
    assert result.detail == "brew install git"


@pytest.mark.os_agnostic
def test_run_install_argv_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ensure.subprocess, "run", _fake_run(2))
    action = _ensure.InstallAction(InstallKind.ARGV, ("brew", "install", "git"))
    result = run_install(_missing(ToolName.GIT), action, dry_run=False)
    assert result.outcome is InstallOutcome.FAILED
    assert "exit 2" in result.detail


@pytest.mark.os_agnostic
def test_run_install_argv_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> subprocess.CompletedProcess[bytes]:
        raise OSError("no such file")

    monkeypatch.setattr(_ensure.subprocess, "run", _boom)
    action = _ensure.InstallAction(InstallKind.ARGV, ("winget", "install"))
    result = run_install(_missing(ToolName.GIT), action, dry_run=False)
    assert result.outcome is InstallOutcome.FAILED


@pytest.mark.os_agnostic
def test_run_install_dry_run_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _guard(*_a: object, **_k: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal called
        called = True
        return _completed(0)

    monkeypatch.setattr(_ensure.subprocess, "run", _guard)
    action = _ensure.InstallAction(InstallKind.ARGV, ("brew", "install", "git"))
    result = run_install(_missing(ToolName.GIT), action, dry_run=True)
    assert result.outcome is InstallOutcome.WOULD_INSTALL
    assert result.detail == "brew install git"
    assert called is False


@pytest.mark.os_agnostic
def test_run_install_none_skips() -> None:
    action = _ensure.InstallAction(InstallKind.NONE, reason="no installer")
    result = run_install(_missing(ToolName.WINGET), action, dry_run=False)
    assert result.outcome is InstallOutcome.SKIPPED
    assert result.detail == "no installer"


# --- PSScriptAnalyzer module path ------------------------------------------


@pytest.mark.os_agnostic
def test_install_module_skips_without_pwsh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bmk.adapters.stagerunner.helpers._psscriptanalyzer.check_pwsh", lambda: None)
    action = _ensure.InstallAction(InstallKind.MODULE)
    result = run_install(_missing(ToolName.PSSCRIPTANALYZER), action, dry_run=False)
    assert result.outcome is InstallOutcome.SKIPPED


@pytest.mark.os_agnostic
def test_install_module_installs_with_pwsh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bmk.adapters.stagerunner.helpers._psscriptanalyzer.check_pwsh", lambda: "/usr/bin/pwsh")
    monkeypatch.setattr("bmk.adapters.stagerunner.helpers._psscriptanalyzer.ensure_psscriptanalyzer", _noop_install)
    action = _ensure.InstallAction(InstallKind.MODULE)
    result = run_install(_missing(ToolName.PSSCRIPTANALYZER), action, dry_run=False)
    assert result.outcome is InstallOutcome.INSTALLED


@pytest.mark.os_agnostic
def test_install_module_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_pwsh: str) -> None:
        raise subprocess.CalledProcessError(1, "pwsh")

    monkeypatch.setattr("bmk.adapters.stagerunner.helpers._psscriptanalyzer.check_pwsh", lambda: "/usr/bin/pwsh")
    monkeypatch.setattr("bmk.adapters.stagerunner.helpers._psscriptanalyzer.ensure_psscriptanalyzer", _raise)
    result = run_install(_missing(ToolName.PSSCRIPTANALYZER), _ensure.InstallAction(InstallKind.MODULE), dry_run=False)
    assert result.outcome is InstallOutcome.FAILED


# --- ensure_tools / run_ensure orchestration -------------------------------


@pytest.mark.os_agnostic
def test_ensure_tools_reports_already_present_without_installing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ensure, "check_prerequisites", lambda: [ToolCheck(ToolName.GIT, found=True, install_hint="")])

    def _fail(*_a: object, **_k: object) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("should not install a present tool")

    monkeypatch.setattr(_ensure.subprocess, "run", _fail)
    results = ensure_tools()
    assert results == [EnsureResult(ToolName.GIT, InstallOutcome.ALREADY_PRESENT)]


@pytest.mark.os_agnostic
def test_run_ensure_installs_missing_and_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        _ensure, "check_prerequisites", lambda: [ToolCheck(ToolName.GIT, found=False, install_hint="h")]
    )
    monkeypatch.setattr(_ensure.subprocess, "run", _fake_run(0))
    code = run_ensure(quiet=True)
    assert code == 0


@pytest.mark.os_agnostic
def test_run_ensure_failed_install_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        _ensure, "check_prerequisites", lambda: [ToolCheck(ToolName.GIT, found=False, install_hint="h")]
    )
    monkeypatch.setattr(_ensure.subprocess, "run", _fake_run(1))
    assert run_ensure(quiet=True) != 0


@pytest.mark.os_agnostic
def test_run_ensure_strict_nonzero_when_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        _ensure, "check_prerequisites", lambda: [ToolCheck(ToolName.PWSH, found=False, install_hint="h")]
    )
    assert run_ensure(strict=True, quiet=True) != 0
    assert run_ensure(strict=False, quiet=True) == 0


@pytest.mark.os_agnostic
def test_run_ensure_dry_run_exits_zero_even_with_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        _ensure, "check_prerequisites", lambda: [ToolCheck(ToolName.PWSH, found=False, install_hint="h")]
    )
    assert run_ensure(dry_run=True, strict=True, quiet=True) == 0


# --- reporting --------------------------------------------------------------


@pytest.mark.os_agnostic
def test_format_ensure_report_lists_each_tool() -> None:
    results = [
        EnsureResult(ToolName.GIT, InstallOutcome.INSTALLED, "brew install git"),
        EnsureResult(ToolName.PWSH, InstallOutcome.SKIPPED, "not in repos"),
    ]
    report = format_ensure_report(results)
    assert "git: installed" in report
    assert "pwsh: skipped" in report
    assert "not in repos" in report


@pytest.mark.os_agnostic
def test_format_ensure_report_renders_the_tool_name_value_byte_for_byte() -> None:
    """The whole report is pinned: f"{member}" of a str-mixin Enum differs on 3.10 and 3.11+."""
    check, arrow = chr(0x2713), chr(0x2192)
    results = [
        EnsureResult(ToolName.SHELLCHECK, InstallOutcome.ALREADY_PRESENT),
        EnsureResult(ToolName.PSSCRIPTANALYZER, InstallOutcome.WOULD_INSTALL, "Install-Module PSScriptAnalyzer"),
    ]
    assert format_ensure_report(results) == (
        f"Ensure external tools:\n  {check} shellcheck: already-present\n"
        f"  {arrow} PSScriptAnalyzer: would-install\n      Install-Module PSScriptAnalyzer"
    )


# --- CLI end-to-end ---------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_ensure_command_exists(cli_runner: CliRunner, production_factory: Callable[[], Any]) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, ["ensure", "--help"], obj=production_factory)
    assert result.exit_code == 0
    assert "Install missing external tools" in result.output


@pytest.mark.os_agnostic
def test_cli_ensure_dry_run_end_to_end(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        _ensure,
        "check_prerequisites",
        lambda: [
            ToolCheck(ToolName.GIT, found=True, install_hint=""),
            ToolCheck(ToolName.PWSH, found=False, install_hint="docs"),
        ],
    )
    result: Result = cli_runner.invoke(cli_mod.cli, ["ensure", "--dry-run"], obj=production_factory)
    assert result.exit_code == 0
    assert "Ensure external tools:" in result.output
    assert "git" in result.output
