"""Pyproject-derived data used to build tool argv lists.

In-process, thread-safe readers for the values the tool stages need from the project's
own configuration: the importable package name (for bandit's ``src/<pkg>`` target),
pip-audit's ``--ignore-vuln`` flags, and the pyright platforms to type-check under.

Each reader parses ``pyproject.toml`` once into ``_ProjectReadings``, a boundary model
holding exactly the keys read here and nothing else. This module is the single owner of
those keys (``[tool.pip-audit]`` in particular; see the NOTE in ``helpers/_toml_config.py``).
A misshapen table or value degrades to "not configured"; a missing file reads as an empty
one; malformed TOML still raises, as it always has.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, cast

import rtoml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from bmk.adapters.stagerunner.helpers._toml_config import coerce_str_tuple, coerce_table
from bmk.domain.enums import PyrightPlatform

# ---------------------------------------------------------------------------
# Lenient coercions for the boundary models below
# ---------------------------------------------------------------------------


def _strings_only(v: Any) -> tuple[str, ...]:
    """The string entries of a TOML array, in order; any other entry, or a non-array, is dropped.

    Stricter than ``coerce_str_tuple``, which stringifies: a vulnerability id or a runner
    label that is not a string names nothing, so it must not become one.
    """
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(item for item in cast("tuple[Any, ...]", v) if isinstance(item, str))


def _str_or_empty(v: Any) -> str:
    """A string as-is; anything else reads as unset (``""``)."""
    return v if isinstance(v, str) else ""


def _string_entry_points(v: Any) -> dict[str, str]:
    """``[project.scripts]`` (name -> ``module:function``), keeping only string targets, in order."""
    if not isinstance(v, dict):
        return {}
    return {str(name): spec for name, spec in cast("dict[str, Any]", v).items() if isinstance(spec, str)}


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


def _runner_platforms(v: Any) -> tuple[PyrightPlatform, ...]:
    """The platforms a ``[tool.ci].os`` runner list declares, once each, in first-seen order."""
    found = (_runner_platform(label) for label in _strings_only(v))
    return tuple(dict.fromkeys(platform for platform in found if platform is not None))


def _named_platform(v: Any) -> PyrightPlatform | None:
    """The platform a ``pythonPlatform`` value names, matched case-insensitively.

    ``All`` - pyright's value for no single platform - and anything that is not a string
    name no pin.
    """
    if not isinstance(v, str):
        return None
    folded = v.casefold()
    return next((platform for platform in PyrightPlatform if platform.value.casefold() == folded), None)


# ---------------------------------------------------------------------------
# Boundary models: exactly the keys this module reads
# ---------------------------------------------------------------------------


class _PyrightConfig(BaseModel):
    """``pyrightconfig.json``, or ``[tool.pyright]`` when that file is absent."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    python_platform: Annotated[PyrightPlatform | None, BeforeValidator(_named_platform)] = Field(
        default=None, validation_alias="pythonPlatform"
    )


class _HatchWheel(BaseModel):
    """``[tool.hatch.build.targets.wheel]``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    packages: Annotated[tuple[str, ...], BeforeValidator(coerce_str_tuple)] = ()


class _HatchTargets(BaseModel):
    """``[tool.hatch.build.targets]``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    wheel: Annotated[_HatchWheel, BeforeValidator(coerce_table)] = Field(default_factory=_HatchWheel)


class _HatchBuild(BaseModel):
    """``[tool.hatch.build]``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    targets: Annotated[_HatchTargets, BeforeValidator(coerce_table)] = Field(default_factory=_HatchTargets)


class _Hatch(BaseModel):
    """``[tool.hatch]``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    build: Annotated[_HatchBuild, BeforeValidator(coerce_table)] = Field(default_factory=_HatchBuild)


class _PipAudit(BaseModel):
    """``[tool.pip-audit]``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    ignore_vulns: Annotated[tuple[str, ...], BeforeValidator(_strings_only)] = Field(
        default=(), validation_alias="ignore-vulns"
    )


class _Ci(BaseModel):
    """``[tool.ci]`` - the CI runner OS list, read as the pyright platforms it covers."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    os: Annotated[tuple[PyrightPlatform, ...], BeforeValidator(_runner_platforms)] = ()


class _Tool(BaseModel):
    """``[tool]`` - the four tables this module reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    hatch: Annotated[_Hatch, BeforeValidator(coerce_table)] = Field(default_factory=_Hatch)
    pip_audit: Annotated[_PipAudit, BeforeValidator(coerce_table)] = Field(
        default_factory=_PipAudit, validation_alias="pip-audit"
    )
    ci: Annotated[_Ci, BeforeValidator(coerce_table)] = Field(default_factory=_Ci)
    pyright: Annotated[_PyrightConfig, BeforeValidator(coerce_table)] = Field(default_factory=_PyrightConfig)


class _Project(BaseModel):
    """``[project]`` - the two keys the package name can be derived from."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: Annotated[str, BeforeValidator(_str_or_empty)] = ""
    # Dynamically keyed (script name -> entry point), so a mapping rather than a model.
    scripts: Annotated[dict[str, str], BeforeValidator(_string_entry_points)] = Field(
        default_factory=lambda: cast("dict[str, str]", {})
    )


class _ProjectReadings(BaseModel):
    """The pyproject.toml keys this module reads, validated once."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    project: Annotated[_Project, BeforeValidator(coerce_table)] = Field(default_factory=_Project)
    tool: Annotated[_Tool, BeforeValidator(coerce_table)] = Field(default_factory=_Tool)


def _load(pyproject: Path) -> _ProjectReadings:
    if not pyproject.is_file():
        return _ProjectReadings()
    return _ProjectReadings.model_validate(rtoml.load(pyproject))


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def derive_package_name(pyproject: Path) -> str | None:
    """Derive the importable package name (hatch wheel -> script entry -> project name)."""
    readings = _load(pyproject)

    packages = readings.tool.hatch.build.targets.wheel.packages
    if packages:
        return Path(packages[0]).name

    for spec in readings.project.scripts.values():
        if ":" in spec:
            return spec.split(":", 1)[0].split(".", 1)[0]

    name = readings.project.name
    if name:
        return name.replace("-", "_")
    return None


def pip_audit_ignore_flags(pyproject: Path) -> list[str]:
    """Return ``--ignore-vuln=<ID>`` flags from ``[tool.pip-audit].ignore-vulns``."""
    return [f"--ignore-vuln={vuln}" for vuln in _load(pyproject).tool.pip_audit.ignore_vulns]


def pyright_platforms(pyproject: Path) -> tuple[PyrightPlatform, ...]:
    """The pyright platforms ``[tool.ci].os`` declares, once each, in first-seen order.

    The CI workflow builds its OS matrix from this same key, so the local type check covers
    exactly the platforms CI will. Empty when the key is absent or holds no recognisable
    runner, which leaves pyright on the host platform.

    Example:
        >>> pyright_platforms(Path("does-not-exist/pyproject.toml"))
        ()
    """
    return _load(pyproject).tool.ci.os


def _pinned_platform(project_dir: Path, pyproject_pyright: _PyrightConfig) -> PyrightPlatform | None:
    """The ``pythonPlatform`` the project's own pyright config pins, or None.

    pyright reads ``pyrightconfig.json`` when it exists and ``[tool.pyright]`` (already
    parsed, passed in) otherwise, so the pin is looked up in that order. A value naming no
    single platform (``All``), and a ``pyrightconfig.json`` that is not a plain JSON object
    (pyright also takes comments), read as no pin.
    """
    config_file = project_dir / "pyrightconfig.json"
    if not config_file.is_file():
        return pyproject_pyright.python_platform
    try:
        return _PyrightConfig.model_validate(json.loads(config_file.read_text(encoding="utf-8"))).python_platform
    except (OSError, ValueError, ValidationError):
        return None


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
    tool = _load(project_dir / "pyproject.toml").tool
    platforms = tool.ci.os
    if not platforms:
        return ((),)
    pinned = _pinned_platform(project_dir, tool.pyright)
    main: list[tuple[str, ...]] = (
        [()] if pinned is not None else [("--pythonplatform", platform.value) for platform in platforms]
    )
    arms = [f"pyrightconfig.{platform.value.lower()}.json" for platform in platforms]
    return (*main, *(("--project", arm) for arm in arms if (project_dir / arm).is_file()))


__all__ = ["derive_package_name", "pip_audit_ignore_flags", "pyright_platforms", "pyright_runs"]
