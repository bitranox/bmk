"""End to end: a failed ``uv sync`` is reported with uv's own words, against the REAL uv.

The stub-``uv`` tests in ``test_stagerunner_venv.py`` pin the report's shape; these pin that the
shape holds for what uv actually prints. The project's in-tree build backend raises, so ``uv venv``
and ``uv lock`` succeed and ``uv sync --locked`` fails building the editable install - a real
failure with uv's verdict FIRST (``error: Failed to build ...``) and the backend's own stderr after
it. The backend prints filler lines before it raises, so the verdict sits further from the end than
any tail a report might be capped at.

Nothing is downloaded: the project has no dependencies and the backend requires nothing, so the
whole run works with ``UV_OFFLINE=1`` and a cold, test-owned uv cache.

A failed ``uv lock`` is pinned the same way: a project depending on a package that exists nowhere,
locked offline against a cold cache, so uv's resolver error must appear under bmk's lock header.
"""

from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.cli.commands._shared import run_command
from bmk.adapters.stagerunner.venv import ensure_project_venv_at
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from pathlib import Path

_MARKER = "e2e-backend-marker-3c8f"
_FILLER_LINES = 30
_ESC = chr(0x1B)

_PYPROJECT = """\
[project]
name = "failing-demo"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []

[build-system]
requires = []
build-backend = "failing_backend"
backend-path = ["."]
"""

# The marker is joined at run time so it reaches stderr exactly once, in the exception's own line:
# a literal would appear a second time where the traceback echoes this source.
_BACKEND = f'''\
"""A PEP 517 backend whose every build hook fails."""

import sys

MARKER = "-".join({tuple(_MARKER.split("-"))!r})


def _fail(*_args, **_kwargs):
    for number in range(1, {_FILLER_LINES} + 1):
        print("e2e-filler-%d" % number, file=sys.stderr)
    raise RuntimeError(MARKER)


build_wheel = build_sdist = build_editable = _fail
'''

_STATES = "venv|directory without pyvenv\\.cfg|empty directory|absent"
_HEADER = re.compile(rf"\[venv\] uv sync from uv\.lock failed for \.venv \(exit [0-9]+; venv afterwards: ({_STATES})\)")

pytestmark = [
    pytest.mark.os_agnostic,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed"),
]


@pytest.fixture
def failing_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project whose build backend raises, with uv offline and its cache and the venv locks under tmp_path."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (project / "failing_backend.py").write_text(_BACKEND, encoding="utf-8")
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("BMK_VENV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    return project


def _header_index(lines: list[str], *, colon: bool) -> int:
    """Index of the one failure header in ``lines``, with or without the trailing colon."""
    suffix = ":" if colon else ""
    found = [
        i
        for i, line in enumerate(lines)
        if line.endswith(")" + suffix) and _HEADER.fullmatch(line.removesuffix(suffix))
    ]
    assert len(found) == 1, f"exactly one failure header expected in: {lines!r}"
    return found[0]


def _indented_block(lines: list[str], start: int) -> list[str]:
    """The contiguous run of four-space-indented lines after ``start``, indent removed."""
    block: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        block.append(line[4:])
    return block


def _index_of(lines: list[str], needle: str, *, prefix: bool = False) -> int:
    """Index of the first line containing (or, with ``prefix``, starting with) ``needle``."""
    found = [i for i, line in enumerate(lines) if (line.startswith(needle) if prefix else needle in line)]
    assert found, f"{needle!r} missing from: {lines!r}"
    return found[0]


def test_a_json_mode_failed_sync_reports_all_of_real_uv_s_stderr(
    failing_project: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Forced colour gives the no-escape assertion something to remove: uv colours a pipe under it.
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("UV_NO_COLOR", raising=False)

    assert ensure_project_venv_at(failing_project, failing_project / ".venv", None, quiet=True) is None

    err = capfd.readouterr().err
    assert _ESC not in err, "no escape byte reaches a CI log"
    lines = err.splitlines()
    block = _indented_block(lines, _header_index(lines, colon=True))
    error_at = _index_of(block, "error: Failed to build", prefix=True)
    stripped = [line.strip() for line in block]
    missing = [n for n in range(1, _FILLER_LINES + 1) if f"e2e-filler-{n}" not in stripped]
    assert not missing, f"uv's stderr reached the report whole, filler lines {missing} are missing"
    fillers = [stripped.index(f"e2e-filler-{n}") for n in range(1, _FILLER_LINES + 1)]
    marker_at = _index_of(block, f"RuntimeError: {_MARKER}")
    assert error_at < fillers[0] < fillers[-1] < marker_at, "every line uv wrote, in uv's order"
    assert err.count(_MARKER) == 1, "the backend's own error, reported once"


def test_a_text_mode_failed_sync_streams_real_uv_live_under_a_bare_header(
    failing_project: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Text mode passes uv's stream through untouched, so plain output is what makes it matchable:
    # forced colour splits "RuntimeError: <marker>" with escape codes (uv's and Python 3.13+'s own).
    for name in ("FORCE_COLOR", "CLICOLOR_FORCE", "PYTHON_COLORS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")

    assert ensure_project_venv_at(failing_project, failing_project / ".venv", None, quiet=False) is None

    err = capfd.readouterr().err
    lines = err.splitlines()
    header_at = _header_index(lines, colon=False)
    assert err.count(_MARKER) == 1, "uv's stream is the only copy: bmk does not echo it again"
    marker_at = _index_of(lines, f"RuntimeError: {_MARKER}")
    error_at = _index_of(lines, "error: Failed to build", prefix=True)
    assert error_at < marker_at < header_at, "uv's output streamed live, before bmk's header"


_MISSING_PACKAGE = "bmk-no-such-package-e2e-9d41"


def test_a_json_mode_failed_lock_reports_real_uv_s_resolver_error_under_its_header(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
        f'dependencies = ["{_MISSING_PACKAGE}"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("BMK_VENV_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)

    assert ensure_project_venv_at(project, project / ".venv", None, quiet=True) is None

    lines = capfd.readouterr().err.splitlines()
    header = re.compile(
        rf"\[venv\] uv lock failed in {re.escape(str(project))} \(exit [1-9][0-9]*\); "
        r"provisioning \.venv from pyproject\.toml instead:"
    )
    found = [i for i, line in enumerate(lines) if header.fullmatch(line)]
    assert len(found) == 1, f"exactly one lock failure header expected in: {lines!r}"
    block = _indented_block(lines, found[0])
    _index_of(block, "error: No solution found", prefix=True)
    _index_of(block, _MISSING_PACKAGE)


# --- `deps_update` after the provisioning sync failed (OPEN-WORK [230]) ------------------------------
# The whole command as `bmk deps update` runs it: provisioning syncs (and fails) before the pipeline, then
# the stage re-locks. The project has no dependencies, so the real dependency check asks PyPI nothing.


def test_an_update_that_leaves_the_lock_unchanged_reports_the_failed_sync_once(
    failing_project: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # The project already states its cooldown, so the update writes nothing and the re-lock is a no-op.
    pyproject = failing_project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[tool.uv]\nexclude-newer = "14 days"\n', encoding="utf-8"
    )

    rc = run_command(failing_project, (), command_prefix="deps_update", output_format=ToolOutputFormat.JSON)

    out, err = capfd.readouterr()
    headers = [line for line in (out + err).splitlines() if _HEADER.fullmatch(line.removesuffix(":"))]
    assert rc == 1
    assert len(headers) == 1, f"one failure block per run: {headers!r}"
    skip = f"{failing_project}: venv provisioning already failed above; uv.lock unchanged by the update, not retrying"
    assert f"[deps_update] (exit code: 1)\n{skip}\n" in out
    assert err.count(_MARKER) == 1, "uv's reason, from the one sync that ran"


def test_an_update_that_changes_the_lock_reports_its_resync_inside_the_stage(
    failing_project: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    # No cooldown yet: the update writes bmk's default into [tool.uv], so the re-lock records it.
    rc = run_command(failing_project, (), command_prefix="deps_update", output_format=ToolOutputFormat.JSON)

    out, err = capfd.readouterr()
    assert rc == 1
    assert "(no output captured)" not in out
    stage = out[out.index("[deps_update] (exit code: 1)\n") :].rstrip("\n").splitlines()
    block = _indented_block(stage, _header_index(stage, colon=True))
    _index_of(block, "error: Failed to build", prefix=True)
    assert stage[-1] == f"{failing_project}: uv sync from uv.lock failed after the floor update"
    assert err.count(_MARKER) == 1, "the provisioning sync's report, on stderr as before"
