"""CLI clean command: end-to-end pipeline dispatch (real command, no internal mocks)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters import cli as cli_mod

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner, Result


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", ["clean", "cln", "cl"])
def test_clean_command_and_aliases_exist(
    cli_runner: CliRunner, production_factory: Callable[[], Any], command: str
) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, [command, "--help"], obj=production_factory)
    assert result.exit_code == 0


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", ["clean", "cln", "cl"])
def test_clean_dispatches_pipeline(cli_pipeline_probe: Callable[..., Result], tmp_path: Path, command: str) -> None:
    result = cli_pipeline_probe([command], prefix="clean")
    assert result.exit_code == 0
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"


@pytest.mark.os_agnostic
def test_clean_propagates_failure(cli_pipeline_probe: Callable[..., Result]) -> None:
    result = cli_pipeline_probe(["clean"], prefix="clean", exit_code=3)
    assert result.exit_code == 3
