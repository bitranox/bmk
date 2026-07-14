"""Tests for the deps / deps_update pipelines (in-process helper calls)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.adapters.stagerunner.registry import PIPELINES, PORTED_PREFIXES
from bmk.domain.enums import ToolOutputFormat


def _ctx(
    tmp_path: Path,
    output_format: ToolOutputFormat = ToolOutputFormat.JSON,
    env: dict[str, str] | None = None,
) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=output_format,
        python_cmd="python3",
        package_name="x",
        env=env if env is not None else {},
        show_warnings=True,
    )


def _make_venv(path: Path) -> Path:
    """Create a directory the venv resolver accepts."""
    from bmk.adapters.stagerunner.venv import venv_python

    path.mkdir(parents=True, exist_ok=True)
    (path / "pyvenv.cfg").write_text("home = /usr\n")
    interpreter = venv_python(path)
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("")
    return path


def test_deps_pipelines_registered_and_ported() -> None:
    assert [s.name for s in PIPELINES["deps"]] == ["deps"]
    assert [s.name for s in PIPELINES["deps_update"]] == ["deps_update"]
    assert {"deps", "deps_update"} <= PORTED_PREFIXES


def test_deps_action_calls_helper_with_pyproject_and_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def fake_main(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(_dependencies, "main", fake_main)

    rc = PIPELINES["deps"][0].action(_ctx(tmp_path, ToolOutputFormat.JSON), CapturingSink())
    assert rc == 0
    assert captured["pyproject"] == tmp_path / "pyproject.toml"
    assert captured["quiet"] is True
    assert not captured.get("update")


def test_deps_action_not_quiet_in_text_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps"][0].action(_ctx(tmp_path, ToolOutputFormat.TEXT), CapturingSink())
    assert captured["quiet"] is False


def test_deps_update_action_sets_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps_update"][0].action(_ctx(tmp_path, ToolOutputFormat.JSON), CapturingSink())
    assert captured["update"] is True
    assert captured["pyproject"] == tmp_path / "pyproject.toml"


def test_deps_update_targets_the_project_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The project venv's interpreter reaches the helper."""
    from bmk.adapters.stagerunner.helpers import _dependencies
    from bmk.adapters.stagerunner.venv import venv_python

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)
    venv = _make_venv(tmp_path / ".venv")

    PIPELINES["deps_update"][0].action(_ctx(tmp_path), CapturingSink())

    assert captured["python"] == str(venv_python(venv))


def test_deps_update_targets_the_uv_project_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UV_PROJECT_ENVIRONMENT redirects the install target."""
    from bmk.adapters.stagerunner.helpers import _dependencies
    from bmk.adapters.stagerunner.venv import venv_python

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)
    venv = _make_venv(tmp_path / ".venv-win")

    PIPELINES["deps_update"][0].action(_ctx(tmp_path, env={"UV_PROJECT_ENVIRONMENT": ".venv-win"}), CapturingSink())

    assert captured["python"] == str(venv_python(venv))


def test_deps_update_passes_no_target_without_a_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a project venv the target is None, never bmk's own interpreter.

    Regression guard: falling back to ctx.python_cmd here is what let a project
    install its dependencies into whatever environment launched bmk.
    """
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps_update"][0].action(_ctx(tmp_path), CapturingSink())

    assert captured["python"] is None
