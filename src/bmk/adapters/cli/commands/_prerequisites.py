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


@dataclass(frozen=True, slots=True)
class ToolCheck:
    """Result of checking whether a single external tool is available."""

    name: str
    found: bool
    install_hint: str


def _is_macos() -> bool:
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


def _posix_tools() -> list[ToolCheck]:
    macos = _is_macos()
    tools: list[tuple[str, str]] = [
        ("git", "brew install git" if macos else "sudo apt install git"),
        (
            "pwsh",
            "brew install powershell/tap/powershell"
            if macos
            else "https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell-on-linux",
        ),
        ("shellcheck", "brew install shellcheck" if macos else "sudo apt install shellcheck"),
        ("shfmt", "brew install shfmt" if macos else "sudo apt install shfmt"),
        ("bashate", "pip install bashate"),
    ]
    results: list[ToolCheck] = []
    for name, hint in tools:
        results.append(ToolCheck(name=name, found=_check_tool_on_path(name), install_hint=hint))

    pwsh_result = next(r for r in results if r.name == "pwsh")
    if pwsh_result.found:
        pwsh_path = shutil.which("pwsh") or "pwsh"
        found = _check_psscriptanalyzer(pwsh_path)
    else:
        found = False
    results.append(
        ToolCheck(
            name="PSScriptAnalyzer",
            found=found,
            install_hint="Install-Module PSScriptAnalyzer -Force -Scope CurrentUser (requires pwsh)",
        )
    )
    return results


def _windows_tools() -> list[ToolCheck]:
    results: list[ToolCheck] = [
        ToolCheck(
            name="winget",
            found=_check_tool_on_path("winget"),
            install_hint=(
                'Pre-installed on Windows 11. For Windows 10: install "App Installer" from the Microsoft Store'
            ),
        ),
        ToolCheck(
            name="git",
            found=_check_tool_on_path("git"),
            install_hint="winget install Git.Git",
        ),
        ToolCheck(
            name="pwsh",
            found=_check_tool_on_path("pwsh"),
            install_hint="winget install Microsoft.PowerShell",
        ),
    ]

    pwsh_result = next(r for r in results if r.name == "pwsh")
    if pwsh_result.found:
        pwsh_path = shutil.which("pwsh") or "pwsh"
        found = _check_psscriptanalyzer(pwsh_path)
    else:
        found = False
    results.append(
        ToolCheck(
            name="PSScriptAnalyzer",
            found=found,
            install_hint="Install-Module PSScriptAnalyzer -Force -Scope CurrentUser (requires pwsh)",
        )
    )
    return results


def check_prerequisites() -> list[ToolCheck]:
    """Check all platform-appropriate external tool prerequisites."""
    if sys.platform == "win32":
        return _windows_tools()
    return _posix_tools()


def format_prerequisites_report(results: list[ToolCheck]) -> str:
    """Format check results as a human-readable summary."""
    lines = ["Prerequisites:"]
    for tool in results:
        if tool.found:
            lines.append(f"  \u2713 {tool.name}")
        else:
            lines.append(f"  \u2717 {tool.name} \u2014 not found")
            lines.append(f"      Install: {tool.install_hint}")
    return "\n".join(lines)


__all__ = [
    "ToolCheck",
    "check_prerequisites",
    "format_prerequisites_report",
]
