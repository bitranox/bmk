"""Tests for the stage-runner engine (batching, parallelism, fail-fast)."""

from __future__ import annotations

import io
import time
from pathlib import Path

from bmk.adapters.stagerunner.engine import run_pipeline
from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.adapters.stagerunner.output import OutputSink
from bmk.domain.enums import ToolOutputFormat


def _ctx(tmp_path: Path, output_format: ToolOutputFormat = ToolOutputFormat.JSON) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=output_format,
        python_cmd="python3",
        package_name="x",
        env={},
        show_warnings=True,
    )


def test_run_pipeline_returns_zero_and_emits_summary_on_success(tmp_path: Path) -> None:
    stages = [Stage("a", 10, lambda ctx, sink: 0), Stage("b", 20, lambda ctx, sink: 0)]
    out = io.StringIO()
    rc = run_pipeline(stages, _ctx(tmp_path), out=out)
    assert rc == 0
    assert out.getvalue() == '{"result":"pass","stages":2,"scripts":2}\n'


def test_run_pipeline_fail_fast_skips_later_batches(tmp_path: Path) -> None:
    called: list[str] = []

    def ok(ctx: StageContext, sink: OutputSink) -> int:
        called.append("a")
        return 0

    def boom(ctx: StageContext, sink: OutputSink) -> int:
        called.append("b")
        return 7

    def never(ctx: StageContext, sink: OutputSink) -> int:
        called.append("c")
        return 0

    stages = [Stage("a", 10, ok), Stage("b", 20, boom), Stage("c", 30, never)]
    rc = run_pipeline(stages, _ctx(tmp_path), out=io.StringIO())
    assert rc == 7
    assert "c" not in called


def test_run_pipeline_normalizes_signal_returncode(tmp_path: Path) -> None:
    stages = [Stage("killed", 10, lambda ctx, sink: -2)]
    rc = run_pipeline(stages, _ctx(tmp_path), out=io.StringIO())
    assert rc == 130


def test_run_pipeline_reports_action_exception_as_failure(tmp_path: Path) -> None:
    def boom(ctx: StageContext, sink: OutputSink) -> int:
        msg = "helper blew up"
        raise RuntimeError(msg)

    out = io.StringIO()
    rc = run_pipeline([Stage("boom", 10, boom)], _ctx(tmp_path), out=out)
    assert rc == 1
    assert "helper blew up" in out.getvalue()


def test_run_batch_runs_equal_order_in_parallel(tmp_path: Path) -> None:
    def slow(ctx: StageContext, sink: OutputSink) -> int:
        time.sleep(0.3)
        return 0

    stages = [Stage("x", 40, slow), Stage("y", 40, slow)]
    start = time.monotonic()
    assert run_pipeline(stages, _ctx(tmp_path), out=io.StringIO()) == 0
    assert time.monotonic() - start < 0.55  # overlapped, not ~0.6 serial


def test_run_pipeline_reports_failure_output_in_json_mode(tmp_path: Path) -> None:
    def boom(ctx: StageContext, sink: OutputSink) -> int:
        sink.write("boom details\n")
        return 3

    out = io.StringIO()
    rc = run_pipeline([Stage("boom", 10, boom)], _ctx(tmp_path), out=out)
    assert rc == 3
    text = out.getvalue()
    assert "boom" in text
    assert "boom details" in text
