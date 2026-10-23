"""Pyproject-derived data used to build tool argv lists.

In-process, thread-safe readers for the two values the shell stages fetched via
helper scripts: the importable package name (for bandit's ``src/<pkg>`` target)
and pip-audit's ``--ignore-vuln`` flags. The ``makescripts`` CLI shims for these
remain during migration; this is their in-package port (canonical after Phase 5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import rtoml

from bmk.domain.enums import PyrightPlatform


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


# GitHub-hosted runner labels name their OS family as a prefix (ubuntu-24.04, windows-latest,
# macos-14). A label naming no family (self-hosted, a custom runner group) adds no platform.
_RUNNER_FAMILIES: tuple[tuple[str, PyrightPlatform], ...] = (
    ("ubuntu", PyrightPlatform.LINUX),
    ("windows", PyrightPlatform.WINDOWS),
    ("macos", PyrightPlatform.DARWIN),
)


def _runner_platform(label: str) -> PyrightPlatform | None:
    folded = label.strip().casefold()
    return next((platform for prefix, platform in _RUNNER_FAMILIES if folded.startswith(prefix)), None)


def pyright_platforms(pyproject: Path) -> tuple[PyrightPlatform, ...]:
    """The pyright platforms ``[tool.ci].os`` declares, once each, in first-seen order.

    The CI workflow builds its OS matrix from this same key, so the local type check covers
    exactly the platforms CI will. Empty when the key is absent or holds no recognisable
    runner, which leaves pyright on the host platform.

    Example:
        >>> pyright_platforms(Path("does-not-exist/pyproject.toml"))
        ()
    """
    declared: object = _load(pyproject).get("tool", {}).get("ci", {}).get("os", [])
    if not isinstance(declared, list):
        return ()
    # A TOML array may hold anything; each entry is checked below, so object is its honest type.
    labels = cast("list[object]", declared)
    found = (_runner_platform(label) for label in labels if isinstance(label, str))
    return tuple(dict.fromkeys(platform for platform in found if platform is not None))


__all__ = ["derive_package_name", "pip_audit_ignore_flags", "pyright_platforms"]
