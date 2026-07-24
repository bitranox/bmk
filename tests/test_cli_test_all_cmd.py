"""CLI test-all command: end-to-end pipeline dispatch (real command, no internal mocks)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters import cli as cli_mod

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner, Result


@pytest.mark.os_agnostic
def test_test_all_command_exists(cli_runner: CliRunner, production_factory: Callable[[], Any]) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, ["test-all", "--help"], obj=production_factory)
    assert result.exit_code == 0


@pytest.mark.os_agnostic
def test_test_all_dispatches_matrix_pipeline(cli_pipeline_probe: Callable[..., Result], tmp_path: Path) -> None:
    result = cli_pipeline_probe(["test-all"], prefix="test_all")
    assert result.exit_code == 0
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"


@pytest.mark.os_agnostic
def test_test_all_forwards_human_flag(cli_pipeline_probe: Callable[..., Result], tmp_path: Path) -> None:
    """The --human flag is accepted and still dispatches the test_all prefix."""
    result = cli_pipeline_probe(["test-all", "--human"], prefix="test_all")
    assert result.exit_code == 0
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"


@pytest.mark.os_agnostic
def test_test_all_propagates_failure(cli_pipeline_probe: Callable[..., Result]) -> None:
    result = cli_pipeline_probe(["test-all"], prefix="test_all", exit_code=5)
    assert result.exit_code == 5
