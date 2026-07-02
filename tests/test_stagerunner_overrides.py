"""Tests for the TOML overlay: add / remove / replace stages declaratively."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.engine import run_pipeline
from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.adapters.stagerunner.overrides import (
    Overlay,
    StageSpec,
    apply_overlay,
    load_overlay,
    resolve_stages,
)
from bmk.domain.enums import ToolOutputFormat


def _base() -> tuple[Stage, ...]:
    return (
        Stage("ruff_lint", 40, lambda ctx, sink: 0),
        Stage("pyright", 40, lambda ctx, sink: 0),
    )


def _ctx(tmp_path: Path, output_format: ToolOutputFormat = ToolOutputFormat.TEXT) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=output_format,
        python_cmd=sys.executable,
        package_name="x",
        env=dict(os.environ),
        show_warnings=True,
    )


def test_apply_overlay_add_appends_stage() -> None:
    overlay = Overlay(add=(StageSpec(name="mypy", order=50, argv=("mypy", "src")),))
    result = apply_overlay(_base(), overlay)
    assert [s.name for s in result] == ["ruff_lint", "pyright", "mypy"]
    assert result[-1].order == 50


def test_apply_overlay_remove_drops_stage_by_name() -> None:
    overlay = Overlay(remove=("pyright",))
    result = apply_overlay(_base(), overlay)
    assert [s.name for s in result] == ["ruff_lint"]


def test_apply_overlay_replace_swaps_action_keeping_order(tmp_path: Path) -> None:
    overlay = Overlay(replace=(StageSpec(name="ruff_lint", order=0, argv=(sys.executable, "-c", "print('replaced')")),))
    result = apply_overlay(_base(), overlay)
    ruff = next(s for s in result if s.name == "ruff_lint")
    assert ruff.order == 40  # original order kept
    # The swapped action runs the overlay argv:
    rc = run_pipeline([ruff], _ctx(tmp_path), out=(buf := io.StringIO()))
    assert rc == 0
    assert "replaced" in buf.getvalue()


def test_load_overlay_reads_pyproject_tool_bmk(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.bmk.pipelines.clean]\n"
        'remove = ["clean"]\n'
        "[[tool.bmk.pipelines.clean.add]]\n"
        'name = "extra"\n'
        "order = 20\n"
        'argv = ["echo", "hi"]\n',
        encoding="utf-8",
    )
    overlay = load_overlay(tmp_path, "clean")
    assert overlay is not None
    assert overlay.remove == ("clean",)
    assert overlay.add == (StageSpec(name="extra", order=20, argv=("echo", "hi")),)


def test_load_overlay_none_when_no_section(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.bmk]\n", encoding="utf-8")
    assert load_overlay(tmp_path, "clean") is None


def test_load_overlay_from_stages_toml_wins(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.bmk.pipelines.clean]\nremove = ["clean"]\n', encoding="utf-8")
    scripts = tmp_path / "bmk_makescripts"
    scripts.mkdir()
    (scripts / "stages.toml").write_text(
        '[[pipelines.clean.add]]\nname = "only"\norder = 5\nargv = ["true"]\n',
        encoding="utf-8",
    )
    overlay = load_overlay(tmp_path, "clean")
    assert overlay is not None
    assert overlay.add == (StageSpec(name="only", order=5, argv=("true",)),)
    assert overlay.remove == ()  # stages.toml replaced the pyproject overlay


def test_load_overlay_rejects_bad_argv_type(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[[tool.bmk.pipelines.clean.add]]\nname = "x"\norder = 1\nargv = "notalist"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="argv"):
        load_overlay(tmp_path, "clean")


def test_resolve_stages_applies_overlay(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[[tool.bmk.pipelines.clean.add]]\nname = "extra"\norder = 20\nargv = ["true"]\n',
        encoding="utf-8",
    )
    base = (Stage("clean", 10, lambda ctx, sink: 0),)
    resolved = resolve_stages(tmp_path, "clean", base)
    assert [s.name for s in resolved] == ["clean", "extra"]


def test_resolve_stages_returns_base_without_overlay(tmp_path: Path) -> None:
    base = (Stage("clean", 10, lambda ctx, sink: 0),)
    assert resolve_stages(tmp_path, "clean", base) == list(base)
