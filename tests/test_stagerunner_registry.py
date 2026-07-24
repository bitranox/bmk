"""Tests for the built-in pipeline registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bmk.adapters.cli.commands._shared import VENV_PIPELINES
from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.adapters.stagerunner.registry import PIPELINES
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from pathlib import Path


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


def test_clean_pipeline_registered_single_stage() -> None:
    stages = PIPELINES["clean"]
    assert [s.name for s in stages] == ["clean"]
    assert stages[0].order == 10


def test_clean_action_removes_artifacts(tmp_path: Path) -> None:
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")

    rc = PIPELINES["clean"][0].action(_ctx(tmp_path), CapturingSink())

    assert rc == 0
    assert not (tmp_path / ".ruff_cache").exists()
    assert (tmp_path / "keep.py").exists()


def test_test_all_and_clean_all_are_registered() -> None:
    assert [s.name for s in PIPELINES["test_all"]] == ["test_all"]
    assert [s.name for s in PIPELINES["clean_all"]] == ["clean_all"]


def test_test_all_and_clean_all_are_not_venv_pipelines() -> None:
    """test-all provisions its OWN matrix venvs; clean-all deletes venvs. Neither must
    trigger the pre-pipeline single-venv sync in `run_command`."""
    assert "test_all" not in VENV_PIPELINES
    assert "clean_all" not in VENV_PIPELINES


def test_clean_all_removes_venvs_and_artifacts_but_not_source(tmp_path: Path) -> None:
    """`clean-all` purges every .venv* (which plain `clean` deliberately keeps) plus caches."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    for name in (".venv", ".venv-3.10", ".venv-3.14", ".ruff_cache"):
        (tmp_path / name).mkdir()
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")

    rc = PIPELINES["clean_all"][0].action(_ctx(tmp_path), CapturingSink())

    assert rc == 0
    for name in (".venv", ".venv-3.10", ".venv-3.14", ".ruff_cache"):
        assert not (tmp_path / name).exists(), f"clean-all must remove {name}"
    assert (tmp_path / "keep.py").exists(), "source is never touched"


def test_plain_clean_keeps_the_venvs(tmp_path: Path) -> None:
    """The deliberate rule: `clean` must NOT delete .venv* (it would force a re-resolve)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".ruff_cache").mkdir()

    PIPELINES["clean"][0].action(_ctx(tmp_path), CapturingSink())

    assert (tmp_path / ".venv").exists(), "plain clean must keep the venv"
    assert not (tmp_path / ".ruff_cache").exists()
