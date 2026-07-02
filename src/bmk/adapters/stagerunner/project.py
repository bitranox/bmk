"""Pyproject-derived data used to build tool argv lists.

In-process, thread-safe readers for the two values the shell stages fetched via
helper scripts: the importable package name (for bandit's ``src/<pkg>`` target)
and pip-audit's ``--ignore-vuln`` flags. The ``makescripts`` CLI shims for these
remain during migration; this is their in-package port (canonical after Phase 5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import rtoml


def _load(pyproject: Path) -> dict[str, Any]:
    if not pyproject.is_file():
        return {}
    return rtoml.load(pyproject)


def derive_package_name(pyproject: Path) -> str | None:
    """Derive the importable package name (hatch wheel -> script entry -> project name)."""
    data = _load(pyproject)
    if not data:
        return None

    wheel = data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    packages = wheel.get("packages", [])
    if packages:
        return Path(str(packages[0])).name

    scripts = data.get("project", {}).get("scripts", {})
    for spec in scripts.values():
        if isinstance(spec, str) and ":" in spec:
            return spec.split(":", 1)[0].split(".", 1)[0]

    name = data.get("project", {}).get("name", "")
    if isinstance(name, str) and name:
        return name.replace("-", "_")
    return None


def pip_audit_ignore_flags(pyproject: Path) -> list[str]:
    """Return ``--ignore-vuln=<ID>`` flags from ``[tool.pip-audit].ignore-vulns``."""
    data = _load(pyproject)
    ignores = data.get("tool", {}).get("pip-audit", {}).get("ignore-vulns", [])
    return [f"--ignore-vuln={vuln}" for vuln in ignores if isinstance(vuln, str)]


__all__ = ["derive_package_name", "pip_audit_ignore_flags"]
