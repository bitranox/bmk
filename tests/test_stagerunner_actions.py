"""Tests for stage-runner actions (argv/tool/helper)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from bmk.adapters.stagerunner.actions import HelperAction, ToolAction, run_argv
from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink


def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format="json",
        python_cmd=sys.executable,
        package_name="x",
        env=dict(os.environ),
        show_warnings=True,
    )


def test_run_argv_captures_output_and_returncode(tmp_path: Path) -> None:
    sink = CapturingSink()
    rc = run_argv([sys.executable, "-c", "print('hi'); raise SystemExit(3)"], _ctx(tmp_path), sink)
    assert rc == 3
    assert "hi" in sink.getvalue()


def test_run_argv_normalizes_zero(tmp_path: Path) -> None:
    sink = CapturingSink()
    rc = run_argv([sys.executable, "-c", "print('ok')"], _ctx(tmp_path), sink)
    assert rc == 0
    assert "ok" in sink.getvalue()


def test_tool_action_builds_argv_from_context(tmp_path: Path) -> None:
    action = ToolAction(lambda ctx: [sys.executable, "-c", "print('built')"])
    sink = CapturingSink()
    assert action(_ctx(tmp_path), sink) == 0
    assert "built" in sink.getvalue()


def test_helper_action_calls_func_in_process(tmp_path: Path) -> None:
    seen: list[StageContext] = []

    def helper(ctx: StageContext) -> int:
        seen.append(ctx)
        return 5

    action = HelperAction(helper)
    assert action(_ctx(tmp_path), CapturingSink()) == 5
    assert seen and seen[0].project_dir == tmp_path
