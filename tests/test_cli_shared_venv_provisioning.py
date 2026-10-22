"""Tests for venv provisioning at the run_command boundary.

Provisioning happens before ``build_context`` rather than as a pipeline stage:
the context pins ``VIRTUAL_ENV`` / ``PIPAPI_PYTHON_LOCATION`` once and
``StageContext`` is frozen, so a venv created by a stage could not repair the
pins for the stages that follow it.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from bmk.adapters.cli.commands._shared import VENV_PIPELINES, run_command
from bmk.domain.enums import ToolOutputFormat, VenvProvisioning

if TYPE_CHECKING:
    from pathlib import Path

    from uv_stub import StubUv

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


# --- what provisioning did reaches the stages (OPEN-WORK [230]) ------------------------------------
# `deps_update` re-syncs the venv; it must know whether this run's provisioning already failed, so the
# outcome travels in the StageContext. Only the pipeline engine is replaced (to receive that context);
# provisioning itself runs for real, against the stub uv or the real one.


@pytest.fixture
def seen_contexts(monkeypatch: pytest.MonkeyPatch) -> list[StageContext]:
    """Every StageContext ``run_command`` hands the engine; the pipeline itself runs nothing."""
    seen: list[StageContext] = []

    def _resolve(_cwd: Path, _prefix: str) -> list[Stage]:
        return []

    def _run(_stages: list[Stage], ctx: StageContext) -> int:
        seen.append(ctx)
        return 0

    monkeypatch.setattr("bmk.adapters.stagerunner.registry.resolve_python_pipeline", _resolve)
    monkeypatch.setattr("bmk.adapters.stagerunner.engine.run_pipeline", _run)
    monkeypatch.delenv("BMK_NO_VENV_SYNC", raising=False)
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    return seen


def _provisioning_of(project: Path, seen: list[StageContext], prefix: str = "test") -> VenvProvisioning:
    assert run_command(project, (), command_prefix=prefix, output_format=ToolOutputFormat.JSON) == 0
    (ctx,) = seen
    return ctx.venv_provisioning


@pytest.fixture
def stub_project(tmp_path: Path, stub_uv: StubUv) -> Path:
    _ = stub_uv  # requested for its PATH and lock-dir setup
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    return project


@pytest.mark.os_posix
def test_a_provisioned_venv_reaches_the_stages_as_provisioned(
    stub_project: Path, seen_contexts: list[StageContext]
) -> None:
    assert _provisioning_of(stub_project, seen_contexts) is VenvProvisioning.PROVISIONED


@pytest.mark.os_posix
def test_a_failed_provisioning_reaches_the_stages_as_failed(
    stub_project: Path, stub_uv: StubUv, seen_contexts: list[StageContext]
) -> None:
    stub_uv.install(sync_rc=1)

    assert _provisioning_of(stub_project, seen_contexts) is VenvProvisioning.FAILED


@pytest.mark.os_agnostic
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_a_real_uv_failure_reaches_the_stages_as_failed(
    tmp_path: Path, seen_contexts: list[StageContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same outcome from the real uv, so it is covered on Windows too: a dependency that exists
    nowhere, resolved offline against a cold cache, fails both the lock and the manifest install."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
        'dependencies = ["bmk-no-such-package-c5e2"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("BMK_VENV_LOCK_DIR", str(tmp_path / "locks"))

    assert _provisioning_of(project, seen_contexts) is VenvProvisioning.FAILED


@pytest.mark.os_agnostic
def test_bmk_no_venv_sync_reaches_the_stages_as_skipped(
    tmp_path: Path, seen_contexts: list[StageContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    monkeypatch.setenv("BMK_NO_VENV_SYNC", "1")

    assert _provisioning_of(tmp_path, seen_contexts) is VenvProvisioning.SKIPPED


@pytest.mark.os_agnostic
def test_a_pipeline_that_needs_no_venv_reaches_the_stages_as_not_attempted(
    tmp_path: Path, seen_contexts: list[StageContext]
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")

    assert _provisioning_of(tmp_path, seen_contexts, prefix="clean") is VenvProvisioning.NOT_ATTEMPTED
