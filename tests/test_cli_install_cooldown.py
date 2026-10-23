"""``bmk install`` deploys bmk's cooldown beside the Makefile, and refreshes the two together.

The template's ``_ensure_bmk`` reads ``.bmk-cooldown.mk`` from the Makefile's directory
(``tests/test_makefile_cooldown.py``). The pair carries one version - the Makefile's sentinel - so
every path that writes the Makefile writes the cooldown with it; a Makefile updated alone would run
the new recipe under the previous release's exemptions.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters import cli as cli_mod

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner

BUNDLED_COOLDOWN = Path(cli_mod.__file__).resolve().parent.parent.parent / "makefile" / "cooldown.mk"
DEPLOYED = ".bmk-cooldown.mk"
_STALE = "# a cooldown from an older bmk release\n"


@pytest.mark.os_agnostic
def test_a_fresh_install_deploys_the_cooldown_beside_the_makefile(
    cli_runner: CliRunner, production_factory: Callable[[], Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == 0, result.output
    assert (tmp_path / DEPLOYED).read_text(encoding="utf-8") == BUNDLED_COOLDOWN.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_updating_a_managed_makefile_refreshes_the_cooldown_too(
    cli_runner: CliRunner, production_factory: Callable[[], Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    (tmp_path / "Makefile").write_text("# BMK MAKEFILE 0.0.1\n", encoding="utf-8")
    (tmp_path / DEPLOYED).write_text(_STALE, encoding="utf-8")

    result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == 0, result.output
    assert (tmp_path / DEPLOYED).read_text(encoding="utf-8") == BUNDLED_COOLDOWN.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_a_custom_makefile_gets_no_cooldown(
    cli_runner: CliRunner, production_factory: Callable[[], Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    (tmp_path / "Makefile").write_text("all:\n\techo custom\n", encoding="utf-8")

    cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert not (tmp_path / DEPLOYED).exists(), "a custom Makefile never reads the cooldown"


@pytest.mark.os_agnostic
def test_the_outdated_makefile_refresh_brings_the_cooldown_along(
    cli_runner: CliRunner, production_factory: Callable[[], Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "json")
    (tmp_path / "Makefile").write_text("# BMK MAKEFILE 0.0.1\n", encoding="utf-8")
    (tmp_path / DEPLOYED).write_text(_STALE, encoding="utf-8")

    result = cli_runner.invoke(cli_mod.cli, ["info"], obj=production_factory)

    assert result.exit_code == 0, result.output
    assert (tmp_path / DEPLOYED).read_text(encoding="utf-8") == BUNDLED_COOLDOWN.read_text(encoding="utf-8")
