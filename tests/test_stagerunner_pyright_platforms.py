"""The pyright stage type-checks every OS family the project declares in ``[tool.ci].os``.

pyright checks ONE platform per run, and with no ``--pythonplatform`` that is the host. So a
Windows-only stub difference (``os.geteuid``, ``signal.SIGHUP``) passed ``make test`` on Linux and
reddened every windows-latest CI cell - three times before the gate learned to ask for each
declared platform. The CI workflow builds its OS matrix from the same key, so the gate and the
matrix agree on which platforms the project supports.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from bmk.adapters.stagerunner import tools
from bmk.adapters.stagerunner.actions import ToolRunsAction
from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.adapters.stagerunner.project import pyright_platforms
from bmk.adapters.stagerunner.registry import PIPELINES
from bmk.domain.enums import PyrightPlatform, ToolOutputFormat


def _project(tmp_path: Path, ci_os: str | None) -> Path:
    body = '[project]\nname = "demo"\nversion = "0.1.0"\n'
    if ci_os is not None:
        body += f"\n[tool.ci]\nos = {ci_os}\n"
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    return tmp_path


def _ctx(project: Path, output_format: ToolOutputFormat = ToolOutputFormat.TEXT) -> StageContext:
    # The test interpreter's own bin dir carries pyright (a runtime dependency of bmk).
    path = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    return StageContext(
        project_dir=project,
        args=(),
        output_format=output_format,
        python_cmd=sys.executable,
        package_name="",
        env={**os.environ, "PATH": path},
        show_warnings=True,
    )


# --- which platforms a project declares --------------------------------------


@pytest.mark.os_agnostic
def test_each_declared_runner_family_becomes_one_pyright_platform(tmp_path: Path) -> None:
    project = _project(tmp_path, '["ubuntu-latest", "windows-2022", "macos-14"]')

    assert pyright_platforms(project / "pyproject.toml") == (
        PyrightPlatform.LINUX,
        PyrightPlatform.WINDOWS,
        PyrightPlatform.DARWIN,
    )


@pytest.mark.os_agnostic
def test_two_runners_of_one_family_are_checked_once_in_first_seen_order(tmp_path: Path) -> None:
    project = _project(tmp_path, '["windows-latest", "ubuntu-22.04", "windows-2022"]')

    assert pyright_platforms(project / "pyproject.toml") == (PyrightPlatform.WINDOWS, PyrightPlatform.LINUX)


@pytest.mark.os_agnostic
def test_a_runner_label_naming_no_os_family_is_skipped(tmp_path: Path) -> None:
    project = _project(tmp_path, '["self-hosted", "UBUNTU-24.04"]')

    assert pyright_platforms(project / "pyproject.toml") == (PyrightPlatform.LINUX,)


@pytest.mark.os_agnostic
@pytest.mark.parametrize("ci_os", [None, "[]", '"ubuntu-latest"', "[1, true]"])
def test_no_usable_os_list_declares_no_platform(tmp_path: Path, ci_os: str | None) -> None:
    project = _project(tmp_path, ci_os)

    assert pyright_platforms(project / "pyproject.toml") == ()


@pytest.mark.os_agnostic
def test_a_missing_pyproject_declares_no_platform(tmp_path: Path) -> None:
    assert pyright_platforms(tmp_path / "pyproject.toml") == ()


# --- the argv each platform gets ---------------------------------------------


@pytest.mark.os_agnostic
def test_without_declared_platforms_pyright_runs_once_for_the_host(tmp_path: Path) -> None:
    ctx = _ctx(_project(tmp_path, None), ToolOutputFormat.JSON)

    assert tools.pyright_argvs(ctx) == [tools.pyright_argv(ctx)]


@pytest.mark.os_agnostic
def test_each_declared_platform_gets_its_own_pyright_argv(tmp_path: Path) -> None:
    ctx = _ctx(_project(tmp_path, '["ubuntu-latest", "windows-latest"]'), ToolOutputFormat.JSON)
    base = tools.pyright_argv(ctx)

    assert tools.pyright_argvs(ctx) == [
        [*base, "--pythonplatform", "Linux"],
        [*base, "--pythonplatform", "Windows"],
    ]


# --- every run executes, the first failure decides the stage -----------------


@pytest.mark.os_agnostic
def test_a_failing_run_does_not_stop_the_runs_after_it(tmp_path: Path) -> None:
    def argvs(_ctx: StageContext) -> list[list[str]]:
        return [
            [sys.executable, "-c", "raise SystemExit(3)"],
            [sys.executable, "-c", "print('second run reached'); raise SystemExit(5)"],
        ]

    sink = CapturingSink()
    rc = ToolRunsAction(argvs)(_ctx(_project(tmp_path, None)), sink)

    assert rc == 3, "the first failure's code decides the stage"
    assert "second run reached" in sink.getvalue()
    assert sink.getvalue().count("$ ") == 2, "each run is headed by its argv"


# --- the real stage, real pyright --------------------------------------------

# Valid on Linux and macOS; Windows' stubs have no os.geteuid, so pyright reports it there only.
_POSIX_ONLY_CALL = "import os\n\nprint(os.geteuid())\n"


def _pyright_stage_output(project: Path) -> tuple[int, str]:
    (project / "demo.py").write_text(_POSIX_ONLY_CALL, encoding="utf-8")
    (stage,) = [s for s in PIPELINES["test"] if s.name == "pyright"]
    sink = CapturingSink()
    rc = stage.action(_ctx(project), sink)
    return rc, sink.getvalue()


@pytest.mark.os_agnostic
def test_the_pyright_stage_fails_on_an_error_only_a_declared_windows_platform_sees(tmp_path: Path) -> None:
    rc, out = _pyright_stage_output(_project(tmp_path, '["ubuntu-latest", "windows-latest"]'))

    assert rc != 0, out
    assert "--pythonplatform Windows" in out, out
    assert "geteuid" in out, out


@pytest.mark.os_agnostic
def test_the_pyright_stage_passes_when_windows_is_not_declared(tmp_path: Path) -> None:
    rc, out = _pyright_stage_output(_project(tmp_path, '["ubuntu-latest", "macos-latest"]'))

    assert rc == 0, out
