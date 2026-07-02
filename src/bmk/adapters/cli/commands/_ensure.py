"""Install missing external tools per-OS (the ``bmk ensure`` backend).

Reuses :func:`_prerequisites.check_prerequisites` to detect the required host
tools, then for each missing one runs its platform-appropriate installer,
best-effort, and reports a per-tool outcome.

Install strategy:
    * shellcheck / shfmt / bashate: pip (the ``shellcheck-py`` / ``shfmt-py`` /
      ``bashate`` wrappers, which are bmk's own runtime deps).
    * git: system package manager (apt-get/dnf/pacman/zypper on Linux, brew on
      macOS, winget on Windows).
    * pwsh: brew (macOS) / winget (Windows); on Linux it is not in the default
      repos, so it is skipped with a hint.
    * PSScriptAnalyzer: ``Install-Module`` via the existing
      :func:`ensure_psscriptanalyzer` (a PowerShell module, not a winget package).
    * winget: never installed by bmk (Microsoft "App Installer"); skipped with a
      hint when absent.

Contents:
    * :class:`InstallOutcome` - Per-tool result category.
    * :class:`EnsureResult` - Outcome plus detail for a single tool.
    * :func:`format_ensure_report` - Render results as a human-readable summary.
    * :func:`run_ensure` - Detect, install-if-missing, report, and return an exit code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

import rich_click as click

from ..exit_codes import ExitCode
from ._prerequisites import ToolCheck, check_prerequisites


class InstallOutcome(str, Enum):
    """Result category for a single tool after an ensure pass."""

    ALREADY_PRESENT = "already-present"
    INSTALLED = "installed"
    WOULD_INSTALL = "would-install"
    SKIPPED = "skipped"
    FAILED = "failed"


class _InstallKind(str, Enum):
    """How a missing tool should be installed."""

    ARGV = "argv"  # run a system command (pip / pkg-mgr / winget / brew)
    MODULE = "module"  # PowerShell module via ensure_psscriptanalyzer
    NONE = "none"  # no installer on this platform -> skip with a reason


@dataclass(frozen=True, slots=True)
class _InstallAction:
    """A resolved plan for installing one missing tool."""

    kind: _InstallKind
    argv: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EnsureResult:
    """Outcome of ensuring a single tool, with a human-readable detail."""

    name: str
    outcome: InstallOutcome
    detail: str = ""


# --- platform / environment probes -----------------------------------------

_PIP_PACKAGES: dict[str, str] = {
    "shellcheck": "shellcheck-py",
    "shfmt": "shfmt-py",
    "bashate": "bashate",
}

# Ordered by preference; the first whose executable is on PATH wins.
_LINUX_PKG_MANAGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("apt-get", ("install", "-y")),
    ("dnf", ("install", "-y")),
    ("pacman", ("-S", "--noconfirm")),
    ("zypper", ("install", "-y")),
)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _externally_managed() -> bool:
    """Whether this interpreter is a PEP 668 externally-managed install."""
    from pathlib import Path

    prefix = Path(sys.prefix)
    if (prefix / "EXTERNALLY-MANAGED").exists():
        return True
    versioned = prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "EXTERNALLY-MANAGED"
    return versioned.exists()


def _pip_install_argv(package: str) -> tuple[str, ...]:
    """Build the pip-install argv, guarding PEP 668 on Linux like _dependencies."""
    argv = [sys.executable, "-m", "pip", "install", package]
    if sys.platform.startswith("linux") and _externally_managed():
        argv.append("--break-system-packages")
    return tuple(argv)


def _detect_linux_pkg_manager() -> tuple[str, tuple[str, ...]] | None:
    """Return the first available Linux package manager and its install subcommand."""
    for exe, subcmd in _LINUX_PKG_MANAGERS:
        if shutil.which(exe) is not None:
            return exe, subcmd
    return None


def _privilege_prefix() -> tuple[str, ...] | None:
    """Prefix needed to run a system install as root.

    Returns an empty tuple when already root, ``("sudo",)`` when escalation is
    available, or ``None`` when neither is possible.
    """
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() == 0:
        return ()
    if shutil.which("sudo") is not None:
        return ("sudo",)
    return None


# --- install planning ------------------------------------------------------


def _system_action(
    *,
    linux_pkg: str | None,
    mac_argv: tuple[str, ...],
    win_argv: tuple[str, ...],
    skip_reason: str,
) -> _InstallAction:
    """Resolve a system-package install for the current OS.

    ``linux_pkg=None`` means the tool has no reliable default-repo package on
    Linux (e.g. pwsh), so it is skipped with ``skip_reason``.
    """
    if _is_windows():
        return _InstallAction(_InstallKind.ARGV, win_argv)
    if _is_macos():
        return _InstallAction(_InstallKind.ARGV, mac_argv)
    if linux_pkg is None:
        return _InstallAction(_InstallKind.NONE, reason=skip_reason)
    manager = _detect_linux_pkg_manager()
    if manager is None:
        return _InstallAction(_InstallKind.NONE, reason=f"no supported package manager found ({skip_reason})")
    prefix = _privilege_prefix()
    if prefix is None:
        return _InstallAction(_InstallKind.NONE, reason=f"root or sudo required to install {linux_pkg}")
    exe, subcmd = manager
    return _InstallAction(_InstallKind.ARGV, (*prefix, exe, *subcmd, linux_pkg))


def _action_for(check: ToolCheck) -> _InstallAction:
    """Resolve how to install a single missing tool on this OS."""
    name = check.name
    if name in _PIP_PACKAGES:
        return _InstallAction(_InstallKind.ARGV, _pip_install_argv(_PIP_PACKAGES[name]))
    if name == "PSScriptAnalyzer":
        return _InstallAction(_InstallKind.MODULE)
    if name == "git":
        return _system_action(
            linux_pkg="git",
            mac_argv=("brew", "install", "git"),
            win_argv=("winget", "install", "--id", "Git.Git", "-e", "--source", "winget"),
            skip_reason=check.install_hint,
        )
    if name == "pwsh":
        return _system_action(
            linux_pkg=None,  # not in default Linux repos; MS-repo setup is out of scope
            mac_argv=("brew", "install", "--cask", "powershell"),
            win_argv=("winget", "install", "--id", "Microsoft.PowerShell", "-e", "--source", "winget"),
            skip_reason=check.install_hint,
        )
    # winget itself and anything unrecognised: no installer -> skip with the hint.
    return _InstallAction(_InstallKind.NONE, reason=check.install_hint)


# --- execution -------------------------------------------------------------


def _install_module(check: ToolCheck, *, dry_run: bool) -> EnsureResult:
    """Install a PowerShell module (PSScriptAnalyzer) via the existing helper."""
    from bmk.adapters.stagerunner.helpers._psscriptanalyzer import check_pwsh, ensure_psscriptanalyzer

    pwsh = check_pwsh()
    if pwsh is None:
        return EnsureResult(check.name, InstallOutcome.SKIPPED, "pwsh not available (install pwsh first)")
    if dry_run:
        return EnsureResult(check.name, InstallOutcome.WOULD_INSTALL, "Install-Module PSScriptAnalyzer")
    try:
        ensure_psscriptanalyzer(pwsh)
    except (OSError, subprocess.SubprocessError) as exc:
        return EnsureResult(check.name, InstallOutcome.FAILED, f"Install-Module PSScriptAnalyzer: {exc}")
    return EnsureResult(check.name, InstallOutcome.INSTALLED, "Install-Module PSScriptAnalyzer")


def _run_install(check: ToolCheck, action: _InstallAction, *, dry_run: bool) -> EnsureResult:
    """Execute one resolved install action and classify the outcome."""
    if action.kind is _InstallKind.NONE:
        return EnsureResult(check.name, InstallOutcome.SKIPPED, action.reason)
    if action.kind is _InstallKind.MODULE:
        return _install_module(check, dry_run=dry_run)
    command = " ".join(action.argv)
    if dry_run:
        return EnsureResult(check.name, InstallOutcome.WOULD_INSTALL, command)
    try:
        completed = subprocess.run(list(action.argv), check=False)  # noqa: S603
    except OSError as exc:
        return EnsureResult(check.name, InstallOutcome.FAILED, f"{command}: {exc}")
    if completed.returncode == 0:
        return EnsureResult(check.name, InstallOutcome.INSTALLED, command)
    return EnsureResult(check.name, InstallOutcome.FAILED, f"{command} (exit {completed.returncode})")


# --- reporting -------------------------------------------------------------

_OUTCOME_GLYPH: dict[InstallOutcome, str] = {
    InstallOutcome.ALREADY_PRESENT: "\u2713",  # check mark
    InstallOutcome.INSTALLED: "\u2713",
    InstallOutcome.WOULD_INSTALL: "\u2192",  # right arrow
    InstallOutcome.SKIPPED: "\u2717",  # cross
    InstallOutcome.FAILED: "\u2717",
}

_DETAILED_OUTCOMES: frozenset[InstallOutcome] = frozenset(
    {InstallOutcome.WOULD_INSTALL, InstallOutcome.SKIPPED, InstallOutcome.FAILED}
)


def format_ensure_report(results: list[EnsureResult]) -> str:
    """Format ensure results as a human-readable summary."""
    lines = ["Ensure external tools:"]
    for result in results:
        glyph = _OUTCOME_GLYPH[result.outcome]
        lines.append(f"  {glyph} {result.name}: {result.outcome.value}")
        if result.detail and result.outcome in _DETAILED_OUTCOMES:
            lines.append(f"      {result.detail}")
    return "\n".join(lines)


def _exit_code(results: list[EnsureResult], *, dry_run: bool, strict: bool) -> int:
    """Derive the process exit code from the collected outcomes."""
    if dry_run:
        return int(ExitCode.SUCCESS)
    if any(r.outcome is InstallOutcome.FAILED for r in results):
        return int(ExitCode.GENERAL_ERROR)
    if strict and any(r.outcome is InstallOutcome.SKIPPED for r in results):
        return int(ExitCode.GENERAL_ERROR)
    return int(ExitCode.SUCCESS)


def ensure_tools(*, dry_run: bool = False) -> list[EnsureResult]:
    """Detect required tools and install the missing ones, returning per-tool results."""
    results: list[EnsureResult] = []
    for check in check_prerequisites():
        if check.found:
            results.append(EnsureResult(check.name, InstallOutcome.ALREADY_PRESENT))
            continue
        results.append(_run_install(check, _action_for(check), dry_run=dry_run))
    return results


def run_ensure(*, dry_run: bool = False, strict: bool = False, quiet: bool = False) -> int:
    """Ensure external tools are installed; print a report and return an exit code."""
    results = ensure_tools(dry_run=dry_run)
    if not quiet:
        click.echo(format_ensure_report(results))
    return _exit_code(results, dry_run=dry_run, strict=strict)


__all__ = [
    "EnsureResult",
    "InstallOutcome",
    "ensure_tools",
    "format_ensure_report",
    "run_ensure",
]
