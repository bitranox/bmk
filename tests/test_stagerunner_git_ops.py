"""Tests for git commit/push stage logic."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner import git_ops
from bmk.adapters.stagerunner.model import StageContext
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(tmp_path: Path, *, args: tuple[str, ...] = (), env: dict[str, str] | None = None) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=args,
        output_format=ToolOutputFormat.TEXT,
        python_cmd=sys.executable,
        package_name="x",
        env=env if env is not None else dict(os.environ),
        show_warnings=True,
    )


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)


# --- pure helpers -----------------------------------------------------------


def test_resolve_message_from_args() -> None:
    assert git_ops.resolve_message(("fix", "bug"), env={}, isatty=False) == "fix bug"


def test_resolve_message_from_env() -> None:
    assert git_ops.resolve_message((), env={"BMK_COMMIT_MESSAGE": "envmsg"}, isatty=False) == "envmsg"


def test_resolve_message_default_when_no_tty() -> None:
    assert git_ops.resolve_message((), env={}, isatty=False) == "chores"


def test_resolve_message_prompts_when_tty() -> None:
    assert git_ops.resolve_message((), env={}, isatty=True, prompt=lambda _p: "typed") == "typed"


def test_resolve_message_empty_prompt_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        git_ops.resolve_message((), env={}, isatty=True, prompt=lambda _p: "   ")


def test_timestamp_prefix() -> None:
    assert git_ops.timestamp_prefix(datetime(2026, 7, 2, 10, 30, 0)) == "2026-07-02 10:30:00"


def test_detect_sensitive() -> None:
    names = [".env", "ok.py", "id_rsa", "x.key", "README", "app/credentials.txt"]
    assert git_ops.detect_sensitive(names) == [".env", "id_rsa", "x.key", "app/credentials.txt"]


# --- push argv --------------------------------------------------------------


def test_push_argv_uses_env_remote_and_branch(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, env={"BMK_GIT_REMOTE": "upstream", "BMK_GIT_BRANCH": "dev"})
    assert git_ops.push_argv(ctx) == ["git", "push", "-u", "upstream", "dev"]


@pytest.mark.os_posix
def test_push_argv_resolves_branch_from_repo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    argv = git_ops.push_argv(_ctx(tmp_path, env={}))
    assert argv[:4] == ["git", "push", "-u", "origin"]
    assert argv[4] in {"master", "main"}


# --- commit -----------------------------------------------------------------


@pytest.mark.os_posix
def test_commit_creates_timestamped_commit(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    rc = git_ops.commit(_ctx(tmp_path, args=("initial", "commit")))
    assert rc == 0
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert subject.endswith("initial commit")
    assert " - " in subject  # timestamp prefix


@pytest.mark.os_posix
def test_commit_allows_empty_when_nothing_staged(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    # Nothing new staged -> empty commit still succeeds.
    rc = git_ops.commit(dataclasses.replace(_ctx(tmp_path, args=("empty",)), env={"BMK_COMMIT_MESSAGE": ""}))
    assert rc == 0
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert count == "2"
