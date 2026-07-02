"""Stage model: the data a pipeline stage is made of, and its execution context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bmk.domain.enums import ToolOutputFormat

from .output import OutputSink


@dataclass(frozen=True, slots=True)
class StageContext:
    """Everything a stage action needs to run, resolved once per pipeline.

    ``env`` is the fully-built environment mapping (project dir, venv pinning,
    output format) passed to any subprocess a stage spawns.
    """

    project_dir: Path
    args: tuple[str, ...]
    output_format: ToolOutputFormat
    python_cmd: str
    package_name: str
    env: Mapping[str, str]
    show_warnings: bool


class StageAction(Protocol):
    """Callable that performs a stage's work and returns an exit code."""

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int: ...


@dataclass(frozen=True, slots=True)
class Stage:
    """A single unit of pipeline work.

    ``order`` groups stages into sequential batches; stages sharing an ``order``
    run in parallel. ``interactive`` stages bypass output capture so prompts
    (e.g. a commit message) remain visible.
    """

    name: str
    order: int
    action: StageAction
    interactive: bool = False
