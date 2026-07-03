"""Tests for stage-runner actions (argv/tool/helper)."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from bmk.adapters.stagerunner import actions as actions_mod
from bmk.adapters.stagerunner.actions import HelperAction, ToolAction, ToolActionWithSetup, run_argv
from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink, OutputSink
from bmk.domain.enums import ToolOutputFormat


def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=ToolOutputFormat.JSON,
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


def test_tool_action_with_setup_runs_setup_then_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
        calls.append(list(argv))
        return 0 if argv[0] == "setup" else 7

    monkeypatch.setattr(actions_mod, "run_argv", fake_run_argv)
    action = ToolActionWithSetup(lambda _ctx: ["setup"], lambda _ctx: ["main"])
    rc = action(_ctx(tmp_path), CapturingSink())
    assert calls == [["setup"], ["main"]]  # setup runs before main, into the same sink
    assert rc == 7  # the stage's exit code is the main tool's, not setup's


def test_tool_action_with_setup_runs_main_even_when_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
        calls.append(list(argv))
        return 1 if argv[0] == "setup" else 0  # setup fails, main succeeds

    monkeypatch.setattr(actions_mod, "run_argv", fake_run_argv)
    action = ToolActionWithSetup(lambda _ctx: ["setup"], lambda _ctx: ["main"])
    rc = action(_ctx(tmp_path), CapturingSink())
    assert calls == [["setup"], ["main"]]  # best-effort setup does not short-circuit the main tool
    assert rc == 0  # setup's non-zero is ignored; the main tool decides
