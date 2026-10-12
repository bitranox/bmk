"""How ``BMK_OUTPUT_FORMAT`` is read: any case of ``text`` / ``json``, and a warning for anything else.

The value used to be matched exactly, so ``TEXT`` - the spelling people type - ran JSON mode in
silence, and so did a typo. Now both known values are accepted in any case, an unset or empty value
is the JSON default without comment, and any other value falls back to JSON with ONE stderr line
naming it.

The end-to-end tests run the real CLI in a subprocess. The observable for "text mode took effect"
is the Makefile-outdated check: in text mode with a stdin that is not a terminal it keeps the
Makefile and prints a note, while JSON mode replaces the Makefile without a word.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from bmk import __init__conf__
from bmk.adapters.cli.commands._shared import resolve_output_format
from bmk.adapters.stagerunner.output_format_env import read_tool_output_format
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from pathlib import Path

_STALE_MAKEFILE = "# BMK MAKEFILE 0.0.1\nSTALE-MAKEFILE-BODY-DO-NOT-KEEP\n"
_WARNING = "[bmk] BMK_OUTPUT_FORMAT="
_TEXT_MODE_NOTE = "run 'bmk install' to update it"

_PREFIX = __init__conf__.LAYEREDCONF_SLUG.upper().replace("-", "_")
_HOMES = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA")
_APP_ROOTS = ("LIB_LAYERED_CONFIG_ETC", "LIB_LAYERED_CONFIG_MAC_APP_ROOT", "LIB_LAYERED_CONFIG_PROGRAMDATA")

# The test's own clock: a run that waited on stdin would never end by itself.
_RUN_DEADLINE_SECONDS = 60.0


# ----------------------------------------------------------------------------- the pure rule


@pytest.mark.os_agnostic
@pytest.mark.parametrize("value", ["text", "TEXT", "Text"])
def test_any_case_of_text_is_text_mode(value: str) -> None:
    assert ToolOutputFormat.from_env(value) is ToolOutputFormat.TEXT


@pytest.mark.os_agnostic
@pytest.mark.parametrize("value", [None, "", "json", "JSON", "Json", "txt", "verbose", " text ", "  "])
def test_everything_else_is_json_mode(value: str | None) -> None:
    assert ToolOutputFormat.from_env(value) is ToolOutputFormat.JSON


@pytest.mark.os_agnostic
@pytest.mark.parametrize("value", [None, "", "text", "TEXT", "json", "JSON"])
def test_unset_empty_and_known_values_are_recognised(value: str | None) -> None:
    assert ToolOutputFormat.is_recognised(value)


@pytest.mark.os_agnostic
# Whitespace is not trimmed: the decision was "any case", and a blank value is not an empty one.
@pytest.mark.parametrize("value", ["txt", "verbose", "1", "texts", " text ", "text\n", "  "])
def test_any_other_value_is_not_recognised(value: str) -> None:
    assert not ToolOutputFormat.is_recognised(value)


# ----------------------------------------------------------------------------- the real CLI


def _run_bmk_info(project: Path, output_format: str | None) -> tuple[int, str]:
    """Run the real `bmk info` in `project`; return its exit code and stderr.

    stdin is an open pipe nobody writes to: not a terminal on any OS. DEVNULL would not do -
    on Windows `NUL` reports isatty() True, which sends the Makefile check down the prompt path.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith((_PREFIX, "BMK_", "LOG_", "LIB_LAYERED_CONFIG"))}
    env.update(dict.fromkeys(_HOMES, str(project)))
    env.update(dict.fromkeys(_APP_ROOTS, str(project)))
    if output_format is not None:
        env["BMK_OUTPUT_FORMAT"] = output_format
    err = project / "stderr.txt"
    read_end, write_end = os.pipe()
    try:
        with err.open("wb") as err_file:
            proc = subprocess.Popen(
                [sys.executable, "-m", "bmk", "info"],
                cwd=project,
                env=env,
                stdin=read_end,
                stdout=subprocess.DEVNULL,
                stderr=err_file,
            )
            try:
                returncode = proc.wait(timeout=_RUN_DEADLINE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                pytest.fail(f"bmk was still running after {_RUN_DEADLINE_SECONDS}s: it waited on stdin")
    finally:
        os.close(read_end)
        os.close(write_end)
    return returncode, err.read_text(encoding="utf-8", errors="replace")


@pytest.mark.os_agnostic
def test_upper_case_text_selects_text_mode_without_a_warning(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(_STALE_MAKEFILE, encoding="utf-8")

    returncode, stderr = _run_bmk_info(tmp_path, "TEXT")

    assert returncode == 0
    assert _TEXT_MODE_NOTE in stderr
    assert (tmp_path / "Makefile").read_text(encoding="utf-8") == _STALE_MAKEFILE
    assert _WARNING not in stderr


@pytest.mark.os_agnostic
def test_an_unknown_value_warns_once_and_runs_json_mode(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(_STALE_MAKEFILE, encoding="utf-8")

    returncode, stderr = _run_bmk_info(tmp_path, "txt")

    assert returncode == 0
    assert stderr.count(_WARNING) == 1, stderr
    assert "'txt'" in stderr
    assert _TEXT_MODE_NOTE not in stderr
    assert (tmp_path / "Makefile").read_text(encoding="utf-8") != _STALE_MAKEFILE


@pytest.mark.os_agnostic
@pytest.mark.parametrize("value", [None, "", "json", "text"])
def test_unset_empty_and_lower_case_values_never_warn(tmp_path: Path, value: str | None) -> None:
    returncode, stderr = _run_bmk_info(tmp_path, value)

    assert returncode == 0
    assert _WARNING not in stderr


@pytest.mark.os_agnostic
def test_reading_the_variable_twice_in_one_process_warns_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One command reads the variable at several call sites; the reader must not repeat itself."""
    # A value no other test uses, so whatever an earlier test warned about cannot hide this one.
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "warn-once-probe")

    first = read_tool_output_format()
    second = read_tool_output_format()

    assert first is second is ToolOutputFormat.JSON
    assert capsys.readouterr().err.count(_WARNING) == 1


@pytest.mark.os_agnostic
def test_the_command_path_names_an_unknown_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`bmk test` and the other pipeline commands decide their mode in resolve_output_format."""
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "command-path-probe")

    assert resolve_output_format(human=False) is ToolOutputFormat.JSON
    assert capsys.readouterr().err.count(_WARNING) == 1


@pytest.mark.os_agnostic
def test_the_command_path_reads_upper_case_text_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "TEXT")

    assert resolve_output_format(human=False) is ToolOutputFormat.TEXT
