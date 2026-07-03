"""Integration: run a real registry tool stage through the engine (offline, fast)."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bmk.adapters.stagerunner.engine import run_pipeline
from bmk.adapters.stagerunner.model import Stage, StageContext
from bmk.adapters.stagerunner.registry import PIPELINES
from bmk.domain.enums import ToolOutputFormat


def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=ToolOutputFormat.TEXT,
        python_cmd=sys.executable,
        package_name="x",
        env=dict(os.environ),
        show_warnings=True,
    )


def _ruff_format_check_stage() -> Stage:
    return next(s for s in PIPELINES["test"] if s.name == "ruff_format_check")


@pytest.mark.os_agnostic
def test_ruff_format_check_passes_on_formatted_file(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    rc = run_pipeline([_ruff_format_check_stage()], _ctx(tmp_path), out=io.StringIO())
    assert rc == 0


@pytest.mark.os_agnostic
def test_ruff_format_check_fails_on_unformatted_file(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("x=1\n", encoding="utf-8")  # ruff would reformat -> check fails
    rc = run_pipeline([_ruff_format_check_stage()], _ctx(tmp_path), out=io.StringIO())
    assert rc != 0


@pytest.mark.local_only  # spawns real uv + pip-audit, needs network; excluded from CI (run via test-slow)
@pytest.mark.os_agnostic
def test_pip_audit_self_heals_when_pinned_venv_removed(tmp_path: Path) -> None:
    """The .venv-vs-clean regression guard: with PIPAPI_PYTHON_LOCATION pinned at a
    project .venv that a clean already removed, the pip_audit stage must fall back to
    ``python_cmd``, bootstrap a current pip into it, and audit cleanly - never crash
    with FileNotFoundError. A minimal dependency-free venv stands in for bmk's own
    interpreter (the fallback target) so the audit is deterministically clean.
    """
    clean_venv = tmp_path / "clean-venv"
    subprocess.run(["uv", "venv", str(clean_venv)], check=True, capture_output=True)
    clean_python = clean_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\nversion = '0'\n", encoding="utf-8")

    env = dict(os.environ)
    env["PIPAPI_PYTHON_LOCATION"] = str(tmp_path / ".venv" / "bin" / "python")  # a clean removed this
    ctx = StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=ToolOutputFormat.TEXT,
        python_cmd=str(clean_python),
        package_name="x",
        env=env,
        show_warnings=False,
    )
    pip_audit = next(s for s in PIPELINES["test"] if s.name == "pip_audit")
    out = io.StringIO()
    rc = run_pipeline([pip_audit], ctx, out=out)
    assert "FileNotFoundError" not in out.getvalue()  # did not crash on the vanished pinned interpreter
    assert rc == 0  # resolved to the clean venv, bootstrapped pip, audited cleanly
