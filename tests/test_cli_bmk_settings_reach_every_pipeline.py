"""``[bmk]`` settings reach the stage context whichever command dispatches the pipeline.

Each command used to pass ``package_name`` and ``supply_chain`` to ``run_command`` itself, and only
``test`` and ``custom`` did: ``push`` - which runs the whole test pipeline, ``update_deps`` included -
and ``deps`` silently ran under the built-in defaults. ``run_command`` now reads them from the CLI's
loaded configuration, so a command cannot forget them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters import cli as cli_mod

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner

    from bmk.adapters.stagerunner.model import Stage, StageContext


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[StageContext]:
    """The contexts every dispatched pipeline ran with; nothing actually runs."""
    contexts: list[StageContext] = []

    def _run(_stages: list[Stage], ctx: StageContext) -> int:
        contexts.append(ctx)
        return 0

    def _resolve(_cwd: Path, _prefix: str) -> list[Stage]:
        return []

    monkeypatch.setattr("bmk.adapters.stagerunner.registry.resolve_python_pipeline", _resolve)
    monkeypatch.setattr("bmk.adapters.stagerunner.engine.run_pipeline", _run)
    monkeypatch.setenv("BMK_NO_VENV_SYNC", "1")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return contexts


_OVERRIDES = [
    "--set",
    'bmk.supply_chain.cooldown="7 days"',
    "--set",
    'bmk.supply_chain.own_packages=["My_Lib"]',
    "--set",
    'bmk.package_name="my_pkg"',
]


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "command", [["push"], ["psh"], ["p"], ["deps"], ["dependencies"], ["d"], ["cov"], ["bld"], ["test"], ["testi"]]
)
def test_configured_bmk_settings_reach_the_pipeline(
    command: list[str],
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    dispatched: list[StageContext],
) -> None:
    result = cli_runner.invoke(cli_mod.cli, [*_OVERRIDES, *command], obj=production_factory)

    assert result.exit_code == 0, result.output
    [ctx] = dispatched
    assert ctx.supply_chain.cooldown == "7 days"
    assert ctx.supply_chain.own_packages == frozenset({"my-lib"})
    assert ctx.package_name == "my_pkg"


@pytest.mark.os_agnostic
def test_a_misconfigured_section_stops_the_command_with_the_reason(
    cli_runner: CliRunner, production_factory: Callable[[], Any], dispatched: list[StageContext]
) -> None:
    result = cli_runner.invoke(
        cli_mod.cli, ["--set", 'bmk.supply_chain.cooldown="14 Days"', "deps"], obj=production_factory
    )

    assert result.exit_code != 0
    assert "14 Days" in result.output
    assert dispatched == []
