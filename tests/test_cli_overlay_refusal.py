"""A malformed pipeline overlay is refused with one readable line per problem.

The overlay is project configuration a user writes by hand, so its refusal is user-facing text.
pydantic's own report spans several lines per problem, echoes the offending input, and ends each
problem with a versioned documentation URL; none of that helps the person fixing ``pyproject.toml``.
These tests go through the real ``main()`` entry point, which is where the ``ValueError`` from the
overlay loader is turned into the message and exit code a user sees.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest
from lib_layered_config import Config

from bmk.adapters.cli.main import main
from bmk.adapters.stagerunner.overrides import load_overlay
from bmk.composition import AppServices, build_testing

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_BAD_OVERLAY = """\
[project]
name = "demo"
version = "0.1.0"

[[tool.bmk.pipelines.deploy.add]]
name = "upload"
order = "soon"
argv = []
"""

_EXPECTED = (
    "invalid [tool.bmk.pipelines.deploy] overlay:\n"
    "  add.0.order: Input should be a valid integer, unable to parse string as an integer\n"
    "  add.0.argv: Tuple should have at least 1 item after validation, not 0"
)


def _services() -> Callable[[], AppServices]:
    config = Config({}, {})

    def get_config(**_kwargs: Any) -> Config:
        return config

    def build() -> AppServices:
        return dataclasses.replace(build_testing(), get_config=get_config)

    return build


@pytest.mark.os_agnostic
def test_load_overlay_names_each_problem_on_its_own_line(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(_BAD_OVERLAY, encoding="utf-8")

    with pytest.raises(ValueError, match=r"^invalid \[tool\.bmk\.pipelines\.deploy\] overlay:") as raised:
        load_overlay(tmp_path, "deploy")

    assert str(raised.value) == _EXPECTED


@pytest.mark.os_agnostic
def test_custom_command_reports_a_bad_overlay_without_pydantic_internals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(_BAD_OVERLAY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["custom", "deploy"], services_factory=_services())

    err = capsys.readouterr().err
    assert exit_code == 22
    assert _EXPECTED in err
    assert "pydantic" not in err
    assert "https://errors.pydantic.dev" not in err
    assert "input_value" not in err
    assert "validation errors for Overlay" not in err
