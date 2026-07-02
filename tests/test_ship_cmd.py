"""Tests for ship command helpers: the gh workflow-run lookup (orjson parsing)."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest

from bmk.adapters.cli.commands import ship_cmd
from bmk.adapters.cli.commands.ship_cmd import _find_run_id

_RUNS_JSON = (
    '[{"databaseId": 123, "workflowName": "CI", "event": "push", "headSha": "abc"},'
    ' {"databaseId": 456, "workflowName": "Release", "event": "release", "headSha": "def"}]'
)


def _fake_gh(stdout: str, returncode: int = 0) -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")

    return _run


@pytest.mark.os_agnostic
def test_find_run_id_matches_workflow_event_and_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_JSON))
    assert _find_run_id("CI", event="push", head_sha="abc") == "123"


@pytest.mark.os_agnostic
def test_find_run_id_filters_by_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_JSON))
    assert _find_run_id("Release", event="release", head_sha="def") == "456"


@pytest.mark.os_agnostic
def test_find_run_id_none_on_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_JSON))
    assert _find_run_id("CI", event="push", head_sha="different") is None


@pytest.mark.os_agnostic
def test_find_run_id_ignores_sha_and_event_filters_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_JSON))
    assert _find_run_id("CI", event=None, head_sha="") == "123"


@pytest.mark.os_agnostic
def test_find_run_id_none_when_gh_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh("", returncode=1))
    assert _find_run_id("CI", event=None, head_sha="") is None


@pytest.mark.os_agnostic
def test_find_run_id_none_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh("not json at all"))
    assert _find_run_id("CI", event=None, head_sha="") is None
