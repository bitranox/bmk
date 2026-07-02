"""Declarative TOML overlay: projects add / remove / replace pipeline stages.

The overlay is the supported downstream customization mechanism. Each stage
action it defines is an argv list (a ``ToolAction``), never arbitrary code, so it
is safe and cross-OS. Sources, in ascending precedence:

1. ``pyproject.toml``               -> ``[tool.bmk.pipelines.<prefix>]``
2. ``bmk_makescripts/stages.toml``  -> ``[pipelines.<prefix>]`` (wins if present)

This module parses untrusted project config, so it validates types and shapes at
this boundary and rejects malformed overlays with a clear ``ValueError``. The
untyped ``rtoml`` result is confined here behind explicit casts (typed facade).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import rtoml

from .actions import ToolAction
from .model import Stage, StageContext

_MAX_ARGV = 256


@dataclass(frozen=True, slots=True)
class StageSpec:
    """A declaratively-specified stage: a name, an order, and an argv to run."""

    name: str
    order: int
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Overlay:
    """Add, remove, and replace operations for one pipeline."""

    add: tuple[StageSpec, ...] = ()
    remove: tuple[str, ...] = ()
    replace: tuple[StageSpec, ...] = ()


def _argv_action(argv: tuple[str, ...]) -> ToolAction:
    def build(_ctx: StageContext) -> list[str]:
        return list(argv)

    return ToolAction(build)


def apply_overlay(stages: Sequence[Stage], overlay: Overlay) -> tuple[Stage, ...]:
    """Apply remove, then replace, then add to ``stages`` (order preserved)."""
    removed = {*overlay.remove}
    replacements = {spec.name: spec for spec in overlay.replace}

    result: list[Stage] = []
    for stage in stages:
        if stage.name in removed:
            continue
        spec = replacements.get(stage.name)
        if spec is not None:
            # Keep the original order and interactivity; swap only the action.
            result.append(Stage(stage.name, stage.order, _argv_action(spec.argv), interactive=stage.interactive))
        else:
            result.append(stage)

    result.extend(Stage(spec.name, spec.order, _argv_action(spec.argv)) for spec in overlay.add)
    return tuple(result)


def _require_argv(raw: Any, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        msg = f"{where}: 'argv' must be a list of strings"
        raise ValueError(msg)
    items = cast("list[Any]", raw)
    strings = [item for item in items if isinstance(item, str)]
    if len(strings) != len(items):
        msg = f"{where}: 'argv' must be a list of strings"
        raise ValueError(msg)
    if not strings or len(strings) > _MAX_ARGV:
        msg = f"{where}: 'argv' must have 1..{_MAX_ARGV} items"
        raise ValueError(msg)
    return tuple(strings)


def _parse_specs(raw_list: Any, prefix: str) -> tuple[StageSpec, ...]:
    if not isinstance(raw_list, list):
        msg = f"[{prefix}]: stage list must be an array of tables"
        raise ValueError(msg)
    specs: list[StageSpec] = []
    for raw in cast("list[Any]", raw_list):
        if not isinstance(raw, dict):
            msg = f"[{prefix}]: each stage must be a table"
            raise ValueError(msg)
        entry = cast("dict[str, Any]", raw)
        name = entry.get("name")
        order = entry.get("order")
        if not isinstance(name, str) or not isinstance(order, int) or isinstance(order, bool):
            msg = f"[{prefix}]: each stage needs a string 'name' and an integer 'order'"
            raise ValueError(msg)
        specs.append(StageSpec(name, order, _require_argv(entry.get("argv"), f"[{prefix}] stage '{name}'")))
    return tuple(specs)


def _parse_remove(raw: Any, prefix: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        msg = f"[{prefix}]: 'remove' must be a list of stage names"
        raise ValueError(msg)
    items = cast("list[Any]", raw)
    names = [item for item in items if isinstance(item, str)]
    if len(names) != len(items):
        msg = f"[{prefix}]: 'remove' must be a list of stage names"
        raise ValueError(msg)
    return tuple(names)


def _parse_overlay(section: dict[str, Any], prefix: str) -> Overlay:
    return Overlay(
        add=_parse_specs(section.get("add", []), prefix),
        remove=_parse_remove(section.get("remove", []), prefix),
        replace=_parse_specs(section.get("replace", []), prefix),
    )


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return rtoml.load(path)


def _pipelines_from(path: Path, root_keys: tuple[str, ...]) -> dict[str, Any]:
    node: dict[str, Any] = _load_toml(path)
    for key in root_keys:
        child = node.get(key, {})
        if not isinstance(child, dict):
            return {}
        node = cast("dict[str, Any]", child)
    return node


def load_overlay(cwd: Path, prefix: str) -> Overlay | None:
    """Load the overlay for ``prefix``; ``stages.toml`` wins over ``pyproject.toml``."""
    pyproject = _pipelines_from(cwd / "pyproject.toml", ("tool", "bmk", "pipelines"))
    stages_toml = _pipelines_from(cwd / "bmk_makescripts" / "stages.toml", ("pipelines",))

    section: Any = stages_toml.get(prefix) or pyproject.get(prefix)
    if not isinstance(section, dict) or not section:
        return None
    return _parse_overlay(cast("dict[str, Any]", section), f"pipelines.{prefix}")


def resolve_stages(cwd: Path, prefix: str, base: Sequence[Stage]) -> list[Stage]:
    """Return the built-in ``base`` stages with any TOML overlay applied."""
    overlay = load_overlay(cwd, prefix)
    if overlay is None:
        return list(base)
    return list(apply_overlay(base, overlay))


__all__ = [
    "Overlay",
    "StageSpec",
    "apply_overlay",
    "load_overlay",
    "resolve_stages",
]
