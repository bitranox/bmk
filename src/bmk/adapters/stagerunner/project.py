"""Pyproject-derived data used to build tool argv lists.

In-process, thread-safe readers for the two values the shell stages fetched via
helper scripts: the importable package name (for bandit's ``src/<pkg>`` target)
and pip-audit's ``--ignore-vuln`` flags. The ``makescripts`` CLI shims for these
remain during migration; this is their in-package port (canonical after Phase 5).
"""

from __future__ import annotations

import json
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


def _pinned_platform(project_dir: Path) -> PyrightPlatform | None:
    """The ``pythonPlatform`` the project's own pyright config pins, or None.

    pyright reads ``pyrightconfig.json`` when it exists and ``[tool.pyright]`` otherwise, so the
    pin is looked up in that order. A value naming no single platform (``All``), and a
    ``pyrightconfig.json`` that is not plain JSON (pyright also takes comments), read as no pin.
    """
    config_file = project_dir / "pyrightconfig.json"
    if config_file.is_file():
        try:
            config: object = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    else:
        config = _load(project_dir / "pyproject.toml").get("tool", {}).get("pyright", {})
    value = cast("dict[str, object]", config).get("pythonPlatform") if isinstance(config, dict) else None
    return next((p for p in PyrightPlatform if isinstance(value, str) and p.value.casefold() == value.casefold()), None)


def pyright_runs(project_dir: Path) -> tuple[tuple[str, ...], ...]:
    """The extra pyright arguments of each run that covers the platforms ``[tool.ci].os`` declares.

    The main config runs the way CI runs it - bare ``pyright`` on each runner: once under the
    platform the project pins (``pythonPlatform``), or once per declared platform
    (``--pythonplatform``) when it pins none. A project that pinned its platform did it on purpose
    (lsdsk keeps Linux-only modules in the main config), and forcing another platform over that
    config reported 159 errors CI never shows. Each declared platform's own arm,
    ``pyrightconfig.<platform>.json`` in the project root, runs too, through ``--project``.

    With no declared platform it is one bare run, for the host.

    Example:
        >>> pyright_runs(Path("does-not-exist"))
        ((),)
    """
    platforms = pyright_platforms(project_dir / "pyproject.toml")
    if not platforms:
        return ((),)
    pinned = _pinned_platform(project_dir)
    main: list[tuple[str, ...]] = (
        [()] if pinned is not None else [("--pythonplatform", platform.value) for platform in platforms]
    )
    arms = [f"pyrightconfig.{platform.value.lower()}.json" for platform in platforms]
    return (*main, *(("--project", arm) for arm in arms if (project_dir / arm).is_file()))


__all__ = ["derive_package_name", "pip_audit_ignore_flags", "pyright_platforms", "pyright_runs"]
