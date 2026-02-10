"""Integration tests for bmk config propagation through execute_script.

Tests config loading (defaultconfig TOML → lib_layered_config → get_config())
and execute_script() → subprocess environment variable propagation.
execute_script now accepts override_dir/package_name as explicit parameters,
so env var propagation tests pass values directly.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from bmk.adapters.cli.commands.test_cmd import execute_script
from bmk.adapters.config.loader import get_config

# ---------------------------------------------------------------------------
# 10-bmk.toml defaults are loaded by get_config()
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_default_config_contains_bmk_section(clear_config_cache: None) -> None:
    """Default config includes [bmk] section from 10-bmk.toml."""
    config = get_config()
    bmk = config.as_dict().get("bmk", {})

    assert "override_dir" in bmk
    assert "package_name" in bmk


@pytest.mark.os_agnostic
def test_default_override_dir_is_empty_string(clear_config_cache: None) -> None:
    """Default override_dir is empty string (stagerunner uses its own default)."""
    config = get_config()
    bmk = config.as_dict()["bmk"]

    assert bmk["override_dir"] == ""


@pytest.mark.os_agnostic
def test_default_package_name_is_empty_string(clear_config_cache: None) -> None:
    """Default package_name is empty string (auto-derived from pyproject.toml)."""
    config = get_config()
    bmk = config.as_dict()["bmk"]

    assert bmk["package_name"] == ""


# ---------------------------------------------------------------------------
# Environment variables flow through lib_layered_config into [bmk] section
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_override_dir_from_env_var(
    clear_config_cache: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BMK___BMK__OVERRIDE_DIR env var flows into config bmk.override_dir."""
    monkeypatch.setenv("BMK___BMK__OVERRIDE_DIR", "/tmp/custom-overrides")

    config = get_config()
    bmk = config.as_dict()["bmk"]

    assert bmk["override_dir"] == "/tmp/custom-overrides"


@pytest.mark.os_agnostic
def test_package_name_from_env_var(
    clear_config_cache: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BMK___BMK__PACKAGE_NAME env var flows into config bmk.package_name."""
    monkeypatch.setenv("BMK___BMK__PACKAGE_NAME", "my_custom_pkg")

    config = get_config()
    bmk = config.as_dict()["bmk"]

    assert bmk["package_name"] == "my_custom_pkg"


@pytest.mark.os_agnostic
def test_both_bmk_env_vars_set(
    clear_config_cache: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both bmk env vars flow into the config simultaneously."""
    monkeypatch.setenv("BMK___BMK__OVERRIDE_DIR", "/opt/overrides")
    monkeypatch.setenv("BMK___BMK__PACKAGE_NAME", "special_pkg")

    config = get_config()
    bmk = config.as_dict()["bmk"]

    assert bmk["override_dir"] == "/opt/overrides"
    assert bmk["package_name"] == "special_pkg"


# ---------------------------------------------------------------------------
# execute_script propagates config values as subprocess env vars
# ---------------------------------------------------------------------------


def _make_env_capture_script(tmp_path: Path, output_file: Path) -> Path:
    """Create a bash script that writes selected env vars to a file."""
    script = tmp_path / "capture_env.sh"
    script.write_text(
        "#!/bin/bash\n"
        "{\n"
        f'  echo "OVERRIDE_DIR=${{BMK_OVERRIDE_DIR:-__UNSET__}}"\n'
        f'  echo "PACKAGE_NAME=${{BMK_PACKAGE_NAME:-__UNSET__}}"\n'
        f'  echo "PROJECT_DIR=${{BMK_PROJECT_DIR:-__UNSET__}}"\n'
        f'  echo "COMMAND_PREFIX=${{BMK_COMMAND_PREFIX:-__UNSET__}}"\n'
        f'}} > "{output_file}"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _parse_captured_env(output_file: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from the env capture script output."""
    result: dict[str, str] = {}
    for line in output_file.read_text().strip().splitlines():
        key, _, value = line.partition("=")
        result[key] = value
    return result


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_execute_script_omits_override_dir_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BMK_OVERRIDE_DIR is not set in subprocess when override_dir is empty."""
    monkeypatch.delenv("BMK_OVERRIDE_DIR", raising=False)

    output_file = tmp_path / "env_output.txt"
    script = _make_env_capture_script(tmp_path, output_file)

    execute_script(script, tmp_path, (), override_dir="")

    env = _parse_captured_env(output_file)
    assert env["OVERRIDE_DIR"] == "__UNSET__"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_execute_script_omits_package_name_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BMK_PACKAGE_NAME is not set in subprocess when package_name is empty."""
    monkeypatch.delenv("BMK_PACKAGE_NAME", raising=False)

    output_file = tmp_path / "env_output.txt"
    script = _make_env_capture_script(tmp_path, output_file)

    execute_script(script, tmp_path, (), package_name="")

    env = _parse_captured_env(output_file)
    assert env["PACKAGE_NAME"] == "__UNSET__"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_execute_script_sets_override_dir(
    tmp_path: Path,
) -> None:
    """BMK_OVERRIDE_DIR is set in subprocess when override_dir is non-empty."""
    output_file = tmp_path / "env_output.txt"
    script = _make_env_capture_script(tmp_path, output_file)

    execute_script(script, tmp_path, (), override_dir="/tmp/my-overrides")

    env = _parse_captured_env(output_file)
    assert env["OVERRIDE_DIR"] == "/tmp/my-overrides"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_execute_script_sets_package_name(
    tmp_path: Path,
) -> None:
    """BMK_PACKAGE_NAME is set in subprocess when package_name is non-empty."""
    output_file = tmp_path / "env_output.txt"
    script = _make_env_capture_script(tmp_path, output_file)

    execute_script(script, tmp_path, (), package_name="custom_package")

    env = _parse_captured_env(output_file)
    assert env["PACKAGE_NAME"] == "custom_package"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_execute_script_sets_both_config_vars(
    tmp_path: Path,
) -> None:
    """Both BMK_OVERRIDE_DIR and BMK_PACKAGE_NAME are set when both values are non-empty."""
    output_file = tmp_path / "env_output.txt"
    script = _make_env_capture_script(tmp_path, output_file)

    execute_script(
        script,
        tmp_path,
        (),
        override_dir="/opt/stages",
        package_name="my_app",
    )

    env = _parse_captured_env(output_file)
    assert env["OVERRIDE_DIR"] == "/opt/stages"
    assert env["PACKAGE_NAME"] == "my_app"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_execute_script_always_sets_project_dir_and_command_prefix(
    tmp_path: Path,
) -> None:
    """BMK_PROJECT_DIR and BMK_COMMAND_PREFIX are always set regardless of bmk config."""
    output_file = tmp_path / "env_output.txt"
    script = _make_env_capture_script(tmp_path, output_file)

    execute_script(script, tmp_path, (), command_prefix="clean")

    env = _parse_captured_env(output_file)
    assert env["PROJECT_DIR"] == str(tmp_path)
    assert env["COMMAND_PREFIX"] == "clean"


@pytest.mark.skipif(sys.platform == "win32", reason="Requires bash")
def test_execute_script_override_dir_with_spaces(
    tmp_path: Path,
) -> None:
    """Paths with spaces are preserved correctly through to subprocess."""
    path_with_spaces = "/tmp/my project/override scripts"

    output_file = tmp_path / "env_output.txt"
    script = _make_env_capture_script(tmp_path, output_file)

    execute_script(script, tmp_path, (), override_dir=path_with_spaces)

    env = _parse_captured_env(output_file)
    assert env["OVERRIDE_DIR"] == path_with_spaces
