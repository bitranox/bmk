"""Pydantic-based TOML configuration parsing.

Provides typed models for pyproject.toml sections, eliminating dict-based access
patterns and their associated type issues. This parses project-authored config that is
never fully trusted (a malformed or unusual value must not fail a build), so every
model tolerates a wrong-shaped value for one of its own fields by falling back to that
field's declared default - see the module-level `_coerce_*` helpers - and
`PyprojectConfig.from_path` additionally never raises on a missing or unparsable file.
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, cast

import rtoml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "CleanConfig",
    "PSScriptAnalyzerConfig",
    "BashateConfig",
    "ToolConfig",
    "ProjectSection",
    "BuildSystemSection",
    "PyprojectConfig",
    "load_pyproject_config",
]


# ---------------------------------------------------------------------------
# Shared Lenient-Coercion Helpers
#
# Pydantic's own coercion is stricter than a TOML reader should be here: a wrong-typed
# leaf value (an int where a string was expected, a table where an array was expected)
# must degrade to that field's default, not raise and blow away a whole section. Each
# helper below is a pure function used as a per-field `BeforeValidator`; none of them
# ever raises, and none of them hard-codes a "real" default - an empty str/tuple/dict is
# the natural empty value, not a business default, so encoding it here does not
# reintroduce the two-places-per-default bug this refactor removes (the one field with a
# non-trivial default, BashateConfig.max_line_length, keeps its default in exactly one
# place; see `_DEFAULT_BASHATE_MAX_LINE_LENGTH` below).
# ---------------------------------------------------------------------------


def _coerce_table(v: Any) -> Any:
    """A TOML sub-table is a dict; anything else (wrong type, or simply absent) becomes
    an empty table so the nested model below falls back to its all-default form
    instead of raising. An already-built BaseModel instance (direct keyword
    construction, e.g. `PyprojectConfig(project=ProjectSection(...))` in tests) passes
    through untouched - it is not TOML data to reshape, and Pydantic's own nested-model
    validation handles it from here.
    """
    if isinstance(v, BaseModel):
        return v
    if isinstance(v, dict):
        # cast, not a bare return: `isinstance(v, dict)` narrows Any to dict[Unknown, Unknown],
        # which strict mode rejects as a partially-unknown return type.
        return cast("dict[str, Any]", v)
    return {}


def _coerce_str(v: Any) -> str:
    """TOML strings already are str; stringify a wrong-typed value (e.g. a numeric
    literal in `version = 1.0`) instead of rejecting it, matching the pre-Pydantic
    getter's leniency.
    """
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    return str(v)


def _coerce_str_tuple(v: Any) -> tuple[str, ...]:
    """A TOML array is a list; a tuple is also accepted as-is (direct keyword
    construction, e.g. `ProjectSection(dependencies=(...))` in tests, already hands in
    the field's own tuple type). Keep only non-None items and stringify anything that
    is not already a str.
    """
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(str(item) for item in cast("tuple[Any, ...]", v) if item is not None)


def _coerce_str_tuple_dict(v: Any) -> dict[str, tuple[str, ...]]:
    """A TOML table of arrays ([project.optional-dependencies], [dependency-groups],
    [tool.pdm.dev-dependencies]): an entry whose value is not itself an array (list or,
    from direct construction, tuple) is dropped rather than raising, so one misshapen
    group does not take out its siblings.
    """
    if not isinstance(v, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for name_raw, deps in cast("dict[str, Any]", v).items():
        if isinstance(deps, (list, tuple)):
            result[str(name_raw)] = tuple(str(item) for item in cast("tuple[Any, ...]", deps) if item is not None)
    return result


# ---------------------------------------------------------------------------
# Tool Configuration Models
# ---------------------------------------------------------------------------


class CleanConfig(BaseModel):
    """[tool.clean] - glob patterns removed by the `clean` stage."""

    model_config = ConfigDict(frozen=True)

    patterns: Annotated[tuple[str, ...], BeforeValidator(_coerce_str_tuple)] = ()


# NOTE on what is deliberately NOT here: [tool.coverage.report], [tool.bandit],
# [tool.pip-audit] and [tool.scripts.test]. Each once had a dataclass in this file, and
# each was dead - parsed on every load, read by nobody, covered by no test. Worse, they
# had drifted: the [tool.scripts.test] copy claimed pytest-verbosity defaults to "-vv"
# while the reader that actually runs pytest uses "-v", so this file answered questions
# about bmk's behaviour incorrectly.
#
# Where those keys are really read: the coverage and scripts-test keys by
# helpers/_coverage.py, in CoverageConfig.from_pyproject; pip-audit's ignored vulnerability
# ids by project.py, in pip_audit_ignore_flags; and bandit's skips by bandit itself, since
# bmk hands it "-c pyproject.toml" from tools.py and never parses that table at all.
#
# Before adding a section here, check it will actually be consumed. A second parser for a
# key another module already owns is how the "-vv" lie got in.


class PSScriptAnalyzerConfig(BaseModel):
    """[tool.psscriptanalyzer] - rule ids excluded from PSScriptAnalyzer runs."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    exclude_rules: Annotated[tuple[str, ...], BeforeValidator(_coerce_str_tuple)] = Field(
        default=(), validation_alias="exclude-rules"
    )


_DEFAULT_BASHATE_MAX_LINE_LENGTH = 120


def _coerce_bashate_max_line_length(v: Any) -> int:
    """Lenient int coercion (a float or a numeric string in TOML still counts);
    anything else falls back to `_DEFAULT_BASHATE_MAX_LINE_LENGTH`, the SAME constant
    used as the field default below, so the two can never drift apart the way -vv/-v
    once did.
    """
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, (float, str)):
        try:
            return int(v)
        except (ValueError, TypeError):
            pass
    return _DEFAULT_BASHATE_MAX_LINE_LENGTH


class BashateConfig(BaseModel):
    """[tool.bashate] - bashate's max line length and ignored check ids."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    max_line_length: Annotated[int, BeforeValidator(_coerce_bashate_max_line_length)] = Field(
        default=_DEFAULT_BASHATE_MAX_LINE_LENGTH, validation_alias="max-line-length"
    )
    ignores: Annotated[tuple[str, ...], BeforeValidator(_coerce_str_tuple)] = ()


class PoetryVersionOperator(str, Enum):
    """Poetry version-constraint prefix characters this parser translates to a PEP 508
    '>=' floor bound. Caret and tilde collapse to the SAME floor here (Poetry's real
    semantics differ: caret allows up to the next major, tilde up to the next minor) -
    bmk's dependency listing only needs a floor bound, so this mirrors the pre-existing,
    deliberately loose translation rather than reimplementing full Poetry semantics.
    """

    CARET = "^"
    TILDE = "~"


class PoetryDepSpec(BaseModel):
    """A single Poetry dependency: name, Poetry-style version constraint, extras."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str = ""
    extras: tuple[str, ...] = ()

    def to_requirement_string(self) -> str:
        """Convert to a PEP 508 requirement string."""
        if not self.version or self.version == "*":
            return self.name
        for operator in PoetryVersionOperator:
            if self.version.startswith(operator.value):
                return f"{self.name}>={self.version[len(operator.value) :]}"
        return f"{self.name}{self.version}"


def _parse_poetry_dep_entry(name: str, spec: Any) -> PoetryDepSpec:
    """A Poetry dependency value is either a bare version string or a table with its
    own version/extras keys; any other shape is treated as "no version, no extras".
    """
    if isinstance(spec, str):
        return PoetryDepSpec(name=name, version=spec)
    if isinstance(spec, dict):
        typed_spec = cast("dict[str, Any]", spec)
        return PoetryDepSpec(
            name=name,
            version=_coerce_str(typed_spec.get("version")),
            extras=_coerce_str_tuple(typed_spec.get("extras")),
        )
    return PoetryDepSpec(name=name)


def _parse_poetry_deps(v: Any) -> tuple[PoetryDepSpec, ...]:
    """Poetry's dependency table maps name -> version-string-or-table. 'python' is
    Poetry's own interpreter-constraint pseudo-dependency (not an installable package)
    and is always excluded. An already-built tuple of PoetryDepSpec (direct keyword
    construction) passes through unchanged - it is not a raw TOML table to walk.
    """
    if isinstance(v, tuple) and all(isinstance(item, PoetryDepSpec) for item in cast("tuple[Any, ...]", v)):
        return cast("tuple[PoetryDepSpec, ...]", v)
    if not isinstance(v, dict):
        return ()
    result: list[PoetryDepSpec] = []
    for name_raw, spec in cast("dict[str, Any]", v).items():
        name = str(name_raw)
        if name.lower() == "python":
            continue
        result.append(_parse_poetry_dep_entry(name, spec))
    return tuple(result)


def _parse_poetry_groups(v: Any) -> dict[str, tuple[PoetryDepSpec, ...]]:
    """[tool.poetry.group.<name>.dependencies] nests one level deeper than every other
    Poetry table: each group name maps to its OWN {dependencies: {...}} table. Genuinely
    awkward shape, so this stays a bespoke walk rather than the shared
    `_coerce_str_tuple_dict` helper. An already-built dict of PoetryDepSpec tuples
    (direct keyword construction) passes through unchanged.
    """
    if not isinstance(v, dict):
        return {}
    typed_v = cast("dict[str, Any]", v)
    if all(
        isinstance(deps, tuple) and all(isinstance(item, PoetryDepSpec) for item in cast("tuple[Any, ...]", deps))
        for deps in typed_v.values()
    ):
        return cast("dict[str, tuple[PoetryDepSpec, ...]]", v)
    result: dict[str, tuple[PoetryDepSpec, ...]] = {}
    for group_name_raw, group_content in cast("dict[str, Any]", v).items():
        if isinstance(group_content, dict):
            deps = cast("dict[str, Any]", group_content).get("dependencies")
            result[str(group_name_raw)] = _parse_poetry_deps(deps)
    return result


class PoetryConfig(BaseModel):
    """[tool.poetry] - Poetry-style dependency tables (main, dev, per-group)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    dependencies: Annotated[tuple[PoetryDepSpec, ...], BeforeValidator(_parse_poetry_deps)] = ()
    dev_dependencies: Annotated[tuple[PoetryDepSpec, ...], BeforeValidator(_parse_poetry_deps)] = Field(
        default=(), validation_alias="dev-dependencies"
    )
    group_dependencies: Annotated[dict[str, tuple[PoetryDepSpec, ...]], BeforeValidator(_parse_poetry_groups)] = Field(
        default_factory=dict, validation_alias="group"
    )


class PdmConfig(BaseModel):
    """[tool.pdm] - PDM's per-group dev dependency arrays."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    dev_dependencies: Annotated[dict[str, tuple[str, ...]], BeforeValidator(_coerce_str_tuple_dict)] = Field(
        default_factory=dict, validation_alias="dev-dependencies"
    )


class UvConfig(BaseModel):
    """[tool.uv] - uv's dev dependency array."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    dev_dependencies: Annotated[tuple[str, ...], BeforeValidator(_coerce_str_tuple)] = Field(
        default=(), validation_alias="dev-dependencies"
    )


class ToolConfig(BaseModel):
    """Configuration for the [tool] section of pyproject.toml."""

    model_config = ConfigDict(frozen=True)

    clean: Annotated[CleanConfig, BeforeValidator(_coerce_table)] = Field(default_factory=CleanConfig)
    psscriptanalyzer: Annotated[PSScriptAnalyzerConfig, BeforeValidator(_coerce_table)] = Field(
        default_factory=PSScriptAnalyzerConfig
    )
    bashate: Annotated[BashateConfig, BeforeValidator(_coerce_table)] = Field(default_factory=BashateConfig)
    poetry: Annotated[PoetryConfig, BeforeValidator(_coerce_table)] = Field(default_factory=PoetryConfig)
    pdm: Annotated[PdmConfig, BeforeValidator(_coerce_table)] = Field(default_factory=PdmConfig)
    uv: Annotated[UvConfig, BeforeValidator(_coerce_table)] = Field(default_factory=UvConfig)


# ---------------------------------------------------------------------------
# Top-Level Section Models
# ---------------------------------------------------------------------------


class ProjectSection(BaseModel):
    """Configuration for the [project] section of pyproject.toml."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: Annotated[str, BeforeValidator(_coerce_str)] = ""
    version: Annotated[str, BeforeValidator(_coerce_str)] = ""
    description: Annotated[str, BeforeValidator(_coerce_str)] = ""
    dependencies: Annotated[tuple[str, ...], BeforeValidator(_coerce_str_tuple)] = ()
    optional_dependencies: Annotated[dict[str, tuple[str, ...]], BeforeValidator(_coerce_str_tuple_dict)] = Field(
        default_factory=dict, validation_alias="optional-dependencies"
    )


class BuildSystemSection(BaseModel):
    """Configuration for the [build-system] section of pyproject.toml."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    requires: Annotated[tuple[str, ...], BeforeValidator(_coerce_str_tuple)] = ()
    build_backend: Annotated[str, BeforeValidator(_coerce_str)] = Field(default="", validation_alias="build-backend")


class DependencyGroupsSection(BaseModel):
    """Configuration for the [dependency-groups] section (PEP 735).

    Unlike every [tool.*] table, TOML represents this section as the group name -> deps
    array mapping directly, with no wrapping key - so the model_validator below detects
    that bare shape and wraps it onto the `groups` field.
    """

    model_config = ConfigDict(frozen=True)

    groups: Annotated[dict[str, tuple[str, ...]], BeforeValidator(_coerce_str_tuple_dict)] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_group_mapping(cls, data: Any) -> Any:
        # [dependency-groups] IS the mapping of groups, with no wrapper key, so the raw
        # table is lifted under "groups" before field validation. The dict branch returns
        # on its own so the fall-through keeps `data` as plain Any: isinstance() would
        # otherwise narrow it to dict[Unknown, Unknown], which strict mode rejects as a
        # partially-unknown return type.
        if isinstance(data, dict):
            table = cast("dict[str, Any]", data)
            return table if "groups" in table else {"groups": table}
        return data


# ---------------------------------------------------------------------------
# Main Configuration Model
# ---------------------------------------------------------------------------


class PyprojectConfig(BaseModel):
    """Complete pyproject.toml configuration."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    project: Annotated[ProjectSection, BeforeValidator(_coerce_table)] = Field(default_factory=ProjectSection)
    build_system: Annotated[BuildSystemSection, BeforeValidator(_coerce_table)] = Field(
        default_factory=BuildSystemSection, validation_alias="build-system"
    )
    dependency_groups: Annotated[DependencyGroupsSection, BeforeValidator(_coerce_table)] = Field(
        default_factory=DependencyGroupsSection, validation_alias="dependency-groups"
    )
    tool: Annotated[ToolConfig, BeforeValidator(_coerce_table)] = Field(default_factory=ToolConfig)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PyprojectConfig:
        """Build from an already-parsed TOML dict, capturing it verbatim in raw_data.

        raw_data is the escape hatch for keys with no dedicated model field - e.g.
        [tool.git].default-remote, read straight out of it by _release.py - so it must
        survive as the untouched top-level dict, not just this model's known fields.
        Not a plain field default: direct keyword construction (`PyprojectConfig(project=...)`,
        used by tests) intentionally leaves raw_data at its empty-dict default instead.
        """
        return cls.model_validate({**data, "raw_data": data})

    @classmethod
    def from_path(cls, path: Path) -> PyprojectConfig:
        """Load configuration from a pyproject.toml file.

        Never raises: a missing file, unreadable file, malformed TOML, or a pyproject
        so malformed that a section can't even become an empty table all fall back to
        an all-default PyprojectConfig, so a project's bad pyproject.toml never fails
        the build that is trying to read it.
        """
        try:
            data: dict[str, Any] = rtoml.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (rtoml.TomlParsingError, OSError, ValueError, ValidationError) as exc:
            if path.exists():
                print(f"Warning: Failed to parse {path}: {exc}", file=sys.stderr)
            return cls()


def load_pyproject_config(path: Path = Path("pyproject.toml")) -> PyprojectConfig:
    """Load and parse pyproject.toml into a typed configuration object.

    Args:
        path: Path to the pyproject.toml file

    Returns:
        PyprojectConfig with all sections parsed, using defaults for missing values
    """
    return PyprojectConfig.from_path(path)
