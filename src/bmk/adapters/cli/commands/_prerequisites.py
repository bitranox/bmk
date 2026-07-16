"""Prerequisite tool checking for bmk install.

Internal module (underscore prefix) that verifies required external tools
are present on the system and formats installation instructions for any
that are missing.

Contents:
    * :class:`ToolCheck` - Frozen result of a single tool presence check.
    * :func:`check_prerequisites` - Check all platform-appropriate prerequisites.
    * :func:`format_prerequisites_report` - Format results as human-readable summary.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum


class ToolName(str, Enum):
    """External tools bmk probes for and, where possible, installs.

    The single definition of the tool vocabulary that ``_prerequisites`` and
    ``_ensure`` dispatch on. Inherits from str so a member equals its wire name:
    for every tool except :attr:`PSSCRIPTANALYZER` (a PowerShell module) the value
    is the executable looked up on ``PATH``, and it is also the label shown in the
    reports.
    """

    GIT = "git"
    PWSH = "pwsh"
    SHELLCHECK = "shellcheck"
    SHFMT = "shfmt"
    BASHATE = "bashate"
    WINGET = "winget"
    PSSCRIPTANALYZER = "PSScriptAnalyzer"


@dataclass(frozen=True, slots=True)
class ToolCheck:
    """Result of checking whether a single external tool is available."""

    name: str
    found: bool
    install_hint: str


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def _check_tool_on_path(name: str) -> bool:
    return shutil.which(name) is not None


def _check_psscriptanalyzer(pwsh_path: str) -> bool:
    """Check if PSScriptAnalyzer PowerShell module is available."""
    try:
        result = subprocess.run(  # noqa: S603
            [pwsh_path, "-NoProfile", "-Command", "Get-Module -ListAvailable PSScriptAnalyzer"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        return result.returncode == 0 and "PSScriptAnalyzer" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _append_psscriptanalyzer_check(results: list[ToolCheck]) -> None:
    """Check PSScriptAnalyzer availability and append result to the list.

    Only probes the module when pwsh is already found in *results*.
    """
    pwsh_result = next(r for r in results if r.name == ToolName.PWSH)
    if pwsh_result.found:
        pwsh_path = shutil.which(ToolName.PWSH.value) or ToolName.PWSH.value
        found = _check_psscriptanalyzer(pwsh_path)
    else:
        found = False
    results.append(
        ToolCheck(
            name=ToolName.PSSCRIPTANALYZER.value,
            found=found,
            install_hint="Install-Module PSScriptAnalyzer -Force -Scope CurrentUser (requires pwsh)",
        )
    )


def _posix_tools() -> list[ToolCheck]:
    macos = is_macos()
    tools: list[tuple[str, str]] = [
        (ToolName.GIT.value, "brew install git" if macos else "sudo apt install git"),
        (
            ToolName.PWSH.value,
            "brew install powershell/tap/powershell"
            if macos
            else "https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-linux",
        ),
        (ToolName.SHELLCHECK.value, "brew install shellcheck" if macos else "sudo apt install shellcheck"),
        (ToolName.SHFMT.value, "brew install shfmt" if macos else "sudo apt install shfmt"),
        (ToolName.BASHATE.value, "pip install bashate"),
    ]
    results: list[ToolCheck] = []
    for name, hint in tools:
        results.append(ToolCheck(name=name, found=_check_tool_on_path(name), install_hint=hint))
    _append_psscriptanalyzer_check(results)
    return results


def _windows_tools() -> list[ToolCheck]:
    results: list[ToolCheck] = [
        ToolCheck(
            name=ToolName.WINGET.value,
            found=_check_tool_on_path(ToolName.WINGET.value),
            install_hint=(
                'Pre-installed on Windows 11. For Windows 10: install "App Installer" from the Microsoft Store'
            ),
        ),
        ToolCheck(
            name=ToolName.GIT.value,
            found=_check_tool_on_path(ToolName.GIT.value),
            install_hint="winget install Git.Git",
        ),
        ToolCheck(
            name=ToolName.PWSH.value,
            found=_check_tool_on_path(ToolName.PWSH.value),
            install_hint="winget install Microsoft.PowerShell",
        ),
    ]
    _append_psscriptanalyzer_check(results)
    return results


def check_prerequisites() -> list[ToolCheck]:
    """Check all platform-appropriate external tool prerequisites."""
    if is_windows():
        return _windows_tools()
    return _posix_tools()


def format_prerequisites_report(results: list[ToolCheck]) -> str:
    """Format check results as a human-readable summary."""
    lines = ["Prerequisites:"]
    for tool in results:
        if tool.found:
            lines.append(f"  \u2713 {tool.name}")
        else:
            lines.append(f"  \u2717 {tool.name} - not found")
            lines.append(f"      Install: {tool.install_hint}")
    return "\n".join(lines)


__all__ = [
    "ToolCheck",
    "ToolName",
    "check_prerequisites",
    "format_prerequisites_report",
    "is_macos",
    "is_windows",
]
