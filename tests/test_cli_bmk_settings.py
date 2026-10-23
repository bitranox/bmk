"""Every pipeline command reads the ``[bmk]`` section the same way, through ``run_command``.

Driven end to end through the real CLI and stage runner (``cli_pipeline_probe``): the probe stage
runs only if the command dispatched its pipeline, so a command that stops on a refused setting
leaves no marker behind.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import pytest
import rtoml

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner, Result

_REFUSED_COOLDOWN = "bmk.supply_chain.cooldown '14 Days' is not one bmk may write"


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("cli_args", "prefix"),
    [(["test"], "test"), (["custom", "deploy"], "deploy"), (["clean"], "clean")],
)
def test_a_refused_cooldown_stops_every_pipeline_command_with_exit_78(
    cli_pipeline_probe: Callable[..., Result], cli_args: list[str], prefix: str, tmp_path: Path
) -> None:
    result = cli_pipeline_probe(["--set", "bmk.supply_chain.cooldown=14 Days", *cli_args], prefix=prefix)

    assert result.exit_code == 78, result.output
    assert _REFUSED_COOLDOWN in result.output
    assert not (tmp_path / "PROBE").exists()


@pytest.mark.os_agnostic
def test_show_warnings_reaches_a_pipeline_that_is_not_test(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bmk.adapters import cli as cli_mod
    from bmk.adapters.stagerunner.registry import PIPELINES

    # The stage records what the stage runner exported, which is what the stages act on.
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, pathlib\npathlib.Path('PROBE').write_text(os.environ.get('BMK_SHOW_WARNINGS', 'unset'))\n",
        encoding="utf-8",
    )
    pipeline: dict[str, Any] = {
        "remove": [stage.name for stage in PIPELINES["clean"]],
        "add": [{"name": "probe", "order": 1, "argv": [sys.executable, str(probe)]}],
    }
    (tmp_path / "pyproject.toml").write_text(
        rtoml.dumps({"tool": {"bmk": {"pipelines": {"clean": pipeline}}}}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = cli_runner.invoke(cli_mod.cli, ["--set", "bmk.show_warnings=false", "clean"], obj=production_factory)

    assert result.exit_code == 0, result.output
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "0"
