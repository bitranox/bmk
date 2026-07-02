"""Tests for stage-runner output sinks, warning extraction, and exit hints."""

from __future__ import annotations

import io

from bmk.adapters.stagerunner.output import (
    CapturingSink,
    PassthroughSink,
    extract_warnings,
    hint_for,
    report_batch_failures,
    report_success_summary,
)
from bmk.domain.stages import PipelineSummary, StageResult


def test_capturing_sink_buffers_text() -> None:
    sink = CapturingSink()
    sink.write("hello\n")
    sink.write("world\n")
    assert sink.getvalue() == "hello\nworld\n"


def test_passthrough_sink_writes_to_target_and_returns_empty_buffer() -> None:
    target = io.StringIO()
    sink = PassthroughSink(target)
    sink.write("live\n")
    assert target.getvalue() == "live\n"
    assert sink.getvalue() == ""


def test_extract_warnings_drops_summary_line() -> None:
    out = "src/a.py: warning: unused import\nfound 3 warnings\nok\n"
    assert extract_warnings(out) == ["src/a.py: warning: unused import"]


def test_hint_for_ruff_lint_violation() -> None:
    assert hint_for("ruff", 1) == "Lint violations found"
    assert hint_for("ruff", 99) is None
    assert hint_for("unknown-tool", 1) is None


def test_report_batch_failures_prints_only_failures() -> None:
    results = [
        StageResult("ok", 0, "passing output\n", 0.1),
        StageResult("boom", 7, "failing output\n", 0.2),
    ]
    out = io.StringIO()
    report_batch_failures(results, quiet=True, out=out)
    text = out.getvalue()
    assert "boom" in text
    assert "exit code: 7" in text
    assert "failing output" in text
    assert "passing output" not in text


def test_report_success_summary_emits_json_line_when_quiet() -> None:
    out = io.StringIO()
    report_success_summary(PipelineSummary("pass", 2, 3, None), quiet=True, out=out)
    assert out.getvalue() == '{"result":"pass","stages":2,"scripts":3}\n'


def test_report_success_summary_silent_when_not_quiet() -> None:
    out = io.StringIO()
    report_success_summary(PipelineSummary("pass", 2, 3, None), quiet=False, out=out)
    assert out.getvalue() == ""
