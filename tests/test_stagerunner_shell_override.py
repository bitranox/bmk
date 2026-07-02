"""Tests for legacy shell-override support during migration.

Downstream projects may ship ``bmk_makescripts/{prefix}_NN_*.sh`` overrides. Under
the Python runner these must still run (via ShellStageAction) and, matching the
old shell behaviour, replace the built-in pipeline entirely. Removed in Phase 5.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.actions import ShellStageAction
from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.adapters.stagerunner.overrides import discover_shell_overrides, resolve_pipeline


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


@pytest.mark.os_posix
def test_shell_stage_action_runs_script(tmp_path: Path) -> None:
    script = tmp_path / "run.sh"
    script.write_text("#!/usr/bin/env bash\necho ran > marker.txt\n", encoding="utf-8")
    script.chmod(0o755)
    rc = ShellStageAction(script)(_ctx(tmp_path), CapturingSink())
    assert rc == 0
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8").strip() == "ran"


def test_discover_shell_overrides_builds_ordered_stages(tmp_path: Path) -> None:
    scripts = tmp_path / "bmk_makescripts"
    scripts.mkdir()
    suffix = ".ps1" if sys.platform == "win32" else ".sh"
    (scripts / f"clean_010_a{suffix}").write_text("#\n", encoding="utf-8")
    (scripts / f"clean_020_b{suffix}").write_text("#\n", encoding="utf-8")
    (scripts / f"other_010_x{suffix}").write_text("#\n", encoding="utf-8")

    stages = discover_shell_overrides(tmp_path, "clean")
    assert sorted((s.order, s.name) for s in stages) == [
        (10, "clean_010_a"),
        (20, "clean_020_b"),
    ]


def test_discover_shell_overrides_empty_when_none(tmp_path: Path) -> None:
    assert discover_shell_overrides(tmp_path, "clean") == []


def test_resolve_pipeline_prefers_shell_override(tmp_path: Path) -> None:
    scripts = tmp_path / "bmk_makescripts"
    scripts.mkdir()
    suffix = ".ps1" if sys.platform == "win32" else ".sh"
    (scripts / f"clean_010_a{suffix}").write_text("#\n", encoding="utf-8")

    base = (Stage("clean", 10, lambda ctx, sink: 0),)
    stages = resolve_pipeline(tmp_path, "clean", base)
    assert [s.name for s in stages] == ["clean_010_a"]


def test_resolve_pipeline_uses_builtin_when_no_override(tmp_path: Path) -> None:
    base = (Stage("clean", 10, lambda ctx, sink: 0),)
    assert [s.name for s in resolve_pipeline(tmp_path, "clean", base)] == ["clean"]
