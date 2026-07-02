"""Declarative TOML overlay: projects add / remove / replace pipeline stages.

The overlay is the supported downstream customization mechanism. Each stage
action it defines is an argv list (a ``ToolAction``), never arbitrary code, so it
is safe and cross-OS. Sources, in ascending precedence:

1. ``pyproject.toml``               -> ``[tool.bmk.pipelines.<prefix>]``
2. ``bmk_makescripts/stages.toml``  -> ``[pipelines.<prefix>]`` (wins if present)

This parses untrusted project config, so the overlay is a Pydantic model
validated at this boundary; a malformed overlay surfaces as a clear ``ValueError``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import rtoml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .actions import ToolAction
from .model import Stage, StageContext

_MAX_ARGV = 256


class StageSpec(BaseModel):
    """A declaratively-specified stage: a name, an order, and an argv to run."""

    model_config = ConfigDict(frozen=True)

    name: str
    order: int
    argv: tuple[str, ...] = Field(min_length=1, max_length=_MAX_ARGV)


class Overlay(BaseModel):
    """Add, remove, and replace operations for one pipeline."""

    model_config = ConfigDict(frozen=True)

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


def _pipelines_from(path: Path, root_keys: tuple[str, ...]) -> dict[str, Any]:
    if not path.is_file():
        return {}
    node: dict[str, Any] = rtoml.load(path)
    for key in root_keys:
        child = node.get(key, {})
        if not isinstance(child, dict):
            return {}
        node = cast("dict[str, Any]", child)
    return node


def load_overlay(cwd: Path, prefix: str) -> Overlay | None:
    """Load and validate the overlay for ``prefix`` (``stages.toml`` wins)."""
    pyproject = _pipelines_from(cwd / "pyproject.toml", ("tool", "bmk", "pipelines"))
    stages_toml = _pipelines_from(cwd / "bmk_makescripts" / "stages.toml", ("pipelines",))

    section: Any = stages_toml.get(prefix) or pyproject.get(prefix)
    if not isinstance(section, dict) or not section:
        return None
    try:
        return Overlay.model_validate(section)
    except ValidationError as exc:
        msg = f"invalid [tool.bmk.pipelines.{prefix}] overlay: {exc}"
        raise ValueError(msg) from exc


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
