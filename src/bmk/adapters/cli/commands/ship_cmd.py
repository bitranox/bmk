"""CLI command for the full CI-gated release: push, wait, release, wait.

``ship`` chains the existing ``push`` and ``release`` steps with GitHub CI
gating in between:

1. ``push`` — run tests, commit, push to the remote.
2. Wait for the push-triggered ``CI`` workflow run to finish; abort if it fails.
3. ``release`` — create the version tag and GitHub release.
4. Wait for the release/publish workflow run to finish; abort if it fails.

CI gating is done via the GitHub CLI (``gh``); the run is matched to the just-
pushed ``HEAD`` commit so concurrent activity does not confuse it. If ``gh`` is
not installed or authenticated, ``ship`` stops after the push with a clear
message so the operator can watch CI manually.

Contents:
    * :func:`cli_ship` - Ship command.
    * :func:`cli_sh` - Short alias for ``cli_ship``.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time

import lib_log_rich.runtime
import rich_click as click

from ..constants import CLICK_CONTEXT_SETTINGS
from ..typed_click import argument, option

logger = logging.getLogger(__name__)

_POLL_SECONDS = 15
_FIND_RUN_TIMEOUT = 180  # how long to wait for a run to appear after push/release
_DEFAULT_CI_WORKFLOW = "CI"
_DEFAULT_RELEASE_WORKFLOW = "Release"


def _git_head() -> str:
    """Return the current HEAD commit sha, or empty string on failure."""
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)  # noqa: S607
    return result.stdout.strip() if result.returncode == 0 else ""


def _find_run_id(workflow: str, *, event: str | None, head_sha: str) -> str | None:
    """Find the most recent workflow run id matching workflow/event/head_sha."""
    fields = "databaseId,workflowName,event,headSha,status,conclusion"
    result = subprocess.run(  # noqa: S603
        ["gh", "run", "list", "--limit", "20", "--json", fields],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for run in runs:
        if run.get("workflowName") != workflow:
            continue
        if event is not None and run.get("event") != event:
            continue
        if head_sha and run.get("headSha") and run["headSha"] != head_sha:
            continue
        return str(run["databaseId"])
    return None


def _watch_run(run_id: str) -> bool:
    """Block until the run finishes; return True on success."""
    result = subprocess.run(["gh", "run", "watch", run_id, "--exit-status"], check=False)  # noqa: S603, S607
    return result.returncode == 0


def _gate_on_ci(workflow: str, *, event: str | None, head_sha: str, label: str) -> None:
    """Find and watch the workflow run for *head_sha*; raise SystemExit on failure.

    Args:
        workflow: GitHub workflow name to match.
        event: Trigger event to match (``push`` / ``release``), or None for any.
        head_sha: Commit sha the run must belong to.
        label: Human label for log messages.

    Raises:
        SystemExit: If the run fails, or no run appears within the timeout.
    """
    logger.info("Waiting for the %s workflow run to start", label)
    deadline = time.monotonic() + _FIND_RUN_TIMEOUT
    run_id: str | None = None
    while run_id is None and time.monotonic() < deadline:
        run_id = _find_run_id(workflow, event=event, head_sha=head_sha)
        if run_id is None:
            time.sleep(_POLL_SECONDS)
    if run_id is None:
        logger.error("No %s workflow run appeared within %ds", label, _FIND_RUN_TIMEOUT)
        raise SystemExit(1)
    logger.info("Watching %s workflow run %s", label, run_id)
    if not _watch_run(run_id):
        logger.error("%s workflow run %s failed", label, run_id)
        raise SystemExit(1)
    logger.info("%s workflow run %s succeeded", label, run_id)


def _run_ship(message: tuple[str, ...], ci_workflow: str, release_workflow: str) -> None:
    """Execute push, CI gate, release, release CI gate.

    Raises:
        SystemExit: On any step failure.
    """
    from .push_cmd import run_push
    from .release_cmd import run_release

    if shutil.which("gh") is None:
        logger.warning("gh CLI not found; running push only. Watch CI and run 'bmk release' manually.")
        run_push(message)
        return

    run_push(message)
    head_sha = _git_head()
    _gate_on_ci(ci_workflow, event="push", head_sha=head_sha, label="CI")
    run_release(())
    # The release tag points at the same commit; match the release workflow by sha.
    _gate_on_ci(release_workflow, event=None, head_sha=head_sha, label="release")


@click.command("ship", context_settings=CLICK_CONTEXT_SETTINGS)
@option("--ci-workflow", default=_DEFAULT_CI_WORKFLOW, show_default=True, help="CI workflow name to gate on.")
@option(
    "--release-workflow",
    default=_DEFAULT_RELEASE_WORKFLOW,
    show_default=True,
    help="Release workflow name to gate on.",
)
@argument("message", nargs=-1)
def cli_ship(message: tuple[str, ...], ci_workflow: str, release_workflow: str) -> None:
    """Push, wait for CI, release, wait for the release workflow.

    The full CI-gated release: runs ``push`` (tests + commit + push), waits for
    the push-triggered CI workflow to pass, runs ``release`` (tag + GitHub
    release), then waits for the release workflow to pass. Aborts if any CI run
    fails. Requires the GitHub CLI (``gh``) for gating.

    MESSAGE is the commit message (default: "chores").

    Example:
        bmk ship "fix reconnect bug"
        bmk ship --ci-workflow CI --release-workflow Release "release 1.2.3"
    """
    with lib_log_rich.runtime.bind(job_id="cli-ship"):
        logger.info("Running ship pipeline (push, CI gate, release, release CI gate)")
        _run_ship(message, ci_workflow, release_workflow)


@click.command("sh", context_settings=CLICK_CONTEXT_SETTINGS)
@option("--ci-workflow", default=_DEFAULT_CI_WORKFLOW, show_default=True, help="CI workflow name to gate on.")
@option(
    "--release-workflow",
    default=_DEFAULT_RELEASE_WORKFLOW,
    show_default=True,
    help="Release workflow name to gate on.",
)
@argument("message", nargs=-1)
def cli_sh(message: tuple[str, ...], ci_workflow: str, release_workflow: str) -> None:
    """Push, gate on CI, release, gate on CI (short alias for 'ship').

    See ``bmk ship --help`` for full documentation.
    """
    with lib_log_rich.runtime.bind(job_id="cli-ship"):
        logger.info("Running ship pipeline (push, CI gate, release, release CI gate)")
        _run_ship(message, ci_workflow, release_workflow)


__all__ = ["cli_sh", "cli_ship"]
