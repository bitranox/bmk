"""Tests for the stage-runner model types."""

from __future__ import annotations

from pathlib import Path

from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.domain.enums import ToolOutputFormat


def test_stage_is_frozen_and_defaults_non_interactive() -> None:
    stage = Stage(name="ruff_lint", order=40, action=lambda ctx, sink: 0)
    assert stage.interactive is False
    assert stage.order == 40
    assert stage.name == "ruff_lint"


def test_stage_action_is_callable_with_context_and_sink() -> None:
    stage = Stage(name="noop", order=10, action=lambda ctx, sink: 3)
    ctx = StageContext(
        project_dir=Path("/proj"),
        args=(),
        output_format=ToolOutputFormat.JSON,
        python_cmd="python3",
        package_name="bmk",
        env={},
        show_warnings=True,
    )
    assert stage.action(ctx, CapturingSink()) == 3


def test_stage_context_carries_project_dir_and_args() -> None:
    ctx = StageContext(
        project_dir=Path("/proj"),
        args=("--x",),
        output_format=ToolOutputFormat.TEXT,
        python_cmd="python3",
        package_name="bmk",
        env={"BMK_PROJECT_DIR": "/proj"},
        show_warnings=False,
    )
    assert ctx.project_dir == Path("/proj")
    assert ctx.args == ("--x",)
    assert ctx.output_format == "text"
    assert ctx.env["BMK_PROJECT_DIR"] == "/proj"
