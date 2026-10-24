"""Git commit and push stage logic.

The message-resolution, timestamp, and sensitive-file detection are pure and
unit-tested without touching git. ``commit`` and ``push_argv`` wrap the actual
git calls. Ports ``commit_010_commit.sh`` and ``push_050_push.sh``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from typing import TYPE_CHECKING

from bmk.domain.enums import RefusalKind
from bmk.domain.errors import RefusalError
from bmk.domain.stages import normalize_returncode

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from .model import StageContext

_SENSITIVE = re.compile(r"\.env$|\.env\.|credentials|secret|\.key$|\.pem$|id_rsa", re.IGNORECASE)


class EmptyCommitMessageError(RefusalError, ValueError):
    """The person at the prompt entered no commit message; bmk will not commit without one."""

    kind = RefusalKind.INVALID_ARGUMENT


def resolve_message(
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    isatty: bool,
    prompt: Callable[[str], str] = input,
) -> str:
    """Resolve the commit message: args -> BMK_COMMIT_MESSAGE -> prompt (tty) -> 'chores'.

    Raises:
        EmptyCommitMessageError: The prompt was answered with an empty message.
    """
    message = " ".join(args).strip()
    if not message:
        message = env.get("BMK_COMMIT_MESSAGE", "").strip()
    if not message:
        if isatty:
            message = prompt("Commit message: ").strip()
            if not message:
                msg = "Commit message cannot be empty"
                raise EmptyCommitMessageError(msg)
        else:
            message = "chores"
    return message


def timestamp_prefix(now: datetime) -> str:
    """Format the local-time prefix for a commit subject."""
    return now.strftime("%Y-%m-%d %H:%M:%S")


def detect_sensitive(names: Sequence[str]) -> list[str]:
    """Return staged paths that look like secrets (env files, keys, credentials)."""
    return [name for name in names if _SENSITIVE.search(name)]


def _git(args: list[str], project: Path, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project,
        check=False,
        capture_output=capture,
        text=True,
    )


def current_branch(project: Path) -> str:
    """Return the current branch name (``git rev-parse --abbrev-ref HEAD``)."""
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], project, capture=True).stdout.strip()


def push_argv(ctx: StageContext) -> list[str]:
    """Build ``git push -u <remote> <branch>`` (env-overridable, else current branch)."""
    remote = ctx.env.get("BMK_GIT_REMOTE", "origin")
    branch = ctx.env.get("BMK_GIT_BRANCH") or current_branch(ctx.project_dir)
    return ["git", "push", "-u", remote, branch]


def commit(ctx: StageContext) -> int:
    """Stage all changes and create a timestamped commit (interactive stage).

    An empty message at the prompt returns 1 with one stderr line and stages nothing; raised
    out of the stage, it would be reported as a crash with a traceback.
    """
    project = ctx.project_dir
    try:
        message = resolve_message(ctx.args, env=ctx.env, isatty=sys.stdin.isatty())
    except EmptyCommitMessageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    # Local time, matching the shell stage's `date` (not UTC).
    subject = f"{timestamp_prefix(datetime.now())} - {message}"

    # flush so these messages order correctly against the git subprocess output,
    # which writes straight to the fd (relevant when stdout is a pipe, not a tty).
    print("Staging changes...", flush=True)
    _git(["add", "-A"], project)

    staged = _git(["diff", "--cached", "--name-only"], project, capture=True).stdout.splitlines()
    sensitive = detect_sensitive(staged)
    if sensitive:
        print("Warning: Potentially sensitive files staged:", file=sys.stderr)
        for name in sensitive:
            print(f"  {name}", file=sys.stderr)

    nothing_staged = _git(["diff", "--cached", "--quiet"], project).returncode == 0
    commit_flags = ["--allow-empty"] if nothing_staged else []

    print(f"Committing: {subject}", flush=True)
    return normalize_returncode(_git(["commit", *commit_flags, "-m", subject], project).returncode)


__all__ = [
    "EmptyCommitMessageError",
    "commit",
    "current_branch",
    "detect_sensitive",
    "push_argv",
    "resolve_message",
    "timestamp_prefix",
]
