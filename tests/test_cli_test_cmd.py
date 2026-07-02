"""CLI test command: end-to-end pipeline dispatch (real command, no internal mocks)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", [["test"], ["t"]])
def test_test_command_and_aliases_exist(
    cli_runner: CliRunner, production_factory: Callable[[], Any], command: list[str]
) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, [*command, "--help"], obj=production_factory)
    assert result.exit_code == 0


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", [["test"], ["t"]])
def test_test_dispatches_pipeline(
    cli_pipeline_probe: Callable[..., Result], tmp_path: Path, command: list[str]
) -> None:
    result = cli_pipeline_probe(command, prefix="test")
    assert result.exit_code == 0
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"


@pytest.mark.os_agnostic
def test_test_propagates_failure(cli_pipeline_probe: Callable[..., Result]) -> None:
    result = cli_pipeline_probe(["test"], prefix="test", exit_code=3)
    assert result.exit_code == 3
