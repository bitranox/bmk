"""Tests for building a StageContext (environment + venv pinning)."""

from __future__ import annotations

import sys
from pathlib import Path

from bmk.adapters.stagerunner.context import build_context


def test_build_context_sets_project_env(tmp_path: Path) -> None:
    ctx = build_context(tmp_path, ("--x",), command_prefix="clean", output_format="json", show_warnings=True)
    assert ctx.project_dir == tmp_path
    assert ctx.args == ("--x",)
    assert ctx.output_format == "json"
    assert ctx.python_cmd == sys.executable
    assert ctx.env["BMK_PROJECT_DIR"] == str(tmp_path)
    assert ctx.env["BMK_COMMAND_PREFIX"] == "clean"
    assert ctx.env["BMK_OUTPUT_FORMAT"] == "json"
    assert ctx.env["BMK_SHOW_WARNINGS"] == "1"


def test_build_context_omits_virtualenv_when_no_venv(tmp_path: Path) -> None:
    ctx = build_context(tmp_path, (), command_prefix="clean", output_format="json", show_warnings=False)
    assert "VIRTUAL_ENV" not in ctx.env
    assert "PIPAPI_PYTHON_LOCATION" not in ctx.env
    assert ctx.env["BMK_SHOW_WARNINGS"] == "0"


def test_build_context_pins_venv_when_present(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    bindir.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    exe = bindir / ("python.exe" if sys.platform == "win32" else "python")
    exe.write_text("", encoding="utf-8")

    ctx = build_context(tmp_path, (), command_prefix="clean", output_format="text", show_warnings=True)
    assert ctx.env["VIRTUAL_ENV"] == str(venv)
    assert ctx.env["PIPAPI_PYTHON_LOCATION"] == str(exe)
