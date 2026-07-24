"""Signal handling and the live-subprocess registry.

A ThreadPoolExecutor worker cannot be force-killed while blocked in
``Popen.wait()``. So on SIGINT/SIGTERM we terminate the tracked child processes
directly; each worker's ``run_argv`` then returns once its child dies.

Cross-OS: ``signal.signal`` may only be called from the main thread and supports
a limited signal set on Windows, so handler installation is guarded and becomes a
no-op where it cannot apply.
"""

from __future__ import annotations

import contextlib
import signal
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Generator

_LIVE: set[subprocess.Popen[str]] = set()
_LOCK = threading.Lock()

# Only signals that exist on this platform. SIGINT is universal; SIGTERM exists
# on Windows too but is settable there, so include whichever are present.
_HANDLED_SIGNALS: tuple[signal.Signals, ...] = tuple(
    sig for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)) if sig is not None
)


def register(proc: subprocess.Popen[str]) -> None:
    """Track a live child process so a signal handler can terminate it."""
    with _LOCK:
        _LIVE.add(proc)


def unregister(proc: subprocess.Popen[str]) -> None:
    """Stop tracking a child process (it has finished or been handled)."""
    with _LOCK:
        _LIVE.discard(proc)


def live_count() -> int:
    """Return how many child processes are currently tracked."""
    with _LOCK:
        return len(_LIVE)


def terminate_all() -> None:
    """Terminate every tracked child process (best effort)."""
    with _LOCK:
        procs = list(_LIVE)
    for proc in procs:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.terminate()


def _install_one(
    sig: signal.Signals,
    handler: Callable[[int, object], None],
    previous: dict[signal.Signals, object],
) -> None:
    try:
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, handler)
    except (ValueError, OSError):
        previous.pop(sig, None)


@contextlib.contextmanager
def install_signal_handlers() -> Generator[None]:
    """Install SIGINT/SIGTERM handlers that terminate children, then restore them.

    No-op when not on the main thread (``signal.signal`` would raise there).
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def handler(signum: int, _frame: object) -> None:
        terminate_all()
        raise SystemExit(128 + signum)

    previous: dict[signal.Signals, object] = {}
    for sig in _HANDLED_SIGNALS:
        _install_one(sig, handler, previous)
    try:
        yield
    finally:
        for sig, prev in previous.items():
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(sig, prev)  # type: ignore[arg-type]
