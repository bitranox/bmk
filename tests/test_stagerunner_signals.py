"""Tests for stage-runner signal handling and the live-process registry.

Kept cross-OS: no real signal delivery here (that is POSIX-specific and would be
flaky on Windows). Real SIGINT delivery is covered by an os_posix test.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

import pytest

from bmk.adapters.stagerunner import signals


def _sleeper() -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_register_and_unregister_track_process() -> None:
    proc = _sleeper()
    try:
        signals.register(proc)
        assert proc in signals._LIVE
        signals.unregister(proc)
        assert proc not in signals._LIVE
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_terminate_all_kills_registered_process() -> None:
    proc = _sleeper()
    signals.register(proc)
    try:
        signals._terminate_all()
        assert proc.wait(timeout=5) is not None
        assert proc.poll() is not None
    finally:
        signals.unregister(proc)


def test_install_signal_handlers_restores_previous_handler() -> None:
    before = signal.getsignal(signal.SIGINT)
    with signals.install_signal_handlers():
        assert signal.getsignal(signal.SIGINT) is not before
    assert signal.getsignal(signal.SIGINT) is before


@pytest.mark.os_posix
def test_sigint_terminates_children_and_exits_128_plus_n() -> None:
    proc = _sleeper()
    signals.register(proc)
    try:
        with pytest.raises(SystemExit) as excinfo, signals.install_signal_handlers():
            os.kill(os.getpid(), signal.SIGINT)
        assert excinfo.value.code == 128 + int(signal.SIGINT)
        assert proc.wait(timeout=5) is not None
    finally:
        signals.unregister(proc)
