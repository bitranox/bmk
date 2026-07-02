"""Tests for PipelineAction (pipeline-composes-pipeline delegator)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.actions import PipelineAction
from bmk.adapters.stagerunner.engine import run_pipeline
from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.domain.enums import ToolOutputFormat


def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=ToolOutputFormat.JSON,
        python_cmd="python3",
        package_name="x",
        env={},
        show_warnings=True,
    )


def test_pipeline_action_runs_delegated_pipeline(tmp_path: Path) -> None:
    (tmp_path / ".ruff_cache").mkdir()
    outer = [Stage("delegate_clean", 10, PipelineAction("clean"))]
    rc = run_pipeline(outer, _ctx(tmp_path), out=io.StringIO())
    assert rc == 0
    assert not (tmp_path / ".ruff_cache").exists()


def test_pipeline_action_propagates_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.adapters.stagerunner import registry

    boom_stage = Stage("boom", 10, lambda ctx, sink: 9)
    patched = {**registry.PIPELINES, "inner_fail": (boom_stage,)}
    monkeypatch.setattr(registry, "PIPELINES", patched)

    outer = [Stage("delegate_fail", 10, PipelineAction("inner_fail"))]
    rc = run_pipeline(outer, _ctx(tmp_path), out=io.StringIO())
    assert rc == 9
