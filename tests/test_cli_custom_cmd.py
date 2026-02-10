"""CLI custom command stories: registration, script discovery, execution, and errors."""

from __future__ import annotations

import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode

# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_custom_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'custom' command is registered and --help works."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["custom", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Run a custom command" in result.output


@pytest.mark.os_agnostic
def test_cli_custom_requires_command_name(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """custom command requires COMMAND_NAME argument."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["custom"], obj=production_factory)

    assert result.exit_code != 0
    assert "Missing argument" in result.output


# ---------------------------------------------------------------------------
# Command name validation (security: prevent glob/sed injection)
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_validate_command_name_accepts_simple_names() -> None:
    """Simple alphanumeric names with hyphens and underscores pass validation."""
    from bmk.adapters.cli.commands.custom_cmd import validate_command_name

    for name in ("deploy", "my-task", "build_prod", "stage2"):
        validate_command_name(name)  # must not raise


@pytest.mark.os_agnostic
def test_validate_command_name_rejects_glob_metacharacters() -> None:
    """Names containing glob metacharacters are rejected."""
    from click import BadParameter

    from bmk.adapters.cli.commands.custom_cmd import validate_command_name

    for bad_name in ("*", "deploy*", "task?", "[a-z]", "name{a,b}"):
        with pytest.raises(BadParameter):
            validate_command_name(bad_name)


@pytest.mark.os_agnostic
def test_validate_command_name_rejects_path_traversal() -> None:
    """Names containing path separators or traversal sequences are rejected."""
    from click import BadParameter

    from bmk.adapters.cli.commands.custom_cmd import validate_command_name

    for bad_name in ("../etc", "foo/bar", "..\\secret", ".hidden"):
        with pytest.raises(BadParameter):
            validate_command_name(bad_name)


@pytest.mark.os_agnostic
def test_cli_custom_rejects_unsafe_command_name(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI rejects command names with glob metacharacters."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    makescripts = tmp_path / "makescripts"
    makescripts.mkdir()

    result: Result = cli_runner.invoke(cli_mod.cli, ["custom", "../../etc"], obj=production_factory)

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Override directory resolution
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_resolve_override_dir_defaults_to_cwd_makescripts(
    tmp_path: Path,
) -> None:
    """Defaults to cwd/makescripts when bmk.override_dir is empty."""
    from bmk.adapters.cli.commands.custom_cmd import resolve_override_dir

    result = resolve_override_dir(tmp_path, {})

    assert result == tmp_path / "makescripts"


@pytest.mark.os_agnostic
def test_resolve_override_dir_uses_config_value(
    tmp_path: Path,
) -> None:
    """Uses bmk.override_dir from config dict when set."""
    from bmk.adapters.cli.commands.custom_cmd import resolve_override_dir

    custom_dir = tmp_path / "my_scripts"
    bmk_config = {"override_dir": str(custom_dir)}

    result = resolve_override_dir(tmp_path, bmk_config)

    assert result == custom_dir


# ---------------------------------------------------------------------------
# Script discovery
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_custom_scripts_returns_matching_scripts(tmp_path: Path) -> None:
    """Finds scripts matching the command prefix naming convention."""
    from bmk.adapters.cli.commands.custom_cmd import find_custom_scripts

    (tmp_path / "deploy_01_prepare.sh").touch()
    (tmp_path / "deploy_02_upload.sh").touch()
    (tmp_path / "other_01_thing.sh").touch()

    result = find_custom_scripts(tmp_path, "deploy")

    assert len(result) == 2
    assert all("deploy" in p.name for p in result)


@pytest.mark.os_agnostic
def test_find_custom_scripts_returns_empty_for_nonexistent_dir(tmp_path: Path) -> None:
    """Returns empty list when override directory does not exist."""
    from bmk.adapters.cli.commands.custom_cmd import find_custom_scripts

    result = find_custom_scripts(tmp_path / "nonexistent", "deploy")

    assert result == []


@pytest.mark.os_agnostic
def test_find_custom_scripts_returns_empty_when_no_match(tmp_path: Path) -> None:
    """Returns empty list when no scripts match the command name."""
    from bmk.adapters.cli.commands.custom_cmd import find_custom_scripts

    (tmp_path / "build_01_compile.sh").touch()

    result = find_custom_scripts(tmp_path, "deploy")

    assert result == []


# ---------------------------------------------------------------------------
# Error: override directory does not exist
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_custom_error_when_override_dir_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message when override directory does not exist."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    # tmp_path/makescripts does not exist by default

    result: Result = cli_runner.invoke(cli_mod.cli, ["custom", "deploy"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND
    assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# Error: no matching scripts
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_custom_error_when_no_scripts_match(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error message when no scripts match the command name."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    makescripts = tmp_path / "makescripts"
    makescripts.mkdir()
    # Directory exists but no matching scripts

    result: Result = cli_runner.invoke(cli_mod.cli, ["custom", "nonexistent"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND
    assert 'custom command "nonexistent" not found' in result.output


# ---------------------------------------------------------------------------
# Execution with real scripts
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_cli_custom_executes_with_correct_env(
    tmp_path: Path,
    clear_config_cache: None,
) -> None:
    """execute_custom_script sets BMK_COMMAND_PREFIX and BMK_OVERRIDE_DIR."""
    from bmk.adapters.cli.commands.custom_cmd import execute_custom_script

    output_file = tmp_path / "env_output.txt"
    script = tmp_path / "capture_env.sh"
    script.write_text(f'#!/bin/bash\necho "$BMK_COMMAND_PREFIX|$BMK_OVERRIDE_DIR" > "{output_file}"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    override_dir = tmp_path / "overrides"
    override_dir.mkdir()

    execute_custom_script(script, tmp_path, (), command_prefix="deploy", override_dir=override_dir)

    parts = output_file.read_text().strip().split("|")
    assert parts[0] == "deploy"
    assert parts[1] == str(override_dir)


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_cli_custom_forwards_extra_arguments(
    tmp_path: Path,
    clear_config_cache: None,
) -> None:
    """Extra arguments are passed through to the script."""
    from bmk.adapters.cli.commands.custom_cmd import execute_custom_script

    output_file = tmp_path / "args_output.txt"
    script = tmp_path / "capture_args.sh"
    script.write_text(f'#!/bin/bash\necho "$@" > "{output_file}"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    override_dir = tmp_path / "overrides"
    override_dir.mkdir()

    execute_custom_script(
        script,
        tmp_path,
        ("--verbose", "--dry-run"),
        command_prefix="deploy",
        override_dir=override_dir,
    )

    assert output_file.read_text().strip() == "--verbose --dry-run"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_cli_custom_propagates_nonzero_exit_code(
    tmp_path: Path,
    clear_config_cache: None,
) -> None:
    """Non-zero exit code from script is returned."""
    from bmk.adapters.cli.commands.custom_cmd import execute_custom_script

    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/bash\nexit 42\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    override_dir = tmp_path / "overrides"
    override_dir.mkdir()

    result = execute_custom_script(
        script,
        tmp_path,
        (),
        command_prefix="deploy",
        override_dir=override_dir,
    )

    assert result == 42
