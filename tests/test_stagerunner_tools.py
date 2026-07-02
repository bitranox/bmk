"""Tests for tool argv builders (JSON vs text flags, helper-script invocation)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from bmk.adapters.stagerunner import tools
from bmk.adapters.stagerunner.model import StageContext
from bmk.domain.enums import ToolOutputFormat


def _ctx(
    tmp_path: Path, output_format: ToolOutputFormat = ToolOutputFormat.JSON, *, args: tuple[str, ...] = ()
) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=args,
        output_format=output_format,
        python_cmd="/usr/bin/python3",
        package_name="",
        env={},
        show_warnings=True,
    )


def test_ruff_lint_argv_json_flag(tmp_path: Path) -> None:
    assert tools.ruff_lint_argv(_ctx(tmp_path, ToolOutputFormat.JSON)) == [
        "ruff",
        "check",
        "--output-format",
        "json",
        ".",
    ]
    assert tools.ruff_lint_argv(_ctx(tmp_path, ToolOutputFormat.TEXT)) == ["ruff", "check", "."]


def test_ruff_format_argvs(tmp_path: Path) -> None:
    assert tools.ruff_format_apply_argv(_ctx(tmp_path)) == ["ruff", "format", "."]
    assert tools.ruff_fix_apply_argv(_ctx(tmp_path)) == ["ruff", "check", "--fix", "."]
    assert tools.ruff_format_check_argv(_ctx(tmp_path)) == ["ruff", "format", "--check", "."]


def test_bandit_argv_uses_package_name_and_format(tmp_path: Path) -> None:
    ctx_json = dataclasses.replace(_ctx(tmp_path, ToolOutputFormat.JSON), package_name="acme")
    assert tools.bandit_argv(ctx_json) == ["bandit", "-r", "-c", "pyproject.toml", "-f", "json", "src/acme"]
    ctx_text = dataclasses.replace(_ctx(tmp_path, ToolOutputFormat.TEXT), package_name="acme")
    assert tools.bandit_argv(ctx_text) == ["bandit", "-r", "-c", "pyproject.toml", "-q", "src/acme"]


def test_bandit_argv_derives_package_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "der-ived"\n', encoding="utf-8")
    assert tools.bandit_argv(_ctx(tmp_path, ToolOutputFormat.TEXT))[-1] == "src/der_ived"


def test_pyright_argv_json_flag(tmp_path: Path) -> None:
    assert tools.pyright_argv(_ctx(tmp_path, ToolOutputFormat.JSON)) == ["pyright", "--outputjson"]
    assert tools.pyright_argv(_ctx(tmp_path, ToolOutputFormat.TEXT)) == ["pyright"]


def test_lint_imports_argv(tmp_path: Path) -> None:
    assert tools.lint_imports_argv(_ctx(tmp_path)) == ["lint-imports"]


def test_pip_audit_argv_with_ignores_and_json(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.pip-audit]\nignore-vulns = ["GHSA-x"]\n', encoding="utf-8")
    assert tools.pip_audit_argv(_ctx(tmp_path, ToolOutputFormat.JSON)) == [
        "pip-audit",
        "--ignore-vuln=GHSA-x",
        "-f",
        "json",
    ]
    assert tools.pip_audit_argv(_ctx(tmp_path, ToolOutputFormat.TEXT)) == ["pip-audit", "--ignore-vuln=GHSA-x"]


def test_pytest_cov_argv(tmp_path: Path) -> None:
    argv = tools.pytest_cov_argv(_ctx(tmp_path, ToolOutputFormat.JSON))
    assert argv[0] == "/usr/bin/python3"
    assert argv[1].endswith("_coverage.py")
    assert argv[2:] == ["--run", "--project-dir", str(tmp_path), "--output-format", "json"]


def test_coverage_run_argv_no_json_flag(tmp_path: Path) -> None:
    argv = tools.coverage_run_argv(_ctx(tmp_path, ToolOutputFormat.JSON))
    assert argv[1].endswith("_coverage.py")
    assert argv[2:] == ["--run", "--project-dir", str(tmp_path)]


def test_shellcheck_and_pssa_forward_args(tmp_path: Path) -> None:
    sc = tools.shellcheck_argv(_ctx(tmp_path, ToolOutputFormat.JSON, args=("--extra",)))
    assert sc[1].endswith("_shellcheck.py")
    assert "--project-dir" in sc and "--output-format" in sc and sc[-1] == "--extra"
    pssa = tools.psscriptanalyzer_argv(_ctx(tmp_path, ToolOutputFormat.TEXT, args=("--x",)))
    assert pssa[1].endswith("_psscriptanalyzer.py")
    assert "--output-format" not in pssa and pssa[-1] == "--x"


def test_integration_pytest_argv(tmp_path: Path) -> None:
    assert tools.integration_pytest_argv(_ctx(tmp_path, args=("-k", "smoke"))) == [
        "pytest",
        "-m",
        "integration",
        "--tb=short",
        "-q",
        "-k",
        "smoke",
    ]
