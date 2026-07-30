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


# ---------------------------------------------------------------------------
# A release must not ship a skill edit the installs will never fetch
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _repo_with_a_shipped_skill(tmp_path: Path, *, plugin_version: str = "1.0.0") -> Path:
    """A real git repo holding a skill and a tagged release, so no git call is faked."""
    import json

    repo = tmp_path / "tool"
    (repo / "skills" / "thing").mkdir(parents=True)
    (repo / ".claude-plugin").mkdir()
    (repo / "skills" / "thing" / "SKILL.md").write_text("# thing\n", encoding="utf-8")
    (repo / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "thing", "version": plugin_version}) + "\n", encoding="utf-8"
    )
    (repo / "pyproject.toml").write_text('[project]\nname = "thing"\nversion = "1.0.0"\n', encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.test")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    _git(repo, "tag", "v1.0.0")
    return repo


@pytest.mark.os_agnostic
def test_a_skill_edit_without_a_plugin_bump_stops_the_release(tmp_path: Path) -> None:
    # An install re-fetches only when the plugin version changes, so this release
    # would ship the code and leave every install on the old skill, silently.
    repo = _repo_with_a_shipped_skill(tmp_path)
    (repo / "skills" / "thing" / "SKILL.md").write_text("# thing\n\nNew guidance.\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "skill edit")

    reason = _release.shipped_skill_needs_a_bump(repo)

    assert reason is not None
    assert "plugin.json is still 1.0.0" in reason
    assert "SKILL.md" in reason


@pytest.mark.os_agnostic
def test_a_skill_edit_with_a_plugin_bump_passes(tmp_path: Path) -> None:
    import json

    repo = _repo_with_a_shipped_skill(tmp_path)
    (repo / "skills" / "thing" / "SKILL.md").write_text("# thing\n\nNew guidance.\n", encoding="utf-8")
    (repo / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "thing", "version": "1.1.0"}) + "\n", encoding="utf-8"
    )
    _git(repo, "commit", "-aqm", "skill edit plus bump")

    assert _release.shipped_skill_needs_a_bump(repo) is None


@pytest.mark.os_agnostic
def test_a_release_that_does_not_touch_the_skill_passes(tmp_path: Path) -> None:
    repo = _repo_with_a_shipped_skill(tmp_path)
    (repo / "pyproject.toml").write_text('[project]\nname = "thing"\nversion = "1.0.1"\n', encoding="utf-8")
    _git(repo, "commit", "-aqm", "code only")

    assert _release.shipped_skill_needs_a_bump(repo) is None


@pytest.mark.os_agnostic
def test_a_repo_that_ships_no_skill_is_not_judged(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    assert _release.shipped_skill_needs_a_bump(plain) is None


@pytest.mark.os_agnostic
def test_a_first_release_has_nothing_to_have_drifted_from(tmp_path: Path) -> None:
    # No previous tag means no previous plugin version to compare, and blocking the
    # very first release of a skill would be nonsense.
    import json

    repo = tmp_path / "fresh"
    (repo / "skills" / "thing").mkdir(parents=True)
    (repo / ".claude-plugin").mkdir()
    (repo / "skills" / "thing" / "SKILL.md").write_text("# thing\n", encoding="utf-8")
    (repo / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "1.0.0"}) + "\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.test")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")

    assert _release.shipped_skill_needs_a_bump(repo) is None
