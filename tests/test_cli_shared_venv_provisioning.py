"""Tests for venv provisioning at the run_command boundary.

Provisioning happens before ``build_context`` rather than as a pipeline stage:
the context pins ``VIRTUAL_ENV`` / ``PIPAPI_PYTHON_LOCATION`` once and
``StageContext`` is frozen, so a venv created by a stage could not repair the
pins for the stages that follow it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from bmk.adapters.cli.commands._shared import VENV_PIPELINES, run_command
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from pathlib import Path

    from bmk.adapters.stagerunner.model import Stage, StageContext


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every prefix to a trivial pipeline that runs nothing."""

    def _resolve(_cwd: Path, _prefix: str) -> list[Stage]:
        return []

    def _run(_stages: list[Stage], _ctx: StageContext) -> int:
        return 0

    monkeypatch.setattr("bmk.adapters.stagerunner.registry.resolve_python_pipeline", _resolve)
    monkeypatch.setattr("bmk.adapters.stagerunner.engine.run_pipeline", _run)


@pytest.mark.os_agnostic
@pytest.mark.parametrize("prefix", sorted(VENV_PIPELINES))
@patch("bmk.adapters.stagerunner.venv.ensure_project_venv")
def test_env_reading_pipelines_provision_the_venv(
    mock_ensure: MagicMock, prefix: str, tmp_path: Path, stub_pipeline: Any
) -> None:
    """Every pipeline that reads or writes the environment provisions it first."""
    run_command(tmp_path, (), command_prefix=prefix, output_format=ToolOutputFormat.JSON)

    mock_ensure.assert_called_once()
    assert mock_ensure.call_args[0][0] == tmp_path


@pytest.mark.os_agnostic
@pytest.mark.parametrize("prefix", ["clean", "commit", "rel", "run", "bump_patch"])
@patch("bmk.adapters.stagerunner.venv.ensure_project_venv")
def test_other_pipelines_do_not_provision(
    mock_ensure: MagicMock, prefix: str, tmp_path: Path, stub_pipeline: Any
) -> None:
    """A command that never looks at the environment must not build one."""
    run_command(tmp_path, (), command_prefix=prefix, output_format=ToolOutputFormat.JSON)

    mock_ensure.assert_not_called()


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv.ensure_project_venv")
def test_bmk_no_venv_sync_opts_out(
    mock_ensure: MagicMock, tmp_path: Path, stub_pipeline: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BMK_NO_VENV_SYNC=1 skips provisioning entirely."""
    monkeypatch.setenv("BMK_NO_VENV_SYNC", "1")

    run_command(tmp_path, (), command_prefix="test", output_format=ToolOutputFormat.JSON)

    mock_ensure.assert_not_called()


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.venv.ensure_project_venv", return_value=None)
def test_pipeline_still_runs_when_provisioning_fails(
    _mock_ensure: MagicMock, tmp_path: Path, stub_pipeline: Any
) -> None:
    """A provisioning failure degrades to the previous behaviour, not an abort."""
    assert run_command(tmp_path, (), command_prefix="test", output_format=ToolOutputFormat.JSON) == 0
