"""Tests for the bump / sync / build / release / run tool argv builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner import tools
from bmk.adapters.stagerunner.model import StageContext
from bmk.domain.enums import BumpPart, ToolOutputFormat

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(tmp_path: Path, *, args: tuple[str, ...] = ()) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=args,
        output_format=ToolOutputFormat.JSON,
        python_cmd="/usr/bin/python3",
        package_name="x",
        env={},
        show_warnings=True,
    )


def test_python_build_argv(tmp_path: Path) -> None:
    assert tools.python_build_argv(_ctx(tmp_path)) == ["/usr/bin/python3", "-m", "build"]


def test_sync_initconf_argv(tmp_path: Path) -> None:
    argv = tools.sync_initconf_argv(_ctx(tmp_path))
    assert argv[0] == "/usr/bin/python3"
    assert argv[1].endswith("_sync_initconf.py")
    assert argv[2:] == ["--project-dir", str(tmp_path)]


def test_bump_argv_includes_kind(tmp_path: Path) -> None:
    argv = tools.bump_argv(BumpPart.MINOR)(_ctx(tmp_path))
    assert argv[1].endswith("_bump_version.py")
    assert argv[2:] == ["minor", "--project-dir", str(tmp_path)]


@pytest.mark.parametrize("part", list(BumpPart))
def test_bump_argv_carries_the_wire_string_not_the_member(tmp_path: Path, part: BumpPart) -> None:
    # A str-Enum member compares equal to its value, so the equality above cannot tell a
    # member that leaked into the argv from the string the subprocess edge needs.
    argv = tools.bump_argv(part)(_ctx(tmp_path))
    assert type(argv[2]) is str
    assert argv[2] == part.value


def test_release_argv_forwards_args(tmp_path: Path) -> None:
    argv = tools.release_argv(_ctx(tmp_path, args=("--remote", "origin")))
    assert argv[1].endswith("_release.py")
    assert argv[2:] == ["--project-dir", str(tmp_path), "--remote", "origin"]


def test_run_project_argv_forwards_args(tmp_path: Path) -> None:
    argv = tools.run_project_argv(_ctx(tmp_path, args=("--help",)))
    assert argv[1].endswith("_run.py")
    assert argv[2:] == ["--help"]
