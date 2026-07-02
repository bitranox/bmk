"""CLI custom command: registration, name validation, and pipeline dispatch."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode


@pytest.mark.os_agnostic
def test_cli_custom_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, ["custom", "--help"], obj=production_factory)
    assert result.exit_code == 0


@pytest.mark.os_agnostic
def test_cli_custom_requires_command_name(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, ["custom"], obj=production_factory)
    assert result.exit_code != 0
    assert "Missing argument" in result.output


@pytest.mark.os_agnostic
def test_validate_command_name_accepts_simple_names() -> None:
    from bmk.adapters.cli.commands.custom_cmd import validate_command_name

    for name in ("deploy", "my-task", "build_prod", "stage2"):
        validate_command_name(name)  # must not raise


@pytest.mark.os_agnostic
def test_validate_command_name_rejects_glob_metacharacters() -> None:
    from click import BadParameter

    from bmk.adapters.cli.commands.custom_cmd import validate_command_name

    for bad_name in ("*", "deploy*", "task?", "[a-z]", "name{a,b}"):
        with pytest.raises(BadParameter):
            validate_command_name(bad_name)


@pytest.mark.os_agnostic
def test_validate_command_name_rejects_path_traversal() -> None:
    from click import BadParameter

    from bmk.adapters.cli.commands.custom_cmd import validate_command_name

    for bad_name in ("../etc", "foo/bar", "..\\secret", ".hidden"):
        with pytest.raises(BadParameter):
            validate_command_name(bad_name)


@pytest.mark.os_agnostic
def test_cli_custom_rejects_unsafe_command_name(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    result: Result = cli_runner.invoke(cli_mod.cli, ["custom", "../../etc"], obj=production_factory)
    assert result.exit_code != 0


@pytest.mark.os_agnostic
def test_cli_custom_dispatches_named_pipeline(
    cli_pipeline_probe: Callable[..., Result],
    tmp_path: Path,
) -> None:
    # An overlay-defined custom pipeline runs end-to-end via `bmk custom <name>`.
    result = cli_pipeline_probe(["custom", "deploy"], prefix="deploy")
    assert result.exit_code == 0
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"


@pytest.mark.os_agnostic
def test_cli_custom_unknown_pipeline_exits_file_not_found(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    result: Result = cli_runner.invoke(cli_mod.cli, ["custom", "nosuchpipeline"], obj=production_factory)
    assert result.exit_code == ExitCode.FILE_NOT_FOUND
