"""CLI integration test command stories: script resolution, execution, and argument passing."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode


def _mock_resolve_none(script_name: str, cwd: Path) -> None:
    """Mock resolve_script_path that returns None."""
    return None


@pytest.mark.os_agnostic
def test_cli_testintegration_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'testintegration' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["testintegration", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Run integration tests only" in result.output


@pytest.mark.os_agnostic
def test_cli_testi_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'testi' alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["testi", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'testintegration'" in result.output


@pytest.mark.os_agnostic
def test_cli_ti_alias_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'ti' alias command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["ti", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "alias for 'testintegration'" in result.output


@pytest.mark.os_agnostic
def test_cli_testintegration_exits_with_file_not_found_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit code is FILE_NOT_FOUND when script doesn't exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["testintegration"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND


@pytest.mark.os_agnostic
def test_cli_testintegration_shows_error_message_when_script_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message shows searched locations when script not found."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        _mock_resolve_none,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["testintegration"], obj=production_factory)

    assert "Error: Test runner script" in result.output
    assert "not found" in result.output
    assert "Searched locations:" in result.output


@pytest.mark.os_agnostic
def test_cli_testintegration_uses_test_integration_command_prefix(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration test command uses command_prefix='test_integration'."""
    captured_args: list[tuple[Path, Path, tuple[str, ...], str]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_args.append((script_path, cwd, extra_args, command_prefix))
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_integration_cmd.execute_script",
        mock_execute,
    )

    cli_runner.invoke(cli_mod.cli, ["testintegration"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][3] == "test_integration"


@pytest.mark.os_agnostic
def test_cli_testintegration_passes_extra_arguments(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Extra CLI arguments are passed through to the script."""
    captured_args: list[tuple[Path, Path, tuple[str, ...], str]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_args.append((script_path, cwd, extra_args, command_prefix))
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_integration_cmd.execute_script",
        mock_execute,
    )

    cli_runner.invoke(
        cli_mod.cli,
        ["testintegration", "--verbose", "-k", "test_foo"],
        obj=production_factory,
    )

    assert len(captured_args) == 1
    assert captured_args[0][2] == ("--verbose", "-k", "test_foo")


@pytest.mark.os_agnostic
def test_cli_testintegration_propagates_script_exit_code(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Script's exit code is propagated as CLI exit code."""
    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\nexit 42")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        return 42

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_integration_cmd.execute_script",
        mock_execute,
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["testintegration"], obj=production_factory)

    assert result.exit_code == 42


@pytest.mark.os_agnostic
def test_cli_testintegration_defaults_output_format_to_json(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default output_format is 'json' when --human is not passed."""
    captured_kwargs: list[dict[str, Any]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_kwargs.append(kwargs)
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr("bmk.adapters.cli.commands._shared.resolve_script_path", mock_resolve)
    monkeypatch.setattr("bmk.adapters.cli.commands.test_integration_cmd.execute_script", mock_execute)
    monkeypatch.delenv("BMK_OUTPUT_FORMAT", raising=False)

    cli_runner.invoke(cli_mod.cli, ["testintegration"], obj=production_factory)

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["output_format"] == "json"


@pytest.mark.os_agnostic
def test_cli_testintegration_human_flag_sets_text_output(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The --human flag sets output_format to 'text'."""
    captured_kwargs: list[dict[str, Any]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_kwargs.append(kwargs)
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr("bmk.adapters.cli.commands._shared.resolve_script_path", mock_resolve)
    monkeypatch.setattr("bmk.adapters.cli.commands.test_integration_cmd.execute_script", mock_execute)

    cli_runner.invoke(cli_mod.cli, ["testintegration", "--human"], obj=production_factory)

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["output_format"] == "text"


@pytest.mark.os_agnostic
def test_cli_testintegration_respects_bmk_output_format_env_var(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BMK_OUTPUT_FORMAT env var is respected when --human is not passed."""
    captured_kwargs: list[dict[str, Any]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_kwargs.append(kwargs)
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr("bmk.adapters.cli.commands._shared.resolve_script_path", mock_resolve)
    monkeypatch.setattr("bmk.adapters.cli.commands.test_integration_cmd.execute_script", mock_execute)
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "text")

    cli_runner.invoke(cli_mod.cli, ["testintegration"], obj=production_factory)

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["output_format"] == "text"


@pytest.mark.os_agnostic
def test_cli_testintegration_human_flag_overrides_env_var(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The --human flag overrides BMK_OUTPUT_FORMAT env var."""
    captured_kwargs: list[dict[str, Any]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_kwargs.append(kwargs)
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr("bmk.adapters.cli.commands._shared.resolve_script_path", mock_resolve)
    monkeypatch.setattr("bmk.adapters.cli.commands.test_integration_cmd.execute_script", mock_execute)
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "json")

    cli_runner.invoke(cli_mod.cli, ["testintegration", "--human"], obj=production_factory)

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["output_format"] == "text"


@pytest.mark.os_agnostic
def test_cli_testi_behaves_same_as_testintegration(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 'testi' alias invokes the same underlying implementation."""
    captured_args: list[tuple[Path, Path, tuple[str, ...], str]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_args.append((script_path, cwd, extra_args, command_prefix))
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_integration_cmd.execute_script",
        mock_execute,
    )

    cli_runner.invoke(cli_mod.cli, ["testi", "--fast"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][2] == ("--fast",)
    assert captured_args[0][3] == "test_integration"


@pytest.mark.os_agnostic
def test_cli_ti_behaves_same_as_testintegration(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 'ti' alias invokes the same underlying implementation."""
    captured_args: list[tuple[Path, Path, tuple[str, ...], str]] = []

    def mock_execute(
        script_path: Path,
        cwd: Path,
        extra_args: tuple[str, ...],
        *,
        command_prefix: str = "test",
        **kwargs: Any,
    ) -> int:
        captured_args.append((script_path, cwd, extra_args, command_prefix))
        return 0

    script_path = tmp_path / "_btx_stagerunner.sh"
    script_path.write_text("#!/bin/bash\necho test")

    def mock_resolve(script_name: str, cwd: Path) -> Path:
        return script_path

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands._shared.resolve_script_path",
        mock_resolve,
    )
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.test_integration_cmd.execute_script",
        mock_execute,
    )

    cli_runner.invoke(cli_mod.cli, ["ti", "-v", "--tb=long"], obj=production_factory)

    assert len(captured_args) == 1
    assert captured_args[0][2] == ("-v", "--tb=long")
    assert captured_args[0][3] == "test_integration"
