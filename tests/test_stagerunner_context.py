"""Tests for building a StageContext (environment + venv pinning)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.context import build_context, resolve_audit_python
from bmk.adapters.stagerunner.model import StageContext
from bmk.domain.enums import ToolOutputFormat


def _ctx(env: dict[str, str]) -> StageContext:
    return StageContext(
        project_dir=Path("/proj"),
        args=(),
        output_format=ToolOutputFormat.JSON,
        python_cmd="/bmk/bin/python",
        package_name="",
        env=env,
        show_warnings=True,
    )


def test_build_context_sets_project_env(tmp_path: Path) -> None:
    ctx = build_context(
        tmp_path, ("--x",), command_prefix="clean", output_format=ToolOutputFormat.JSON, show_warnings=True
    )
    assert ctx.project_dir == tmp_path
    assert ctx.args == ("--x",)
    assert ctx.output_format == "json"
    assert ctx.python_cmd == sys.executable
    assert ctx.env["BMK_PROJECT_DIR"] == str(tmp_path)
    assert ctx.env["BMK_COMMAND_PREFIX"] == "clean"
    assert ctx.env["BMK_OUTPUT_FORMAT"] == "json"
    assert ctx.env["BMK_SHOW_WARNINGS"] == "1"


def test_build_context_prepends_src_to_pythonpath(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    ctx = build_context(tmp_path, (), command_prefix="test", output_format=ToolOutputFormat.JSON, show_warnings=True)
    assert ctx.env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "src")


def test_build_context_no_pythonpath_when_no_src(tmp_path: Path) -> None:
    ctx = build_context(tmp_path, (), command_prefix="test", output_format=ToolOutputFormat.JSON, show_warnings=True)
    # No src/ dir -> PYTHONPATH is only whatever was inherited (not forced to src).
    assert str(tmp_path / "src") not in ctx.env.get("PYTHONPATH", "")


def test_build_context_prepends_tool_bin_to_path(tmp_path: Path) -> None:
    # bmk's own venv bin dir (dir of sys.executable, where ruff/pytest/pyright are
    # installed by `uv tool install --with .`) must be first on PATH so bare-name
    # tool stages resolve on a machine with no global ruff/pytest (the Windows bug:
    # FileNotFoundError / WinError 2).
    ctx = build_context(tmp_path, (), command_prefix="test", output_format=ToolOutputFormat.JSON, show_warnings=True)
    assert ctx.env["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)


def test_build_context_pins_pip_audit_to_bmk_interpreter_when_no_venv(tmp_path: Path) -> None:
    # No project .venv: pin pip-audit at bmk's own interpreter. Its env (a
    # `uv tool install --with .` tool venv) holds bmk plus the project's full
    # dependency tree, so pip-audit audits *that*, not whatever pip-audit sits
    # first on PATH (e.g. an editor's venv full of unrelated packages).
    ctx = build_context(tmp_path, (), command_prefix="clean", output_format=ToolOutputFormat.JSON, show_warnings=False)
    assert "VIRTUAL_ENV" not in ctx.env
    assert ctx.env["PIPAPI_PYTHON_LOCATION"] == sys.executable
    assert ctx.env["BMK_SHOW_WARNINGS"] == "0"


def test_build_context_pins_venv_when_present(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    bindir.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    exe = bindir / ("python.exe" if sys.platform == "win32" else "python")
    exe.write_text("", encoding="utf-8")

    ctx = build_context(tmp_path, (), command_prefix="clean", output_format=ToolOutputFormat.TEXT, show_warnings=True)
    assert ctx.env["VIRTUAL_ENV"] == str(venv)
    assert ctx.env["PIPAPI_PYTHON_LOCATION"] == str(exe)


def test_build_context_pins_the_uv_project_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A tree shared between OSes cannot use one venv path for both: .venv is the
    # Linux venv, so Windows points UV_PROJECT_ENVIRONMENT at .venv-win. The pin
    # must follow it, or tools would resolve against the other OS's venv.
    venv = tmp_path / ".venv-win"
    bindir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    bindir.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    exe = bindir / ("python.exe" if sys.platform == "win32" else "python")
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".venv-win")

    ctx = build_context(tmp_path, (), command_prefix="clean", output_format=ToolOutputFormat.JSON, show_warnings=True)

    assert ctx.env["VIRTUAL_ENV"] == str(venv)
    assert ctx.env["PIPAPI_PYTHON_LOCATION"] == str(exe)


def test_resolve_audit_python_prefers_existing_pinned_interpreter(tmp_path: Path) -> None:
    exe = tmp_path / "python"
    exe.write_text("", encoding="utf-8")
    assert resolve_audit_python(_ctx({"PIPAPI_PYTHON_LOCATION": str(exe)})) == str(exe)


def test_resolve_audit_python_falls_back_when_pinned_interpreter_gone(tmp_path: Path) -> None:
    # A clean removed the pinned .venv interpreter: fall back to bmk's own (python_cmd).
    missing = tmp_path / ".venv" / "bin" / "python"
    assert resolve_audit_python(_ctx({"PIPAPI_PYTHON_LOCATION": str(missing)})) == "/bmk/bin/python"


def test_resolve_audit_python_falls_back_when_unpinned() -> None:
    assert resolve_audit_python(_ctx({})) == "/bmk/bin/python"
