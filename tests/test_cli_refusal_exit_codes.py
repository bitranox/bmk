"""Deliberate refusals exit with a fixed ``ExitCode`` and one readable line, never a crash report.

A refusal that reaches ``main()``'s catch-all is mapped by ``lib_cli_exit_tools`` to the OS's
errno for the exception type, so a refused overlay exited 22 on POSIX and 87 on Windows, and
printed a ``ValueError:`` line a user reads as a crash. These tests drive the real ``main()``
entry point (or the stage engine, for an in-stage refusal) with the bad input on disk, and pin
both the exit code and the absence of traceback and ``SystemExit`` text.
"""

from __future__ import annotations

import dataclasses
import io
import os
import sys
from typing import TYPE_CHECKING, Any

import pytest
from lib_layered_config import Config

from bmk.adapters.cli.exit_codes import ExitCode
from bmk.adapters.cli.main import main
from bmk.adapters.stagerunner import git_ops
from bmk.adapters.stagerunner.actions import HelperAction
from bmk.adapters.stagerunner.engine import run_stage
from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.composition import AppServices, build_testing
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_PROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\n'
# Latin-1 e-acute: valid in a cp1252 editor, invalid as UTF-8, so a decoder refuses the file.
_NOT_UTF8 = b'[project]\nname = "d\xe9mo"\nversion = "0.1.0"\n'


def _services() -> Callable[[], AppServices]:
    config = Config({}, {})

    def get_config(**_kwargs: Any) -> Config:
        return config

    def build() -> AppServices:
        return dataclasses.replace(build_testing(), get_config=get_config)

    return build


def _assert_no_crash_text(err: str) -> None:
    assert "Traceback" not in err
    assert "SystemExit" not in err
    assert "ValueError" not in err
    assert "UnicodeDecodeError" not in err


def _stages_toml(project: Path, content: bytes) -> None:
    (project / "bmk_makescripts").mkdir()
    (project / "bmk_makescripts" / "stages.toml").write_bytes(content)


def _run_custom_deploy(project: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.chdir(project)
    return main(["custom", "deploy"], services_factory=_services())


# --- A1: an overlay section that is not a table ------------------------------


@pytest.mark.os_agnostic
def test_a_pyproject_overlay_section_that_is_not_a_table_exits_78(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(_PROJECT + "\n[tool.bmk.pipelines]\ndeploy = 3\n", encoding="utf-8")

    exit_code = _run_custom_deploy(tmp_path, monkeypatch)

    err = capsys.readouterr().err
    assert exit_code == ExitCode.CONFIG_ERROR
    assert "Error: invalid [tool.bmk.pipelines.deploy] overlay:\n  must be a table" in err
    _assert_no_crash_text(err)


# --- A3: stages.toml `pipelines` that is not a table --------------------------


@pytest.mark.os_agnostic
def test_a_stages_toml_pipelines_key_that_is_not_a_table_exits_78(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(_PROJECT, encoding="utf-8")
    _stages_toml(tmp_path, b"pipelines = 3\n")

    exit_code = _run_custom_deploy(tmp_path, monkeypatch)

    err = capsys.readouterr().err
    assert exit_code == ExitCode.CONFIG_ERROR
    assert "Error: invalid bmk_makescripts/stages.toml [pipelines]:\n  must be a table" in err
    _assert_no_crash_text(err)


# --- A4: a file the overlay loader cannot parse --------------------------------


@pytest.mark.os_agnostic
def test_a_pyproject_toml_syntax_error_exits_78_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\nname = 1\n", encoding="utf-8")

    exit_code = _run_custom_deploy(tmp_path, monkeypatch)

    err = capsys.readouterr().err
    assert exit_code == ExitCode.CONFIG_ERROR
    assert "Error: cannot read pyproject.toml:" in err
    _assert_no_crash_text(err)


@pytest.mark.os_agnostic
def test_a_non_utf8_pyproject_toml_exits_78_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_bytes(_NOT_UTF8)

    exit_code = _run_custom_deploy(tmp_path, monkeypatch)

    err = capsys.readouterr().err
    assert exit_code == ExitCode.CONFIG_ERROR
    assert "Error: cannot read pyproject.toml:" in err
    _assert_no_crash_text(err)


@pytest.mark.os_agnostic
def test_a_non_utf8_stages_toml_exits_78_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(_PROJECT, encoding="utf-8")
    _stages_toml(tmp_path, b'[pipelines.deploy]\nremove = ["l\xe9nt"]\n')

    exit_code = _run_custom_deploy(tmp_path, monkeypatch)

    err = capsys.readouterr().err
    assert exit_code == ExitCode.CONFIG_ERROR
    assert "Error: cannot read bmk_makescripts/stages.toml:" in err
    _assert_no_crash_text(err)


# --- the traceback flag still shows the full trace -----------------------------


@pytest.mark.os_agnostic
def test_a_refusal_shows_its_traceback_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text(_PROJECT + "\n[tool.bmk.pipelines]\ndeploy = 3\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["--traceback", "custom", "deploy"], services_factory=_services())

    err = capsys.readouterr().err
    assert exit_code == ExitCode.CONFIG_ERROR
    assert "Traceback" in err
    assert "must be a table" in err


# --- A6 / A7: a Makefile that is not UTF-8 text ---------------------------------

_LATIN1_MAKEFILE = b"# Gr\xfc\xdfe\nall:\n\techo hi\n"


@pytest.mark.os_agnostic
def test_a_non_utf8_makefile_does_not_abort_an_unrelated_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The outdated-Makefile check runs before every subcommand and is best-effort."""
    (tmp_path / "Makefile").write_bytes(_LATIN1_MAKEFILE)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["info"], services_factory=_services())

    err = capsys.readouterr().err
    assert exit_code == ExitCode.SUCCESS
    _assert_no_crash_text(err)
    assert (tmp_path / "Makefile").read_bytes() == _LATIN1_MAKEFILE


@pytest.mark.os_agnostic
def test_install_beside_a_non_utf8_makefile_refuses_and_leaves_it_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "Makefile").write_bytes(_LATIN1_MAKEFILE)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["install"], services_factory=_services())

    err = capsys.readouterr().err
    assert exit_code == ExitCode.GENERAL_ERROR
    assert "Makefile exists but is not UTF-8 text" in err
    _assert_no_crash_text(err)
    assert (tmp_path / "Makefile").read_bytes() == _LATIN1_MAKEFILE


# --- C: an empty interactive commit message -------------------------------------


class _TerminalInput(io.StringIO):
    """Stands in for a person at a terminal: ``isatty`` is the only question commit asks of stdin."""

    def isatty(self) -> bool:
        return True


@pytest.mark.os_agnostic
def test_an_empty_interactive_commit_message_is_refused_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # sys.stdin is the process's terminal, an edge no parameter reaches; the person presses Enter.
    monkeypatch.setattr(sys, "stdin", _TerminalInput("\n"))
    env = {key: value for key, value in os.environ.items() if key != "BMK_COMMIT_MESSAGE"}
    ctx = StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=ToolOutputFormat.TEXT,
        python_cmd=sys.executable,
        package_name="x",
        env=env,
        show_warnings=True,
    )
    out = io.StringIO()

    result = run_stage(Stage("commit", 10, HelperAction(git_ops.commit), interactive=True), ctx, out)

    err = capsys.readouterr().err
    assert result.returncode == 1
    assert "Error: Commit message cannot be empty" in err
    assert "Traceback" not in out.getvalue() + result.output
    assert "raised an unexpected error" not in out.getvalue() + result.output
