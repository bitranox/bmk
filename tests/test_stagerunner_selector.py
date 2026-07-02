"""Tests for the BMK_RUNNER selector in execute_script.

During migration the Python engine is opt-in: only when BMK_RUNNER=python and the
prefix is ported does execute_script run it in-process. Otherwise the legacy
shell path is used (verified by asserting the in-process side effect does NOT
happen).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bmk.adapters.cli.commands._shared import execute_script


def test_python_runner_runs_ported_pipeline_in_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BMK_RUNNER", "python")
    (tmp_path / ".ruff_cache").mkdir()

    rc = execute_script(
        Path("ignored-for-python-path"),
        tmp_path,
        (),
        command_prefix="clean",
        output_format="json",
    )

    assert rc == 0
    assert not (tmp_path / ".ruff_cache").exists()


def test_default_runner_does_not_use_python_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BMK_RUNNER", raising=False)
    marker = tmp_path / ".ruff_cache"
    marker.mkdir()

    # A non-existent script path: the shell path will fail to spawn it, proving
    # we did NOT take the in-process path (which would have removed the marker).
    with pytest.raises(OSError):  # any spawn failure proves the shell path was taken
        execute_script(
            tmp_path / "does_not_exist.sh",
            tmp_path,
            (),
            command_prefix="clean",
            output_format="json",
        )

    assert marker.exists()
