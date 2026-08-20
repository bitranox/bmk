"""Cross-process lock over bmk's own, machine-wide uv tool environment.

bmk is installed once per machine, into uv's tool dir, and the generated Makefile upgrades
that environment before EVERY target. When a new release reaches PyPI, the first ``make``
that notices rebuilds the environment in place while any other bmk - in any other repo, or
a subagent's gate beside your own - is still running out of it. What the victim reports is
an ImportError inside bmk's OWN dependencies (``pip_api._hash``,
``pydantic.functional_serializers``) that clears on a re-run, so it reads as a flake rather
than as its interpreter's site-packages being deleted mid-gate.

Every bmk process holds a SHARED lock here for its lifetime; the Makefile takes the same
lock EXCLUSIVE around the upgrade. Readers never exclude each other, so two repos still
gate concurrently, which is the entire point - a guard that serialised gates would be the
machine-wide stall this exists to remove.

Why a private lock file rather than uv's own ``<tools>/.lock``, which uv genuinely honours
(measured: ``uv tool install`` blocks on an exclusive flock held there)? Because ``uv tool
upgrade`` and ``uv tool list`` block on it too, and the upgrade runs before every make
target. A gate-lifetime shared lock on uv's file would make every ``make`` on the machine -
and every unrelated ``uv tool install`` - wait for the longest-running gate.

Stdlib only, and deliberately TOP-LEVEL rather than ``bmk._toollock``, for the same reason
as :mod:`bmk_selfcheck`: ``python -m`` on a submodule would execute ``bmk/__init__.py``
first, so the guard would import the very package whose environment it is guarding, and it
must keep working when that environment is the damaged thing being repaired.

That is not circular, and the reason is structural: a uv tool env's ``bin/python`` is a
SYMLINK to an interpreter outside the tool dir, so the stdlib this runs on is not part of
the tree uv replaces, and this module is read and compiled before ``uv`` is ever spawned.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

#: ETIMEDOUT. Mirrors ``ExitCode.TIMEOUT`` in ``bmk/adapters/cli/exit_codes.py``, which is
#: unreachable from here (stdlib only, and importing bmk defeats the point). A test pins
#: the two together so they cannot drift.
EXIT_TIMEOUT = 110

#: Marks a uv TOOL environment. A plain ``uv venv`` has none, so a pytest run or a
#: ``uvx bmk`` locks nothing and cannot collide with the machine's real tool env.
RECEIPT_NAME = "uv-receipt.toml"

LOCK_NAME = ".bmk-tool.lock"
#: Point the guard at a throwaway lock file. For tests; not part of the user contract.
LOCK_PATH_ENV = "BMK_TOOL_LOCK_PATH"
#: Set to the holder's pid once this process holds the lock, and inherited by every child.
LOCK_HELD_ENV = "BMK_TOOL_LOCK_HELD"
#: ``0`` disables the guard entirely.
LOCK_ENABLE_ENV = "BMK_TOOL_LOCK"

_DEFAULT_TIMEOUT = 30.0
_POLL_SECONDS = 0.05

#: Acquired fds, kept open for the process lifetime. A POSIX flock belongs to the open file
#: description, so closing the fd - or letting it be garbage collected - releases the lock.
_HELD: list[int] = []


def tool_env_root(prefix: Path | None = None) -> Path | None:
    """The uv tool dir that contains ``prefix``, or None when this is not a tool env.

    Args:
        prefix: Environment to inspect; defaults to the running interpreter's ``sys.prefix``.

    Returns:
        The PARENT of the environment - uv's tools root - or None when there is no receipt.
        The parent, not the environment itself, because ``uv tool install --reinstall``
        deletes the environment directory, and a lock inside it would be deleted with it.
    """
    env_dir = Path(sys.prefix) if prefix is None else Path(prefix)
    if not (env_dir / RECEIPT_NAME).is_file():
        return None
    return env_dir.parent


def lock_path(root: Path) -> Path:
    """The lock file guarding every environment under uv's tools ``root``."""
    return root / LOCK_NAME


def resolve_lock_path() -> Path | None:
    """Where this process should lock, or None when there is nothing to guard."""
    override = os.environ.get(LOCK_PATH_ENV, "").strip()
    if override:
        return Path(override)
    root = tool_env_root()
    return None if root is None else lock_path(root)


if sys.platform == "win32":  # pragma: no cover - exercised on the Windows CI cell
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    _LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    _WHOLE_FILE_LOW = 0xFFFFFFFF
    _WHOLE_FILE_HIGH = 0xFFFFFFFF

    class _Overlapped(ctypes.Structure):
        """The OVERLAPPED LockFileEx requires; zeroed, so it locks from offset 0."""

        _fields_ = (
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        )

    def _try_lock(fd: int, *, exclusive: bool) -> bool:
        """One non-blocking attempt.

        ``msvcrt.locking`` cannot express a shared lock at all, so this goes to LockFileEx,
        where the absence of LOCKFILE_EXCLUSIVE_LOCK IS the shared mode.
        """
        flags = _LOCKFILE_FAIL_IMMEDIATELY | (_LOCKFILE_EXCLUSIVE_LOCK if exclusive else 0)
        overlapped = _Overlapped()
        handle = msvcrt.get_osfhandle(fd)
        locked = ctypes.windll.kernel32.LockFileEx(
            handle, flags, 0, _WHOLE_FILE_LOW, _WHOLE_FILE_HIGH, ctypes.byref(overlapped)
        )
        return bool(locked)

else:
    import fcntl

    def _try_lock(fd: int, *, exclusive: bool) -> bool:
        """One non-blocking attempt; False means somebody else holds an conflicting lock."""
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
        except OSError:
            return False
        return True


def acquire(path: str | os.PathLike[str], *, exclusive: bool, timeout: float) -> bool:
    """Take the lock at ``path``, waiting up to ``timeout`` seconds.

    The fd is kept open for the life of the process: an flock belongs to the open file
    description, so releasing it early would silently drop the guarantee.

    Returns:
        True if held. False on timeout. Raises OSError only if the file cannot be opened,
        which callers treat as "no lock available here" rather than as a held lock.
    """
    fd = os.open(os.fspath(path), os.O_RDWR | os.O_CREAT, 0o666)
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if _try_lock(fd, exclusive=exclusive):
            _HELD.append(fd)
            return True
        if time.monotonic() >= deadline:
            os.close(fd)
            return False
        time.sleep(_POLL_SECONDS)


def hold_shared(timeout: float = _DEFAULT_TIMEOUT) -> bool:
    """Announce this bmk as a reader of the shared tool env, for its whole lifetime.

    Best-effort by construction: refusing to run bmk because a lock is busy would be worse
    than the race it prevents, so every failure path returns False and lets bmk run.

    Publishing :data:`LOCK_HELD_ENV` is what stops a nested ``make`` from rebuilding the
    environment its parent is running out of - see :func:`main`.
    """
    if os.environ.get(LOCK_ENABLE_ENV) == "0" or os.environ.get(LOCK_HELD_ENV):
        return False
    target = resolve_lock_path()
    if target is None:
        return False
    try:
        held = acquire(target, exclusive=False, timeout=timeout)
    except OSError:
        return False
    if held:
        os.environ[LOCK_HELD_ENV] = str(os.getpid())
    return held


def env_fingerprint(env_dir: Path | None = None) -> tuple[int, int, int] | None:
    """Identify the CURRENT installation of the tool env, or None when there is not one.

    uv rewrites ``uv-receipt.toml`` whenever it installs or upgrades a tool, so the
    receipt's stat is a cheap stand-in for "this is the same installation I started with".
    """
    target = Path(sys.prefix) if env_dir is None else Path(env_dir)
    try:
        stat = (target / RECEIPT_NAME).stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size, stat.st_ino)


def env_changed(before: tuple[int, int, int] | None, env_dir: Path | None = None) -> bool:
    """Whether the tool env was reinstalled since ``before`` was taken.

    This is the half of the problem a lock cannot reach: a repo whose Makefile predates the
    guard is an unguarded writer until its next ``make`` regenerates it, and a hand-run
    ``uv tool install bmk`` is unguarded forever. Neither can be prevented from inside a
    victim process - but the victim can say what happened instead of reporting an
    ImportError in bmk's own dependencies that reads as a flake.

    A missing ``before`` means this was never a tool env, so nothing is claimed.
    """
    if before is None:
        return False
    return env_fingerprint(env_dir) != before


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bmk_toollock",
        description="Run a command under bmk's shared tool-environment lock.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--exclusive", action="store_true", help="take the lock exclusively (a mutation)")
    mode.add_argument("--shared", action="store_true", help="take the lock shared (a reader)")
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT, help="seconds to wait")
    parser.add_argument(
        "--on-timeout",
        choices=("skip", "fail"),
        default="skip",
        help="skip: leave the command unrun and exit 0. fail: exit with the timeout code.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def _run(command: list[str]) -> int:
    """Run the wrapped command with inherited stdio.

    Never captured: a real upgrade failure has to reach the terminal, the same doctrine the
    Makefile applies by refusing ``2>/dev/null`` on these lines.
    """
    if not command:
        return 0
    return subprocess.run(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    """Entry point: acquire, run, release.

    The command is run unguarded whenever there is nothing to guard or the lock cannot be
    taken at all - an unlockable filesystem is not evidence of a concurrent holder, and
    refusing there would break ``make`` for everyone on such a mount. The one case that
    does NOT fall through to running the command is a genuine timeout: somebody really is
    holding it, and proceeding is the corruption this exists to prevent.
    """
    args = _parse(list(sys.argv[1:] if argv is None else argv))
    command = [item for item in args.command if item != "--"]

    if os.environ.get(LOCK_ENABLE_ENV) == "0":
        return _run(command)

    # A nested make inherits the parent's token. It must not wait for the parent's own lock
    # (that never returns) and must not rebuild the environment the parent is running out
    # of (that is the bug). So it does neither, and skips.
    if os.environ.get(LOCK_HELD_ENV):
        return 0

    target = resolve_lock_path()
    if target is None:
        return _run(command)

    try:
        held = acquire(target, exclusive=not args.shared, timeout=args.timeout)
    except OSError as exc:
        print(f"[bmk] could not lock {target} ({exc}); proceeding unguarded", file=sys.stderr)
        return _run(command)

    if not held:
        print(
            f"[bmk] another bmk is using the shared tool environment; waited {args.timeout:g}s "
            f"for the lock at {target} and gave up. Nothing was changed.",
            file=sys.stderr,
        )
        return 0 if args.on_timeout == "skip" else EXIT_TIMEOUT

    return _run(command)


if __name__ == "__main__":
    raise SystemExit(main())
