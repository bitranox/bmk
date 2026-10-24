"""A malformed pipeline overlay is refused with one readable line per problem.

The overlay is project configuration a user writes by hand, so its refusal is user-facing text.
pydantic's own report spans several lines per problem, echoes the offending input, and ends each
problem with a versioned documentation URL; none of that helps the person fixing ``pyproject.toml``.
These tests go through the real ``main()`` entry point, which is where the refusal from the overlay
loader is turned into the message and exit code a user sees.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest
from lib_layered_config import Config

from bmk.adapters.cli.exit_codes import ExitCode
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
def test_a_bad_stages_toml_overlay_names_that_file_and_its_own_table(tmp_path: Path) -> None:
    """stages.toml has no [tool.bmk] prefix, so naming the pyproject table would send the reader to the wrong file."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")
    (tmp_path / "bmk_makescripts").mkdir()
    (tmp_path / "bmk_makescripts" / "stages.toml").write_text(
        '[[pipelines.deploy.add]]\nname = "upload"\norder = "soon"\nargv = ["true"]\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="overlay:") as raised:
        load_overlay(tmp_path, "deploy")

    assert str(raised.value) == (
        "invalid bmk_makescripts/stages.toml [pipelines.deploy] overlay:\n"
        "  add.0.order: Input should be a valid integer, unable to parse string as an integer"
    )


def _two_overlays(tmp_path: Path, stages_toml: str) -> None:
    """A valid pyproject overlay for ``deploy`` beside a stages.toml holding ``stages_toml``."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.bmk.pipelines.deploy]\nremove = ["lint"]\n',
        encoding="utf-8",
    )
    (tmp_path / "bmk_makescripts").mkdir()
    (tmp_path / "bmk_makescripts" / "stages.toml").write_text(stages_toml, encoding="utf-8")


@pytest.mark.os_agnostic
def test_an_empty_stages_toml_table_still_wins_over_pyproject(tmp_path: Path) -> None:
    """stages.toml wins when it names the pipeline at all; an empty table is a definition, not an absence."""
    _two_overlays(tmp_path, "[pipelines.deploy]\n")

    assert load_overlay(tmp_path, "deploy") is None


@pytest.mark.os_agnostic
def test_a_stages_toml_section_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    """``[[pipelines.deploy]]`` (an array of tables) is a typo; ignoring it also dropped the pyproject overlay."""
    _two_overlays(tmp_path, '[[pipelines.deploy]]\nremove = ["lint"]\n')

    with pytest.raises(ValueError, match="overlay:") as raised:
        load_overlay(tmp_path, "deploy")

    assert str(raised.value) == "invalid bmk_makescripts/stages.toml [pipelines.deploy] overlay:\n  must be a table"


@pytest.mark.os_agnostic
def test_custom_command_reports_a_bad_overlay_without_pydantic_internals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(_BAD_OVERLAY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["custom", "deploy"], services_factory=_services())

    err = capsys.readouterr().err
    # A refused overlay is a configuration refusal: the same fixed code on every OS, no crash report.
    assert exit_code == ExitCode.CONFIG_ERROR
    assert f"Error: {_EXPECTED}" in err
    assert "Traceback" not in err
    assert "ValueError" not in err
    assert "pydantic" not in err
    assert "https://errors.pydantic.dev" not in err
    assert "input_value" not in err
    assert "validation errors for Overlay" not in err


@pytest.mark.os_agnostic
def test_a_stages_toml_pipelines_key_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    """``pipelines`` belongs to bmk; a wrong shape there must not silently hand over to pyproject."""
    _two_overlays(tmp_path, "pipelines = 3\n")

    with pytest.raises(ValueError, match="must be a table") as raised:
        load_overlay(tmp_path, "deploy")

    assert str(raised.value) == "invalid bmk_makescripts/stages.toml [pipelines]:\n  must be a table"


@pytest.mark.os_agnostic
def test_a_pyproject_pipelines_key_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.bmk]\npipelines = 5\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="must be a table") as raised:
        load_overlay(tmp_path, "deploy")

    assert str(raised.value) == "invalid [tool.bmk.pipelines]:\n  must be a table"


@pytest.mark.os_agnostic
def test_a_wrong_shaped_shared_tool_table_still_reads_as_no_overlay(tmp_path: Path) -> None:
    """``[tool]`` is shared with every other tool; its shape is not bmk's to refuse."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ntool = 3\n', encoding="utf-8"
    )

    assert load_overlay(tmp_path, "deploy") is None
