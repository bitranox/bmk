"""Tests for stage-runner actions (argv/tool/helper)."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from bmk.adapters.stagerunner import actions as actions_mod
from bmk.adapters.stagerunner.actions import HelperAction, PipAuditAction, ToolAction, run_argv
from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink, OutputSink
from bmk.domain.enums import ToolOutputFormat


def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=ToolOutputFormat.JSON,
        python_cmd=sys.executable,
        package_name="x",
        env=dict(os.environ),
        show_warnings=True,
    )


def _ctx_with_path(tmp_path: Path, path_value: str) -> StageContext:
    return StageContext(
        project_dir=tmp_path,
        args=(),
        output_format=ToolOutputFormat.JSON,
        python_cmd=sys.executable,
        package_name="x",
        env={**os.environ, "PATH": path_value},
        show_warnings=True,
    )


def test_run_argv_resolves_bare_name_tool_against_env_path(tmp_path: Path) -> None:
    # run_argv resolves a bare-name executable (as tools.py emits: ["ruff", ...]) against
    # the child env PATH before spawning, so bmk's own toolchain - installed next to
    # sys.executable - is found even on Windows, where CreateProcess otherwise ignores the
    # child env PATH for the executable lookup. Use the running interpreter as a
    # guaranteed-present executable whose dir is the only thing on PATH.
    name = Path(sys.executable).name  # e.g. "python.exe" / "python3"
    ctx = _ctx_with_path(tmp_path, str(Path(sys.executable).parent))
    sink = CapturingSink()
    rc = run_argv([name, "-c", "print('resolved')"], ctx, sink)
    assert rc == 0
    assert "resolved" in sink.getvalue()


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal-0 liveness probe")
def test_run_argv_kills_the_child_when_reading_its_output_raises(tmp_path: Path) -> None:
    # text=True decodes strictly, so a tool emitting one undecodable byte raises
    # UnicodeDecodeError while run_argv is iterating proc.stdout. Before the finally
    # killed it, that abandoned a LIVE child: the stage failed but the tool kept running
    # unreaped. The child reports its own pid so this asserts on the real process rather
    # than patching subprocess.
    pid_file = tmp_path / "child.pid"
    code = (
        "import sys, os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "sys.stdout.buffer.write(b'\\xff\\n')\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(30)\n"
    )

    with pytest.raises(UnicodeDecodeError):
        run_argv([sys.executable, "-c", code], _ctx(tmp_path), CapturingSink())

    child_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        # Killed AND reaped by the finally, so the pid is gone - not merely a zombie.
        os.kill(child_pid, 0)


def test_run_argv_raises_when_bare_tool_not_found(tmp_path: Path) -> None:
    # An unresolvable tool is left unchanged so the spawn raises the original error
    # (FileNotFoundError / WinError 2), rather than being silently swallowed.
    with pytest.raises(FileNotFoundError):
        run_argv(["definitely-not-a-real-tool-xyz"], _ctx_with_path(tmp_path, str(tmp_path)), CapturingSink())


def test_run_argv_captures_output_and_returncode(tmp_path: Path) -> None:
    sink = CapturingSink()
    rc = run_argv([sys.executable, "-c", "print('hi'); raise SystemExit(3)"], _ctx(tmp_path), sink)
    assert rc == 3
    assert "hi" in sink.getvalue()


def test_run_argv_normalizes_zero(tmp_path: Path) -> None:
    sink = CapturingSink()
    rc = run_argv([sys.executable, "-c", "print('ok')"], _ctx(tmp_path), sink)
    assert rc == 0
    assert "ok" in sink.getvalue()


def test_tool_action_builds_argv_from_context(tmp_path: Path) -> None:
    action = ToolAction(lambda ctx: [sys.executable, "-c", "print('built')"])
    sink = CapturingSink()
    assert action(_ctx(tmp_path), sink) == 0
    assert "built" in sink.getvalue()


def test_helper_action_calls_func_in_process(tmp_path: Path) -> None:
    seen: list[StageContext] = []

    def helper(ctx: StageContext) -> int:
        seen.append(ctx)
        return 5

    action = HelperAction(helper)
    assert action(_ctx(tmp_path), CapturingSink()) == 5
    assert seen and seen[0].project_dir == tmp_path


def test_pip_audit_action_repoints_interpreter_and_runs_setup_then_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
        calls.append((list(argv), ctx.env["PIPAPI_PYTHON_LOCATION"]))
        return 0 if argv[0] == "setup" else 7

    monkeypatch.setattr(actions_mod, "run_argv", fake_run_argv)
    # Resolver reports the interpreter to audit (an existing one, so the self-heal retry
    # does not fire); both children must see it via env.
    action = PipAuditAction(lambda ctx: ctx.python_cmd, lambda _ctx: ["setup"], lambda _ctx: ["main"])
    ctx = _ctx(tmp_path)
    rc = action(ctx, CapturingSink())
    assert [argv for argv, _ in calls] == [["setup"], ["main"]]  # setup (pip bootstrap) before pip-audit
    assert all(pipapi == ctx.python_cmd for _, pipapi in calls)  # PIPAPI_PYTHON_LOCATION repointed
    assert rc == 7  # the stage's exit code is pip-audit's, not the best-effort setup's


def test_pip_audit_action_setup_failure_does_not_fail_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
        calls.append(list(argv))
        return 1 if argv[0] == "setup" else 0  # pip bootstrap fails, pip-audit succeeds

    monkeypatch.setattr(actions_mod, "run_argv", fake_run_argv)
    action = PipAuditAction(lambda ctx: ctx.python_cmd, lambda _ctx: ["setup"], lambda _ctx: ["main"])
    rc = action(_ctx(tmp_path), CapturingSink())
    assert calls == [["setup"], ["main"]]  # best-effort setup does not short-circuit pip-audit
    assert rc == 0  # setup's non-zero is ignored; pip-audit decides


def test_pip_audit_action_retries_own_interpreter_when_pinned_vanished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / ".venv" / "bin" / "python"  # resolved then removed (TOCTOU): does not exist
    seen_pipapi: list[str] = []

    def fake_run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
        if argv[0] == "setup":
            return 0
        pipapi = ctx.env["PIPAPI_PYTHON_LOCATION"]
        seen_pipapi.append(pipapi)
        return 1 if pipapi == str(missing) else 0  # audit fails on the vanished pin, passes on fallback

    monkeypatch.setattr(actions_mod, "run_argv", fake_run_argv)
    action = PipAuditAction(lambda _ctx: str(missing), lambda _ctx: ["setup"], lambda _ctx: ["main"])
    ctx = _ctx(tmp_path)  # python_cmd == sys.executable, which exists
    rc = action(ctx, CapturingSink())
    assert seen_pipapi == [str(missing), ctx.python_cmd]  # first the vanished pin, then the self-heal retry
    assert rc == 0


def test_pip_audit_action_does_not_retry_real_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Interpreter still exists but pip-audit reports findings: a genuine failure, not the
    # race - must NOT be retried (retrying would mask real vulnerabilities).
    audits = 0

    def fake_run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
        nonlocal audits
        if argv[0] == "setup":
            return 0
        audits += 1
        return 1  # findings

    monkeypatch.setattr(actions_mod, "run_argv", fake_run_argv)
    action = PipAuditAction(lambda ctx: ctx.python_cmd, lambda _ctx: ["setup"], lambda _ctx: ["main"])
    rc = action(_ctx(tmp_path), CapturingSink())  # resolves to python_cmd, which exists
    assert rc == 1
    assert audits == 1  # no retry
