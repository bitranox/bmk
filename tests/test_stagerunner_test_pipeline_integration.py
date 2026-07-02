"""Integration: run a real registry tool stage through the engine (offline, fast)."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.engine import run_pipeline
from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.adapters.stagerunner.registry import PIPELINES


def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format="text",
        python_cmd=sys.executable,
        package_name="x",
        env=dict(os.environ),
        show_warnings=True,
    )


def _ruff_format_check_stage() -> Stage:
    return next(s for s in PIPELINES["test"] if s.name == "ruff_format_check")


@pytest.mark.os_agnostic
def test_ruff_format_check_passes_on_formatted_file(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    rc = run_pipeline([_ruff_format_check_stage()], _ctx(tmp_path), out=io.StringIO())
    assert rc == 0


@pytest.mark.os_agnostic
def test_ruff_format_check_fails_on_unformatted_file(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("x=1\n", encoding="utf-8")  # ruff would reformat -> check fails
    rc = run_pipeline([_ruff_format_check_stage()], _ctx(tmp_path), out=io.StringIO())
    assert rc != 0
