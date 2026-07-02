"""Tests for the built-in pipeline registry."""

from __future__ import annotations

from pathlib import Path

from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.adapters.stagerunner.registry import PIPELINES


def test_clean_pipeline_registered_single_stage() -> None:
    stages = PIPELINES["clean"]
    assert [s.name for s in stages] == ["clean"]
    assert stages[0].order == 10


def test_clean_action_removes_artifacts(tmp_path: Path) -> None:
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    ctx = StageContext(
        project_dir=tmp_path,
        args=(),
        output_format="json",
        python_cmd="python3",
        package_name="x",
        env={},
        show_warnings=True,
    )
    rc = PIPELINES["clean"][0].action(ctx, CapturingSink())
    assert rc == 0
    assert not (tmp_path / ".ruff_cache").exists()
    assert (tmp_path / "keep.py").exists()
