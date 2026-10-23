"""Pydantic-based TOML configuration parsing.

Provides typed models for pyproject.toml sections, eliminating dict-based access
patterns and their associated type issues. This parses project-authored config that is
never fully trusted (a malformed or unusual value must not fail a build), so every
model tolerates a wrong-shaped value for one of its own fields by falling back to that
field's declared default - see the module-level `coerce_*` / `_coerce_*` helpers (the
two public ones are shared with the other pyproject readers, ``project.py`` and
``_coverage.py``, so a misshapen table degrades the same way everywhere) - and
`PyprojectConfig.from_path` additionally never raises on a missing or unparsable file.
"""

from __future__ import annotations

import re
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, cast

import rtoml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "BashateConfig",
    "BuildSystemSection",
    "CleanConfig",
    "GitConfig",
    "PSScriptAnalyzerConfig",
    "ProjectSection",
    "PyprojectConfig",
    "ScriptsConfig",
    "ScriptsTestAllConfig",
    "ToolConfig",
    "coerce_str_tuple",
    "coerce_table",
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


def coerce_table(v: Any) -> Any:
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


def coerce_str_tuple(v: Any) -> tuple[str, ...]:
    """A TOML array is a list; a tuple is also accepted as-is (direct keyword
    construction, e.g. `ProjectSection(dependencies=(...))` in tests, already hands in
    the field's own tuple type). Keep only non-None items and stringify anything that
    is not already a str.
    """
    if not isinstance(v, (list, tuple)):
        return ()
    return tuple(str(item) for item in cast("tuple[Any, ...]", v) if item is not None)


# A real PSScriptAnalyzer rule id is always ``PS`` followed by alphanumerics (e.g.
# ``PSAvoidUsingWriteHost``). This value is interpolated into a ``pwsh -Command`` string
# in ``_psscriptanalyzer.py``, so anything with a space, quote, semicolon, or other
# metacharacter is not a rule id and could break out of the command - drop it here, at the
# project-authored-config boundary, so a hostile ``pyproject.toml`` cannot inject PowerShell.
_PSSCRIPT_RULE_RE = re.compile(r"^PS[A-Za-z0-9]+$")


def _coerce_psscript_rules(v: Any) -> tuple[str, ...]:
    """Keep only well-formed PSScriptAnalyzer rule ids; silently drop anything else."""
    return tuple(rule for rule in coerce_str_tuple(v) if _PSSCRIPT_RULE_RE.match(rule))


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

    patterns: Annotated[tuple[str, ...], BeforeValidator(coerce_str_tuple)] = ()


# NOTE on what is deliberately NOT here: [tool.coverage.report], [tool.bandit],
# [tool.pip-audit] and [tool.scripts.test] (its sibling [tool.scripts.test-all] IS here, in
# ScriptsConfig: the rule is one owner per key, not per table). Each once had a dataclass in this file, and
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


def _coerce_stripped_str(v: Any) -> str:
    """A string, stripped; anything that is not a string reads as unset (``""``).

    Unlike `_coerce_str`, a number is NOT stringified: a value naming something by
    identifier (a git remote) is a string or it is not set at all.
    """
    return v.strip() if isinstance(v, str) else ""


def _coerce_optional_int(v: Any) -> int | None:
    """A TOML integer, or None for anything else - including a bool (Python's bool is an
    int subclass, but ``workers = true`` is no count) and a float or numeric string, which
    a deliberate setting would not use. None lets the caller fall back to its default.
    """
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return None


class GitConfig(BaseModel):
    """[tool.git] - the remote ``release`` pushes to."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    # Empty means "not configured": the reader falls back to "origin".
    default_remote: Annotated[str, BeforeValidator(_coerce_stripped_str)] = Field(
        default="", validation_alias="default-remote"
    )


class ScriptsTestAllConfig(BaseModel):
    """[tool.scripts.test-all] - how the version matrix (``test-all``) runs."""

    model_config = ConfigDict(frozen=True)

    # None means "not set, or not an integer": the matrix then picks its own default.
    workers: Annotated[int | None, BeforeValidator(_coerce_optional_int)] = None


class ScriptsConfig(BaseModel):
    """[tool.scripts] - only the tables this module owns; [tool.scripts.test] is read by
    helpers/_coverage.py (see the NOTE above).
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    test_all: Annotated[ScriptsTestAllConfig, BeforeValidator(coerce_table)] = Field(
        default_factory=ScriptsTestAllConfig, validation_alias="test-all"
    )


class PSScriptAnalyzerConfig(BaseModel):
    """[tool.psscriptanalyzer] - rule ids excluded from PSScriptAnalyzer runs."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    exclude_rules: Annotated[tuple[str, ...], BeforeValidator(_coerce_psscript_rules)] = Field(
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
    ignores: Annotated[tuple[str, ...], BeforeValidator(coerce_str_tuple)] = ()


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
            extras=coerce_str_tuple(typed_spec.get("extras")),
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
    """[tool.uv] - uv's dev dependency array and its supply-chain cooldown.

    ``exclude_newer`` and ``exclude_newer_package`` are kept as raw TOML values and never parsed
    here: bmk reads the cutoff uv RESOLVED from ``uv.lock`` (``_supply_chain.ReleasePolicy``), and
    uses these only to notice a value uv refused, so uv's own grammar is the only one that applies.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    dev_dependencies: Annotated[tuple[str, ...], BeforeValidator(coerce_str_tuple)] = Field(
        default=(), validation_alias="dev-dependencies"
    )
    exclude_newer: Any = Field(default=None, validation_alias="exclude-newer")
    exclude_newer_package: Annotated[dict[str, Any], BeforeValidator(coerce_table)] = Field(
        default_factory=lambda: {}, validation_alias="exclude-newer-package"
    )


class ToolConfig(BaseModel):
    """Configuration for the [tool] section of pyproject.toml."""

    model_config = ConfigDict(frozen=True)

    clean: Annotated[CleanConfig, BeforeValidator(coerce_table)] = Field(default_factory=CleanConfig)
    psscriptanalyzer: Annotated[PSScriptAnalyzerConfig, BeforeValidator(coerce_table)] = Field(
        default_factory=PSScriptAnalyzerConfig
    )
    bashate: Annotated[BashateConfig, BeforeValidator(coerce_table)] = Field(default_factory=BashateConfig)
    poetry: Annotated[PoetryConfig, BeforeValidator(coerce_table)] = Field(default_factory=PoetryConfig)
    pdm: Annotated[PdmConfig, BeforeValidator(coerce_table)] = Field(default_factory=PdmConfig)
    uv: Annotated[UvConfig, BeforeValidator(coerce_table)] = Field(default_factory=UvConfig)
    git: Annotated[GitConfig, BeforeValidator(coerce_table)] = Field(default_factory=GitConfig)
    scripts: Annotated[ScriptsConfig, BeforeValidator(coerce_table)] = Field(default_factory=ScriptsConfig)


# ---------------------------------------------------------------------------
# Top-Level Section Models
# ---------------------------------------------------------------------------


_PY_CLASSIFIER = "Programming Language :: Python :: "


class ProjectSection(BaseModel):
    """Configuration for the [project] section of pyproject.toml."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: Annotated[str, BeforeValidator(_coerce_str)] = ""
    version: Annotated[str, BeforeValidator(_coerce_str)] = ""
    description: Annotated[str, BeforeValidator(_coerce_str)] = ""
    dependencies: Annotated[tuple[str, ...], BeforeValidator(coerce_str_tuple)] = ()
    optional_dependencies: Annotated[dict[str, tuple[str, ...]], BeforeValidator(_coerce_str_tuple_dict)] = Field(
        default_factory=dict, validation_alias="optional-dependencies"
    )
    # The trove classifiers, read for the `Programming Language :: Python :: X.Y` entries:
    # they are what declares the Python versions a project supports, and the CI workflow
    # already builds its test matrix from them. `requires-python` cannot serve that purpose
    # - it is a floor (`>=3.10`) with no upper bound, so it never names the newest supported
    # version. See `venv.desired_python_minor`.
    classifiers: Annotated[tuple[str, ...], BeforeValidator(coerce_str_tuple)] = ()
    # The floor, read where a dependency must still install on the OLDEST Python the project
    # supports: the dependency updater must not raise a floor past it.
    requires_python: Annotated[str, BeforeValidator(_coerce_str)] = Field(
        default="", validation_alias="requires-python"
    )

    def python_minors(self) -> tuple[str, ...]:
        """Every ``X.Y`` the Python classifiers declare, ascending numerically.

        Only dotted entries count (a bare ``:: Python :: 3`` is skipped), and the order is
        numeric, since as strings ``"3.9" > "3.14"``.

        Example:
            >>> ProjectSection(classifiers=(
            ...     "Programming Language :: Python :: 3.14",
            ...     "Programming Language :: Python :: 3",
            ...     "Programming Language :: Python :: 3.9",
            ... )).python_minors()
            ('3.9', '3.14')
        """
        found: list[tuple[tuple[int, ...], str]] = []
        for classifier in self.classifiers:
            if not classifier.startswith(_PY_CLASSIFIER):
                continue
            version = classifier[len(_PY_CLASSIFIER) :].strip()
            if "." not in version:
                continue
            try:
                parts = tuple(int(p) for p in version.split("."))
            except ValueError:
                continue
            found.append((parts, version))
        return tuple(version for _, version in sorted(found))


class BuildSystemSection(BaseModel):
    """Configuration for the [build-system] section of pyproject.toml."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    requires: Annotated[tuple[str, ...], BeforeValidator(coerce_str_tuple)] = ()
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

    project: Annotated[ProjectSection, BeforeValidator(coerce_table)] = Field(default_factory=ProjectSection)
    build_system: Annotated[BuildSystemSection, BeforeValidator(coerce_table)] = Field(
        default_factory=BuildSystemSection, validation_alias="build-system"
    )
    dependency_groups: Annotated[DependencyGroupsSection, BeforeValidator(coerce_table)] = Field(
        default_factory=DependencyGroupsSection, validation_alias="dependency-groups"
    )
    tool: Annotated[ToolConfig, BeforeValidator(coerce_table)] = Field(default_factory=ToolConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PyprojectConfig:
        """Build from an already-parsed TOML dict.

        Every key bmk reads here has a typed field, and a key no model declares is
        dropped: a reader that needs a new key adds a field rather than crawling the
        raw document.

        Args:
            data: The parsed pyproject.toml document.

        Returns:
            The typed configuration.

        Example:
            >>> PyprojectConfig.from_dict({"tool": {"git": {"default-remote": " up "}}}).tool.git.default_remote
            'up'
        """
        return cls.model_validate(data)

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
