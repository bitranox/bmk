"""Keep a project's bmk current without anyone having to remember.

The Makefile installs bmk into the project's own ``.venv-bmk`` and skips the
install while a stamp file is newer than ``pyproject.toml``. That is what makes
`make` fast, but on its own it would also pin bmk forever: nothing would ever
notice a new release, and a fleet quietly sitting on an old bmk is exactly the
kind of silent staleness the stamp exists to avoid elsewhere.

So bmk checks for a newer release itself. It cannot install one from inside a
running bmk - that would rewrite the env it is executing from, which Windows
forbids outright - so it DELETES THE STAMP instead. make rebuilds a missing stamp,
and it does so in `_ensure_bmk`, BEFORE any bmk process starts: the next `make`
installs the new version with uv and then runs it. Nothing ever replaces an env
out from under a live process, and the user does nothing but run their next
command.

The check runs at most once a day and never fails a build: no network, no
`.venv-bmk`, a malformed response, anything at all - it returns quietly and the
run continues.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Mapping
from pathlib import Path

from bmk.__init__conf__ import version as _installed_version

from .helpers._dependencies import compare_versions, fetch_latest_version

#: Directory the Makefile installs bmk into, and the stamp it skips on.
TOOL_DIR_NAME = ".venv-bmk"
STAMP_NAME = ".bmk-installed"

#: Marker whose mtime records the last check.
CHECK_MARKER_NAME = ".bmk-upgrade-checked"

#: Ask PyPI at most this often. A day keeps a release reaching the fleet promptly
#: while costing one request per repo per day.
CHECK_INTERVAL_SECONDS = 24 * 60 * 60

#: Set to "1" to never contact PyPI.
OPT_OUT_ENV = "BMK_NO_UPGRADE_CHECK"


def _is_due(marker: Path, now: float) -> bool:
    """Whether enough time has passed since the last check."""
    try:
        return (now - marker.stat().st_mtime) >= CHECK_INTERVAL_SECONDS
    except OSError:
        return True  # never checked


def _touch(marker: Path) -> None:
    """Record that a check happened, so a failing one does not retry every run."""
    with contextlib.suppress(OSError):
        marker.touch()


def _is_check_due(tool_dir: Path, env: Mapping[str, str], now: float) -> bool:
    """Whether to ask PyPI at all on this run."""
    if env.get(OPT_OUT_ENV) == "1":
        return False
    if not tool_dir.is_dir():
        return False  # not the Makefile-managed layout; nothing to invalidate
    return _is_due(tool_dir / CHECK_MARKER_NAME, now)


def _newer_release() -> str | None:
    """The latest bmk on PyPI when it is newer than this one, else None."""
    try:
        # Deliberately broad: this is a convenience check, and no failure of it -
        # DNS, TLS, a proxy, a malformed body - may ever fail someone's build.
        latest = fetch_latest_version("bmk")
    except Exception:
        return None
    if not latest or compare_versions(_installed_version, latest) != "outdated":
        return None
    return latest


def _invalidate_stamp(tool_dir: Path) -> bool:
    """Remove the install stamp so make rebuilds the env on the next target."""
    try:
        (tool_dir / STAMP_NAME).unlink(missing_ok=True)
    except OSError:
        return False
    return True


def check_for_upgrade(
    project_dir: Path, env: Mapping[str, str] | None = None, *, now: float | None = None
) -> str | None:
    """Invalidate the install stamp when a newer bmk exists on PyPI.

    Args:
        project_dir: The project whose ``.venv-bmk`` is managed by its Makefile.
        env: Environment to read the opt-out from (defaults to ``os.environ``).
        now: Current epoch seconds; injected by tests.

    Returns:
        The newer version when the stamp was invalidated, else ``None``. Never
        raises: a build must not fail because PyPI was unreachable.
    """
    tool_dir = project_dir / TOOL_DIR_NAME
    environ = os.environ if env is None else env
    if not _is_check_due(tool_dir, environ, time.time() if now is None else now):
        return None

    # Mark BEFORE the request: a failing check must not retry on every make.
    _touch(tool_dir / CHECK_MARKER_NAME)

    latest = _newer_release()
    if latest is None:
        return None
    return latest if _invalidate_stamp(tool_dir) else None
