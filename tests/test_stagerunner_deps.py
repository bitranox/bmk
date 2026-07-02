"""Tests for the deps / deps_update pipelines (in-process helper calls)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.adapters.stagerunner.registry import PIPELINES, PORTED_PREFIXES


def _ctx(tmp_path: Path, output_format: str = "json") -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=output_format,
        python_cmd="python3",
        package_name="x",
        env={},
        show_warnings=True,
    )


def test_deps_pipelines_registered_and_ported() -> None:
    assert [s.name for s in PIPELINES["deps"]] == ["deps"]
    assert [s.name for s in PIPELINES["deps_update"]] == ["deps_update"]
    assert {"deps", "deps_update"} <= PORTED_PREFIXES


def test_deps_action_calls_helper_with_pyproject_and_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.makescripts import _dependencies

    captured: dict[str, Any] = {}

    def fake_main(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(_dependencies, "main", fake_main)

    rc = PIPELINES["deps"][0].action(_ctx(tmp_path, "json"), CapturingSink())
    assert rc == 0
    assert captured["pyproject"] == tmp_path / "pyproject.toml"
    assert captured["quiet"] is True
    assert not captured.get("update")


def test_deps_action_not_quiet_in_text_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.makescripts import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps"][0].action(_ctx(tmp_path, "text"), CapturingSink())
    assert captured["quiet"] is False


def test_deps_update_action_sets_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.makescripts import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps_update"][0].action(_ctx(tmp_path, "json"), CapturingSink())
    assert captured["update"] is True
    assert captured["pyproject"] == tmp_path / "pyproject.toml"
