"""Git commit and push stage logic.

The message-resolution, timestamp, and sensitive-file detection are pure and
unit-tested without touching git. ``commit`` and ``push_argv`` wrap the actual
git calls. Ports ``commit_010_commit.sh`` and ``push_050_push.sh``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from bmk.domain.stages import normalize_returncode

from .model import StageContext

_SENSITIVE = re.compile(r"\.env$|\.env\.|credentials|secret|\.key$|\.pem$|id_rsa", re.IGNORECASE)


def resolve_message(
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    isatty: bool,
    prompt: Callable[[str], str] = input,
) -> str:
    """Resolve the commit message: args -> BMK_COMMIT_MESSAGE -> prompt (tty) -> 'chores'."""
    message = " ".join(args).strip()
    if not message:
        message = env.get("BMK_COMMIT_MESSAGE", "").strip()
    if not message:
        if isatty:
            message = prompt("Commit message: ").strip()
            if not message:
                msg = "Commit message cannot be empty"
                raise ValueError(msg)
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
    """Stage all changes and create a timestamped commit (interactive stage)."""
    project = ctx.project_dir
    message = resolve_message(ctx.args, env=ctx.env, isatty=sys.stdin.isatty())
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
    "commit",
    "current_branch",
    "detect_sensitive",
    "push_argv",
    "resolve_message",
    "timestamp_prefix",
]
