"""Tests for the deps / deps_update pipelines (in-process helper calls)."""

from __future__ import annotations

import shlex
import shutil
from typing import TYPE_CHECKING, Any

import pytest
from uv_stub import LOCK_MARKER

from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink
from bmk.adapters.stagerunner.registry import PIPELINES, PORTED_PREFIXES
from bmk.domain.enums import ToolOutputFormat, VenvProvisioning

if TYPE_CHECKING:
    from pathlib import Path

    from uv_stub import StubUv


def _ctx(
    tmp_path: Path,
    output_format: ToolOutputFormat = ToolOutputFormat.JSON,
    env: dict[str, str] | None = None,
    venv_provisioning: VenvProvisioning = VenvProvisioning.NOT_ATTEMPTED,
) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=output_format,
        python_cmd="python3",
        package_name="x",
        env=env if env is not None else {},
        show_warnings=True,
        venv_provisioning=venv_provisioning,
    )


def _make_venv(path: Path) -> Path:
    """Create a directory the venv resolver accepts."""
    from bmk.adapters.stagerunner.venv import venv_python

    path.mkdir(parents=True, exist_ok=True)
    (path / "pyvenv.cfg").write_text("home = /usr\n")
    interpreter = venv_python(path)
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("")
    return path


def test_deps_pipelines_registered_and_ported() -> None:
    assert [s.name for s in PIPELINES["deps"]] == ["deps"]
    assert [s.name for s in PIPELINES["deps_update"]] == ["deps_update"]
    assert {"deps", "deps_update"} <= PORTED_PREFIXES


def test_deps_action_calls_helper_with_pyproject_and_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def fake_main(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(_dependencies, "main", fake_main)

    rc = PIPELINES["deps"][0].action(_ctx(tmp_path, ToolOutputFormat.JSON), CapturingSink())
    assert rc == 0
    assert captured["pyproject"] == tmp_path / "pyproject.toml"
    assert captured["quiet"] is True
    assert not captured.get("update")


def test_deps_action_not_quiet_in_text_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps"][0].action(_ctx(tmp_path, ToolOutputFormat.TEXT), CapturingSink())
    assert captured["quiet"] is False


def test_deps_update_action_sets_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps_update"][0].action(_ctx(tmp_path, ToolOutputFormat.JSON), CapturingSink())
    assert captured["update"] is True
    assert captured["pyproject"] == tmp_path / "pyproject.toml"


def test_deps_update_targets_the_project_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The project venv's interpreter reaches the helper."""
    from bmk.adapters.stagerunner.helpers import _dependencies
    from bmk.adapters.stagerunner.venv import venv_python

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)
    venv = _make_venv(tmp_path / ".venv")

    PIPELINES["deps_update"][0].action(_ctx(tmp_path), CapturingSink())

    assert captured["python"] == str(venv_python(venv))


def test_deps_update_targets_the_uv_project_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UV_PROJECT_ENVIRONMENT redirects the install target."""
    from bmk.adapters.stagerunner.helpers import _dependencies
    from bmk.adapters.stagerunner.venv import venv_python

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)
    venv = _make_venv(tmp_path / ".venv-win")

    PIPELINES["deps_update"][0].action(_ctx(tmp_path, env={"UV_PROJECT_ENVIRONMENT": ".venv-win"}), CapturingSink())

    assert captured["python"] == str(venv_python(venv))


def test_deps_update_passes_no_target_without_a_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a project venv the target is None, never bmk's own interpreter.

    Regression guard: falling back to ctx.python_cmd here is what let a project
    install its dependencies into whatever environment launched bmk.
    """
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake)

    PIPELINES["deps_update"][0].action(_ctx(tmp_path), CapturingSink())

    assert captured["python"] is None


@pytest.mark.os_posix
def test_deps_update_locks_the_project_and_syncs_its_own_venv_from_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_uv: StubUv
) -> None:
    """After the floors are judged the stage re-locks, then syncs the project's own venv from the lock.

    ``_dependencies.main`` is replaced only to receive the ``LockedProject`` it is handed (the real
    one asks PyPI for every floor); the lock and the sync then run for real against the stub ``uv``.
    """
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake_main(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake_main)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    venv = _make_venv(tmp_path / ".venv-win")

    PIPELINES["deps_update"][0].action(_ctx(tmp_path, env={"UV_PROJECT_ENVIRONMENT": ".venv-win"}), CapturingSink())
    locked = captured["locked"]

    assert locked.upgrade() is True
    last = stub_uv.calls()[-1]
    assert (list(last.argv), last.cwd) == (["uv", "lock", "--upgrade"], tmp_path.resolve())
    assert locked.sync() is True
    sync = next(c for c in reversed(stub_uv.calls()) if c.argv[:2] == ("uv", "sync"))
    assert "--locked" in sync.argv
    assert sync.project_environment == str(venv)


def test_deps_update_has_nothing_to_sync_without_a_project_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bmk.adapters.stagerunner.helpers import _dependencies

    captured: dict[str, Any] = {}

    def _fake_main(**kw: Any) -> int:
        captured.update(kw)
        return 0

    monkeypatch.setattr(_dependencies, "main", _fake_main)

    PIPELINES["deps_update"][0].action(_ctx(tmp_path), CapturingSink())

    assert captured["locked"].sync() is None


# --- deps_update after a failed provisioning: one report per run, inside the stage (OPEN-WORK [230]) ---
# `run_command` provisions the venv before the pipeline; `deps_update` then re-locks and re-syncs. When the
# provisioning sync already failed and the re-lock changed nothing, a second sync can only fail the same
# way, so its block would print twice. When it does re-sync, its report must land in the stage's capture,
# or JSON mode shows the failed stage as '(no output captured)'.

_SYNC_HEADER = "[venv] uv sync from uv.lock failed for .venv (exit 1; venv afterwards: venv)"
# The real `_dependencies.main` runs: a project with no dependencies and its own cooldown asks PyPI nothing.
_PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.uv]\nexclude-newer = "14 days"\n'
# What uv 0.13.0 writes for that project; `main` reads the cutoff back from it before the re-lock.
_UV_LOCK = (
    'version = 1\nrevision = 5\nrequires-python = ">=3.10"\n\n[options]\n'
    'exclude-newer = "0001-01-01T00:00:00Z"\nexclude-newer-span = "P14D"\n\n'
    '[[package]]\nname = "demo"\nversion = "0.1.0"\nsource = { virtual = "." }\n'
)
# Every succeeding stub `uv lock` writes that lock, as uv does - including the one `main` runs in a scratch
# project to read the cutoff back. Written whole each time, its bytes do not change between runs.
_LOCK_WRITE = "printf '%s\\n' " + " ".join(shlex.quote(line) for line in _UV_LOCK.splitlines()) + " > uv.lock"
# ...unless every run also stamps it with the stub's pid, like an upgrade that moved a pin.
_LOCK_MOVES = _LOCK_WRITE + ' && echo "# lock written by stub pid $$" >> uv.lock'


def _skip_line(project: Path) -> str:
    return f"{project}: venv provisioning already failed above; uv.lock unchanged by the update, not retrying"


@pytest.fixture
def deps_project(tmp_path: Path, stub_uv: StubUv, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A dependency-free project beside the stub ``uv``, its venv at the default ``.venv``."""
    _ = stub_uv  # requested for its PATH and lock-dir setup
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    monkeypatch.delenv("BMK_NO_VENV_SYNC", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (project / "uv.lock").write_text(_UV_LOCK, encoding="utf-8")
    return project


def _sync_calls(stub_uv: StubUv) -> int:
    return sum(1 for argv in stub_uv.commands() if argv[:2] == ["uv", "sync"])


@pytest.mark.os_posix
def test_a_failed_provisioning_is_reported_once_when_the_update_leaves_the_lock_unchanged(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str]
) -> None:
    from bmk.adapters.cli.commands._shared import run_command

    stub_uv.install(sync_rc=1, lock_aftermath=_LOCK_WRITE)

    rc = run_command(deps_project, (), command_prefix="deps_update", output_format=ToolOutputFormat.JSON)

    out, err = capfd.readouterr()
    assert rc == 1, "the venv is still not what the lock pins"
    assert (out + err).count(_SYNC_HEADER) == 1, f"one failure block per run:\n{out}\n{err}"
    assert _sync_calls(stub_uv) == 1, "an unchanged lock is not synced a second time"
    assert f"[deps_update] (exit code: 1)\n{_skip_line(deps_project)}\n" in out
    assert "(no output captured)" not in out


@pytest.mark.os_posix
def test_a_failed_provisioning_that_left_no_venv_still_degrades_instead_of_failing_the_stage(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str]
) -> None:
    """With no venv there is no re-sync to skip: the stage passes and the gates fall back, as before."""
    from bmk.adapters.cli.commands._shared import run_command

    stub_uv.install(venv_rc=1, lock_aftermath=_LOCK_WRITE)

    rc = run_command(deps_project, (), command_prefix="deps_update", output_format=ToolOutputFormat.JSON)

    out, err = capfd.readouterr()
    assert rc == 0, f"a provisioning failure degrades, it does not abort:\n{out}\n{err}"
    assert not (deps_project / ".venv").exists()
    assert _sync_calls(stub_uv) == 0
    assert "already failed above" not in out + err


@pytest.mark.os_posix
@pytest.mark.parametrize("provisioning", ["NOT_ATTEMPTED", "FAILED", "PROVISIONED"])
def test_a_resync_after_the_update_reports_into_the_stage_capture(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str], provisioning: str
) -> None:
    _make_venv(deps_project / ".venv")
    stub_uv.install(sync_rc=1, lock_aftermath=_LOCK_MOVES)
    ctx = _ctx(deps_project, venv_provisioning=VenvProvisioning[provisioning])
    sink = CapturingSink()

    rc = PIPELINES["deps_update"][0].action(ctx, sink)

    captured = sink.getvalue()
    lines = captured.splitlines()
    assert rc == 1
    assert _sync_calls(stub_uv) == 1, "a lock the update changed is synced, whatever provisioning did"
    assert lines[0] == _SYNC_HEADER + ":", "the JSON-mode report, header first, lands in the capture"
    assert lines[-1] == f"{deps_project}: uv sync from uv.lock failed after the floor update"
    assert _SYNC_HEADER not in "".join(capfd.readouterr()), "nothing of it bypasses the stage capture"


@pytest.mark.os_posix
@pytest.mark.parametrize("provisioning", ["NOT_ATTEMPTED", "PROVISIONED"])
def test_an_unchanged_lock_is_still_synced_unless_this_run_saw_the_sync_fail(
    deps_project: Path, stub_uv: StubUv, provisioning: str
) -> None:
    _make_venv(deps_project / ".venv")
    stub_uv.install(lock_aftermath=_LOCK_WRITE)
    ctx = _ctx(deps_project, venv_provisioning=VenvProvisioning[provisioning])

    rc = PIPELINES["deps_update"][0].action(ctx, CapturingSink())

    assert rc == 0
    assert _sync_calls(stub_uv) == 1, "only a sync already seen failing is skipped"


@pytest.mark.os_posix
def test_a_text_mode_resync_still_reports_on_stderr(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str]
) -> None:
    """Text mode streams live; the stage's passthrough sink is stdout, so the report stays on stderr."""
    _make_venv(deps_project / ".venv")
    stub_uv.install(sync_rc=1, lock_aftermath=_LOCK_MOVES)
    sink = CapturingSink()

    rc = PIPELINES["deps_update"][0].action(_ctx(deps_project, ToolOutputFormat.TEXT), sink)

    err = capfd.readouterr().err
    assert rc == 1
    assert sink.getvalue() == ""
    assert f"{_SYNC_HEADER}\n" in err, "text mode: the bare header, uv's own output streamed above it"
    assert f"{deps_project}: uv sync from uv.lock failed after the floor update\n" in err


@pytest.mark.os_posix
def test_bmk_no_venv_sync_also_skips_the_deps_update_resync(deps_project: Path, stub_uv: StubUv) -> None:
    _make_venv(deps_project / ".venv")
    stub_uv.install(lock_aftermath=_LOCK_MOVES)
    ctx = _ctx(deps_project, env={"BMK_NO_VENV_SYNC": "1"})

    rc = PIPELINES["deps_update"][0].action(ctx, CapturingSink())

    assert rc == 0
    assert ["uv", "lock", "--upgrade"] in stub_uv.commands(), "the lock is still upgraded"
    assert _sync_calls(stub_uv) == 0, "BMK_NO_VENV_SYNC=1 opts out of every sync, this one too"


# --- a failed `uv lock --upgrade` says why (OPEN-WORK [260]): uv's own reason reaches the stage's capture ---

_UPGRADE_FAILED = "uv lock --upgrade failed after the floor update"


@pytest.mark.os_posix
def test_a_failed_upgrade_lock_reports_uv_s_reason_into_the_stage_capture(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str]
) -> None:
    stub_uv.install(lock_upgrade_rc=2, lock_aftermath=_LOCK_WRITE)
    sink = CapturingSink()

    rc = PIPELINES["deps_update"][0].action(_ctx(deps_project), sink)

    captured = sink.getvalue()
    assert rc == 1
    assert LOCK_MARKER in captured, captured
    assert captured.index(LOCK_MARKER) < captured.index(_UPGRADE_FAILED), "uv's reason, then bmk's summary"
    assert LOCK_MARKER not in "".join(capfd.readouterr()), "nothing of it bypasses the stage capture"


@pytest.mark.os_posix
def test_a_failed_upgrade_lock_in_json_mode_shows_the_reason_in_the_stage_block(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str]
) -> None:
    from bmk.adapters.cli.commands._shared import run_command

    stub_uv.install(lock_upgrade_rc=2, lock_aftermath=_LOCK_WRITE)

    rc = run_command(deps_project, (), command_prefix="deps_update", output_format=ToolOutputFormat.JSON)

    out, err = capfd.readouterr()
    block = out[out.index("[deps_update] (exit code: 1)") :] if "[deps_update] (exit code: 1)" in out else ""
    assert rc == 1
    assert LOCK_MARKER in block, f"{out}\n{err}"
    assert "(no output captured)" not in out


@pytest.mark.os_posix
def test_a_text_mode_upgrade_lock_failure_shows_uv_s_reason_once(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str]
) -> None:
    """Text mode streams uv's stderr live, so a report under the header would repeat it."""
    stub_uv.install(lock_upgrade_rc=2, lock_aftermath=_LOCK_WRITE)
    sink = CapturingSink()

    rc = PIPELINES["deps_update"][0].action(_ctx(deps_project, ToolOutputFormat.TEXT), sink)

    out, err = capfd.readouterr()
    assert rc == 1
    assert (out + err + sink.getvalue()).count(LOCK_MARKER) == 1, f"{out}\n{err}"


# --- what `make test` users see: its first stage `update_deps` runs the `deps_update` PIPELINE, so the
# failed stage block nests inside the outer stage's capture (PipelineAction), never on stderr. ---


class _CountingSink(CapturingSink):
    """A capture that also counts its writes, so a line written in two calls shows up."""

    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def write(self, text: str) -> None:
        self.writes += 1
        super().write(text)


@pytest.mark.os_posix
def test_make_tests_update_deps_stage_nests_the_skip_line_in_its_capture(
    deps_project: Path, stub_uv: StubUv, capfd: pytest.CaptureFixture[str]
) -> None:
    from bmk.adapters.stagerunner.actions import PipelineAction

    _make_venv(deps_project / ".venv")
    stub_uv.install(lock_aftermath=_LOCK_WRITE)
    ctx = _ctx(deps_project, venv_provisioning=VenvProvisioning.FAILED)
    outer = CapturingSink()

    rc = PipelineAction("deps_update")(ctx, outer)

    out, err = capfd.readouterr()
    assert rc == 1
    assert f"[deps_update] (exit code: 1)\n{_skip_line(deps_project)}\n" in outer.getvalue(), outer.getvalue()
    assert out == "", "the nested block goes into the outer stage's capture, not straight to stdout"
    assert err == "", "nothing of it bypasses the capture"


@pytest.mark.os_posix
def test_the_skip_line_is_one_write(deps_project: Path, stub_uv: StubUv) -> None:
    """One write per line, like the venv reports: a line written in two calls can be split by a parallel writer."""
    _make_venv(deps_project / ".venv")
    stub_uv.install(lock_aftermath=_LOCK_WRITE)
    sink = _CountingSink()

    rc = PIPELINES["deps_update"][0].action(_ctx(deps_project, venv_provisioning=VenvProvisioning.FAILED), sink)

    assert rc == 1
    assert sink.getvalue() == f"{_skip_line(deps_project)}\n"
    assert sink.writes == 1


@pytest.mark.os_agnostic
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_a_cooldown_uv_refuses_is_reported_inside_the_deps_update_capture(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Real uv judges `[tool.uv] exclude-newer`; its refusal must land in the stage's JSON-mode capture."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n[tool.uv]\nexclude-newer = "not-a-date"\n', encoding="utf-8"
    )
    sink = CapturingSink()

    rc = PIPELINES["deps_update"][0].action(_ctx(tmp_path), sink)

    err = capfd.readouterr().err
    assert rc == 1
    assert sink.getvalue().startswith(f"{pyproject}: "), sink.getvalue()
    assert "cooldown" in sink.getvalue()
    assert str(pyproject) not in err, err
