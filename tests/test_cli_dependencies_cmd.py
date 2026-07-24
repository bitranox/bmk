"""CLI dependencies command: end-to-end pipeline dispatch across all aliases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters import cli as cli_mod

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner, Result

# The command is exposed under three group names, each with the same behaviour.
GROUPS = ["dependencies", "deps", "d"]
# Forms that trigger the update pipeline (subcommand, alias, or flag).
UPDATE_FORMS = [["update"], ["u"], ["--update"]]


@pytest.mark.os_agnostic
@pytest.mark.parametrize("group", GROUPS)
def test_deps_group_exists(cli_runner: CliRunner, production_factory: Callable[[], Any], group: str) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, [group, "--help"], obj=production_factory)
    assert result.exit_code == 0


@pytest.mark.os_agnostic
@pytest.mark.parametrize("group", GROUPS)
def test_deps_check_dispatches_deps_pipeline(
    cli_pipeline_probe: Callable[..., Result], tmp_path: Path, group: str
) -> None:
    result = cli_pipeline_probe([group], prefix="deps")
    assert result.exit_code == 0
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"


@pytest.mark.os_agnostic
@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("form", UPDATE_FORMS)
def test_deps_update_dispatches_deps_update_pipeline(
    cli_pipeline_probe: Callable[..., Result], tmp_path: Path, group: str, form: list[str]
) -> None:
    result = cli_pipeline_probe([group, *form], prefix="deps_update")
    assert result.exit_code == 0
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"


@pytest.mark.os_agnostic
def test_deps_propagates_failure(cli_pipeline_probe: Callable[..., Result]) -> None:
    result = cli_pipeline_probe(["deps"], prefix="deps", exit_code=3)
    assert result.exit_code == 3
