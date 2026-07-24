"""Coverage for _release's git/gh subprocess wrappers and main() delegation."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from bmk.adapters.stagerunner.helpers import _release

if TYPE_CHECKING:
    from pathlib import Path


class _FakeRun:
    """A typed stand-in for subprocess.run that records argv and returns a fixed result."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self._returncode = returncode
        self._stdout = stdout
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self._returncode, stdout=self._stdout, stderr="")


@pytest.mark.os_agnostic
def test_git_branch_returns_stripped_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_release.subprocess, "run", _FakeRun(0, "main\n"))
    assert _release._git_branch() == "main"


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("rc", "expected"), [(0, True), (1, False)])
def test_git_tag_exists(monkeypatch: pytest.MonkeyPatch, rc: int, expected: bool) -> None:
    monkeypatch.setattr(_release.subprocess, "run", _FakeRun(rc))
    assert _release._git_tag_exists("v1.0.0") is expected


@pytest.mark.os_agnostic
def test_git_create_tag_and_push_build_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun(0)
    monkeypatch.setattr(_release.subprocess, "run", fake)
    _release._git_create_annotated_tag("v1.2.3", "release 1.2.3")
    _release._git_push("origin", "v1.2.3")
    assert fake.calls[0][:3] == ["git", "tag", "-a"]
    assert fake.calls[1] == ["git", "push", "origin", "v1.2.3"]


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("which", "expected"), [("/usr/bin/gh", True), (None, False)])
def test_gh_available(monkeypatch: pytest.MonkeyPatch, which: str | None, expected: bool) -> None:
    def fake_which(_name: str, path: object = None) -> str | None:
        return which

    monkeypatch.setattr(_release.shutil, "which", fake_which)
    assert _release._gh_available() is expected


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("rc", "expected"), [(0, True), (1, False)])
def test_gh_release_exists(monkeypatch: pytest.MonkeyPatch, rc: int, expected: bool) -> None:
    monkeypatch.setattr(_release.subprocess, "run", _FakeRun(rc))
    assert _release._gh_release_exists("v1.0.0") is expected


@pytest.mark.os_agnostic
def test_gh_release_create_and_edit_build_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRun(0)
    monkeypatch.setattr(_release.subprocess, "run", fake)
    _release._gh_release_create("v1.2.3", "1.2.3", "notes")
    _release._gh_release_edit("v1.2.3", "1.2.3", "notes")
    assert fake.calls[0][:3] == ["gh", "release", "create"]
    assert fake.calls[1][:3] == ["gh", "release", "edit"]


@pytest.mark.os_agnostic
def test_main_delegates_to_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_release(**kwargs: Any) -> int:
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(_release, "release", fake_release)
    assert _release.main(project_dir=tmp_path, remote="upstream") == 0
    assert seen == {"project_dir": tmp_path, "remote": "upstream"}
