"""Tests for ship command helpers: the gh workflow-run lookup (orjson parsing)."""

# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import click
import pytest

from bmk.adapters.cli.commands import ship_cmd
from bmk.adapters.cli.commands.ship_cmd import GhRunEvent, _find_run_id
from bmk.adapters.cli.exit_codes import ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable

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
    assert _find_run_id("CI", event=GhRunEvent.PUSH, head_sha="abc") == "123"


@pytest.mark.os_agnostic
def test_find_run_id_filters_by_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_JSON))
    assert _find_run_id("Release", event=GhRunEvent.RELEASE, head_sha="def") == "456"


@pytest.mark.os_agnostic
def test_find_run_id_none_on_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_JSON))
    assert _find_run_id("CI", event=GhRunEvent.PUSH, head_sha="different") is None


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


@pytest.mark.os_agnostic
def test_find_run_id_skips_malformed_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run missing required fields fails validation and is skipped, not fatal."""
    mixed = (
        '[{"workflowName": "CI", "event": "push"},'  # no databaseId/headSha -> skipped
        ' {"databaseId": 99, "workflowName": "CI", "event": "push", "headSha": "abc"}]'
    )
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(mixed))
    assert _find_run_id("CI", event=GhRunEvent.PUSH, head_sha="abc") == "99"


# gh reports every trigger event, not only the two ship gates on.
_RUNS_WITH_OTHER_EVENTS_JSON = (
    '[{"databaseId": 301, "workflowName": "CI", "event": "pull_request", "headSha": "abc",'
    ' "status": "completed", "conclusion": "success"},'
    ' {"databaseId": 302, "workflowName": "CI", "event": "workflow_dispatch", "headSha": "abc",'
    ' "status": "in_progress", "conclusion": ""},'
    ' {"databaseId": 303, "workflowName": "CI", "event": "push", "headSha": "abc",'
    ' "status": "queued", "conclusion": ""}]'
)


@pytest.mark.os_agnostic
def test_workflow_run_parses_an_event_outside_the_gated_set() -> None:
    run = ship_cmd._WorkflowRun.model_validate(
        {"databaseId": 1, "workflowName": "CI", "event": "schedule", "headSha": "abc", "status": "queued"}
    )
    assert run.event == "schedule"
    assert type(run.event) is str


@pytest.mark.os_agnostic
def test_find_run_id_skips_runs_of_other_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs triggered by pull_request / workflow_dispatch parse, but never match a push gate."""
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_WITH_OTHER_EVENTS_JSON))
    assert _find_run_id("CI", event=GhRunEvent.PUSH, head_sha="abc") == "303"


@pytest.mark.os_agnostic
def test_find_run_id_none_when_only_other_events_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    only_others = _RUNS_WITH_OTHER_EVENTS_JSON.replace('"event": "push"', '"event": "schedule"')
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(only_others))
    assert _find_run_id("CI", event=GhRunEvent.PUSH, head_sha="abc") is None
    assert _find_run_id("CI", event=GhRunEvent.RELEASE, head_sha="abc") is None


@pytest.mark.os_agnostic
def test_find_run_id_with_no_event_filter_takes_any_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh(_RUNS_WITH_OTHER_EVENTS_JSON))
    assert _find_run_id("CI", event=None, head_sha="abc") == "301"


@pytest.mark.os_agnostic
def test_gh_run_event_values_are_the_strings_gh_reports() -> None:
    assert [event.value for event in GhRunEvent] == ["push", "release"]
    assert all(type(event.value) is str for event in GhRunEvent)


# ---------------------------------------------------------------------------
# _watch_run / _git_head
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_watch_run_true_on_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh("", returncode=0))
    assert ship_cmd._watch_run("1") is True


@pytest.mark.os_agnostic
def test_watch_run_false_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh("", returncode=1))
    assert ship_cmd._watch_run("1") is False


@pytest.mark.os_agnostic
def test_git_head_returns_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh("abc123\n", returncode=0))
    assert ship_cmd._git_head() == "abc123"


@pytest.mark.os_agnostic
def test_git_head_empty_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd.subprocess, "run", _fake_gh("nope", returncode=128))
    assert ship_cmd._git_head() == ""


# ---------------------------------------------------------------------------
# _gate_on_ci
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_gate_on_ci_raises_when_watched_run_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd, "_find_run_id", lambda *_a, **_k: "77")
    monkeypatch.setattr(ship_cmd, "_watch_run", lambda _run_id: False)
    with click.Context(ship_cmd.cli_ship).scope(), pytest.raises(click.exceptions.Exit) as exited:
        ship_cmd._gate_on_ci("CI", event=GhRunEvent.PUSH, head_sha="abc", label="CI")
    assert exited.value.exit_code == ExitCode.GENERAL_ERROR


@pytest.mark.os_agnostic
def test_gate_on_ci_raises_when_no_run_appears_before_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The find-run loop times out to GENERAL_ERROR; monotonic is stubbed so no real wait happens."""
    monkeypatch.setattr(ship_cmd, "_find_run_id", lambda *_a, **_k: None)
    monkeypatch.setattr(ship_cmd.time, "sleep", lambda _s: None)
    clock = iter([0.0, 10_000.0])  # deadline set from 0, next read is already past it
    monkeypatch.setattr(ship_cmd.time, "monotonic", lambda: next(clock))
    with click.Context(ship_cmd.cli_ship).scope(), pytest.raises(click.exceptions.Exit) as exited:
        ship_cmd._gate_on_ci("CI", event=GhRunEvent.PUSH, head_sha="abc", label="CI")
    assert exited.value.exit_code == ExitCode.GENERAL_ERROR


@pytest.mark.os_agnostic
def test_gate_on_ci_passes_when_run_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ship_cmd, "_find_run_id", lambda *_a, **_k: "5")
    monkeypatch.setattr(ship_cmd, "_watch_run", lambda _run_id: True)
    ship_cmd._gate_on_ci("CI", event=GhRunEvent.PUSH, head_sha="abc", label="CI")  # must not raise


# ---------------------------------------------------------------------------
# _run_ship orchestration
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_ship_gh_missing_runs_push_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """No gh -> push only, and release is never reached (the manual-CI degrade path)."""
    order: list[str] = []
    monkeypatch.setattr(ship_cmd.shutil, "which", lambda _name: None)
    monkeypatch.setattr("bmk.adapters.cli.commands.push_cmd.run_push", lambda _msg: order.append("push"))
    monkeypatch.setattr("bmk.adapters.cli.commands.release_cmd.run_release", lambda _args: order.append("release"))
    ship_cmd._run_ship(("msg",), "CI", "Release")
    assert order == ["push"]


@pytest.mark.os_agnostic
def test_run_ship_full_sequence_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """gh present -> push, gate CI, release, gate release, in that exact order."""
    order: list[str] = []
    monkeypatch.setattr(ship_cmd.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr("bmk.adapters.cli.commands.push_cmd.run_push", lambda _msg: order.append("push"))
    monkeypatch.setattr("bmk.adapters.cli.commands.release_cmd.run_release", lambda _args: order.append("release"))
    monkeypatch.setattr(ship_cmd, "_git_head", lambda: "abc")
    monkeypatch.setattr(ship_cmd, "_gate_on_ci", lambda _wf, *, event, head_sha, label: order.append(f"gate:{label}"))
    ship_cmd._run_ship((), "CI", "Release")
    assert order == ["push", "gate:CI", "release", "gate:release"]


@pytest.mark.os_agnostic
def test_cli_ship_help_lists_workflow_options() -> None:
    from click.testing import CliRunner

    result = CliRunner().invoke(ship_cmd.cli_ship, ["--help"])
    assert result.exit_code == 0
    assert "--ci-workflow" in result.output
    assert "--release-workflow" in result.output
