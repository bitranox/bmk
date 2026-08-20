"""bmk's shared tool environment is guarded against being rebuilt under a running bmk.

bmk installs itself once per machine, into uv's tool dir, and the generated Makefile
upgrades that env before EVERY target. When a new release appears on PyPI the first
`make` that notices rebuilds the env in place while any other bmk, in any other repo,
is still running out of it. The symptom is an ImportError inside bmk's OWN dependencies
(`pip_api._hash`, `pydantic.functional_serializers`) that clears on a re-run, so it reads
as a flake rather than as the environment vanishing mid-gate.

Every bmk process therefore holds a SHARED lock on the tools root for its lifetime, and
the Makefile takes that lock EXCLUSIVE around the upgrade.

Why not simply share uv's own `<tools>/.lock`, which uv really does honour (measured:
`uv tool install` blocks on an exclusive flock held there)? Because `uv tool upgrade` and
`uv tool list` block on it too, and the upgrade runs before every make target. A
gate-lifetime shared lock on uv's file would make every `make` on the machine wait for the
longest-running gate - the machine-wide serialisation this work exists to remove.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import bmk_toollock
from bmk.adapters.cli.exit_codes import ExitCode

if TYPE_CHECKING:
    from collections.abc import Iterator

_SRC = str(Path(__file__).resolve().parent.parent / "src")

#: Long enough that a loaded machine does not fail the control, short enough that a
#: genuinely blocked case does not stall the suite.
_SHORT_WAIT = "1"


def _child_env(lock_path: Path, **extra: str) -> dict[str, str]:
    """Environment for a guard subprocess, pinned at a throwaway lock file."""
    env = {**os.environ, "PYTHONPATH": _SRC, bmk_toollock.LOCK_PATH_ENV: str(lock_path)}
    env.pop(bmk_toollock.LOCK_HELD_ENV, None)
    env.update(extra)
    return env


@pytest.fixture
def holder() -> Iterator[object]:
    """Hold the tool lock from a genuinely separate process, shared or exclusive.

    A separate process, not a thread: the guarantee under test is cross-PROCESS. On POSIX
    an flock is owned by the open file description, so two fds in one process would test
    this module's own bookkeeping rather than the thing that fails in the field.
    """
    procs: list[subprocess.Popen[str]] = []

    def hold(path: Path, *, mode: str) -> None:
        code = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {_SRC!r})
            import bmk_toollock
            ok = bmk_toollock.acquire({str(path)!r}, exclusive={mode == "exclusive"!r}, timeout=10)
            print("held" if ok else "failed", flush=True)
            time.sleep(120)
        """)
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        procs.append(proc)
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "held", "holder never acquired the lock"

    yield hold
    for proc in procs:
        proc.kill()
        proc.wait(timeout=10)


def _guard(
    lock_path: Path, *guard_args: str, marker: Path | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run `python -m bmk_toollock ... -- <cmd>`, where <cmd> touches ``marker``."""
    tail = [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"] if marker else [sys.executable, "-c", "pass"]
    return subprocess.run(
        [sys.executable, "-m", "bmk_toollock", *guard_args, "--", *tail],
        env=_child_env(lock_path, **env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


@pytest.mark.os_agnostic
def test_a_uv_tool_env_is_recognised_by_its_receipt(tmp_path: Path) -> None:
    """`uv-receipt.toml` beside the interpreter is what marks a uv TOOL env.

    A plain `uv venv` has no receipt, so a pytest run or `uvx bmk` locks nothing and test
    runs cannot collide with the machine's real tool env.
    """
    env_dir = tmp_path / "tools" / "bmk"
    env_dir.mkdir(parents=True)
    assert bmk_toollock.tool_env_root(env_dir) is None, "a venv without a receipt is not a tool env"

    (env_dir / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    assert bmk_toollock.tool_env_root(env_dir) == tmp_path / "tools"


@pytest.mark.os_agnostic
def test_the_lock_lives_in_the_tools_root_not_the_env_being_replaced(tmp_path: Path) -> None:
    """The lock must outlive the very directory it guards.

    `uv tool install --reinstall` DELETES `<tools>/bmk/`. A lock file inside it would go
    with it, and on POSIX a lock on a deleted inode does not conflict with a lock on the
    new file at the same path - so the guard would fail SILENTLY OPEN, which is worse than
    having no guard at all.
    """
    env_dir = tmp_path / "tools" / "bmk"
    env_dir.mkdir(parents=True)
    (env_dir / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")

    root = bmk_toollock.tool_env_root(env_dir)
    assert root is not None
    lock = bmk_toollock.lock_path(root)

    assert env_dir not in lock.parents, "the lock must not sit inside the env a reinstall deletes"
    assert lock.parent == tmp_path / "tools"


@pytest.mark.os_agnostic
def test_two_shared_holders_do_not_exclude_each_other(tmp_path: Path, holder: object) -> None:
    """Concurrent bmk processes must never serialise against each other.

    This is the whole point of a shared mode: two gates in two repos run at once. If they
    excluded each other the guard would be the machine-wide stall it exists to remove.
    """
    lock = tmp_path / "t.lock"
    holder(lock, mode="shared")  # type: ignore[operator]

    assert bmk_toollock.acquire(lock, exclusive=False, timeout=5), "a second reader must get in"


@pytest.mark.os_agnostic
def test_a_running_bmk_blocks_the_upgrade(tmp_path: Path, holder: object) -> None:
    """THE guarantee: an upgrade may not proceed while any bmk is running out of the env."""
    lock = tmp_path / "t.lock"
    marker = tmp_path / "upgraded"
    holder(lock, mode="shared")  # type: ignore[operator]

    result = _guard(lock, "--exclusive", "--timeout", _SHORT_WAIT, "--on-timeout", "skip", marker=marker)

    assert not marker.exists(), "the upgrade ran while a bmk was still using the environment"
    assert result.returncode == 0, "a skipped upgrade is not a failure; the next make picks it up"


@pytest.mark.os_agnostic
def test_the_upgrade_excludes_a_starting_bmk(tmp_path: Path, holder: object) -> None:
    """The other direction: a bmk must not start reading an env mid-rebuild."""
    lock = tmp_path / "t.lock"
    holder(lock, mode="exclusive")  # type: ignore[operator]

    assert not bmk_toollock.acquire(lock, exclusive=False, timeout=1), "a reader got in during a rebuild"


@pytest.mark.os_agnostic
def test_a_skipped_upgrade_does_not_run_the_command(tmp_path: Path, holder: object) -> None:
    """`--on-timeout skip` must exit 0 AND leave the command unrun.

    Exiting 0 having silently RUN the upgrade would defeat the guard while looking healthy.
    """
    lock = tmp_path / "t.lock"
    marker = tmp_path / "ran"
    holder(lock, mode="exclusive")  # type: ignore[operator]

    result = _guard(lock, "--exclusive", "--timeout", _SHORT_WAIT, "--on-timeout", "skip", marker=marker)

    assert result.returncode == 0
    assert not marker.exists()


@pytest.mark.os_agnostic
def test_a_repair_that_cannot_get_the_lock_fails_rather_than_skipping(tmp_path: Path, holder: object) -> None:
    """The REPAIR may not skip: skipping would leave a damaged env in place.

    It fails instead, and the Makefile falls through to its deliberately unguarded retry.
    """
    lock = tmp_path / "t.lock"
    marker = tmp_path / "ran"
    holder(lock, mode="exclusive")  # type: ignore[operator]

    result = _guard(lock, "--exclusive", "--timeout", _SHORT_WAIT, "--on-timeout", "fail", marker=marker)

    assert result.returncode == bmk_toollock.EXIT_TIMEOUT
    assert not marker.exists()


@pytest.mark.os_agnostic
def test_the_timeout_exit_code_matches_the_cli_enum() -> None:
    """`bmk_toollock` is stdlib-only and cannot import the CLI's enum, so pin the value.

    Without this the two spellings of 110 drift apart silently.
    """
    assert bmk_toollock.EXIT_TIMEOUT == ExitCode.TIMEOUT


@pytest.mark.os_agnostic
def test_a_nested_make_never_rebuilds_the_env_its_parent_is_running_out_of(tmp_path: Path) -> None:
    """The inherited token makes a nested guard skip, instead of deadlocking on itself.

    A custom pipeline stage may run `make`, and `build_context` copies the environment into
    every child. Waiting for the parent's own shared lock would hang forever; mutating the
    env the parent is running out of is exactly the bug. So it does neither: it skips.
    """
    lock = tmp_path / "t.lock"
    marker = tmp_path / "ran"

    result = _guard(
        lock,
        "--exclusive",
        "--timeout",
        _SHORT_WAIT,
        "--on-timeout",
        "fail",
        marker=marker,
        **{bmk_toollock.LOCK_HELD_ENV: "12345"},
    )

    assert result.returncode == 0, "a nested guard must not fail the build"
    assert not marker.exists(), "a nested make must never rebuild its parent's environment"


@pytest.mark.os_agnostic
def test_an_unlockable_location_still_runs_the_command(tmp_path: Path) -> None:
    """Never worse than today: a filesystem without the primitive must not break `make`.

    An unlockable path is not evidence of a concurrent holder, so the command proceeds.
    """
    unusable = tmp_path / "missing-dir" / "deep" / "t.lock"
    marker = tmp_path / "ran"

    result = _guard(unusable, "--exclusive", "--timeout", _SHORT_WAIT, "--on-timeout", "fail", marker=marker)

    assert result.returncode == 0, "an unlockable location must degrade, not fail the build"
    assert marker.exists(), "the command must still run when the lock is unavailable"


@pytest.mark.os_agnostic
def test_the_guard_returns_the_commands_own_exit_code(tmp_path: Path) -> None:
    """A real upgrade failure must reach make, not be masked by the guard."""
    lock = tmp_path / "t.lock"
    result = subprocess.run(
        [sys.executable, "-m", "bmk_toollock", "--exclusive", "--", sys.executable, "-c", "raise SystemExit(7)"],
        env=_child_env(lock),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 7


@pytest.mark.os_agnostic
def test_holding_shared_publishes_the_token_for_children(tmp_path: Path) -> None:
    """`hold_shared` must advertise itself, or a nested guard cannot know to skip."""
    lock = tmp_path / "t.lock"
    code = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {_SRC!r})
        import bmk_toollock
        bmk_toollock.hold_shared()
        print(os.environ.get(bmk_toollock.LOCK_HELD_ENV, "<unset>"), flush=True)
    """)
    result = subprocess.run(
        [sys.executable, "-c", code], env=_child_env(lock), capture_output=True, text=True, timeout=60, check=False
    )
    assert result.stdout.strip().isdigit(), f"expected the holder's pid, got {result.stdout!r}"


@pytest.mark.os_agnostic
def test_a_waiting_guard_says_so_rather_than_stalling_silently(tmp_path: Path, holder: object) -> None:
    """An invisible multi-minute wait and a hang are indistinguishable to a person."""
    lock = tmp_path / "t.lock"
    holder(lock, mode="shared")  # type: ignore[operator]

    result = _guard(lock, "--exclusive", "--timeout", "2", "--on-timeout", "skip")

    assert "lock" in result.stderr.lower(), f"a wait must announce itself; stderr was {result.stderr!r}"


@pytest.mark.os_agnostic
def test_an_uncontended_guard_does_not_measurably_slow_make(tmp_path: Path) -> None:
    """This runs before EVERY target, so the uncontended path has to stay cheap."""
    lock = tmp_path / "t.lock"
    start = time.monotonic()
    result = _guard(lock, "--exclusive", "--timeout", "10", "--on-timeout", "skip")
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed < 5.0, f"uncontended acquisition took {elapsed:.2f}s"


# --- Detecting a replacement the lock could not prevent ---------------------------------
#
# A lock only helps once BOTH sides take it. A repo whose Makefile predates this change is
# an unguarded writer until its next `make` regenerates it, and a hand-run
# `uv tool install bmk` is unguarded forever. Neither can be stopped from here, but the
# victim can at least be told what happened instead of reporting an ImportError in
# `pip_api._hash` that reads as a flake.


@pytest.mark.os_agnostic
def test_a_replaced_environment_is_detectable_after_the_fact(tmp_path: Path) -> None:
    """uv rewrites the receipt when it reinstalls, so its stat is the fingerprint."""
    env_dir = tmp_path / "bmk"
    env_dir.mkdir()
    receipt = env_dir / bmk_toollock.RECEIPT_NAME
    receipt.write_text("[tool]\n", encoding="utf-8")

    before = bmk_toollock.env_fingerprint(env_dir)
    assert before is not None
    assert not bmk_toollock.env_changed(before, env_dir), "an untouched environment must look untouched"

    receipt.write_text("[tool]\nrewritten = true\n", encoding="utf-8")
    assert bmk_toollock.env_changed(before, env_dir), "a rewritten receipt must be noticed"


@pytest.mark.os_agnostic
def test_an_environment_that_vanished_counts_as_changed(tmp_path: Path) -> None:
    """`--reinstall` deletes the directory before writing the new one."""
    env_dir = tmp_path / "bmk"
    env_dir.mkdir()
    receipt = env_dir / bmk_toollock.RECEIPT_NAME
    receipt.write_text("[tool]\n", encoding="utf-8")
    before = bmk_toollock.env_fingerprint(env_dir)
    assert before is not None

    receipt.unlink()
    assert bmk_toollock.env_changed(before, env_dir)


@pytest.mark.os_agnostic
def test_bmk_holds_the_shared_lock_while_it_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reader side is what the whole guard rests on, so prove bmk really takes it."""
    from bmk.adapters.cli.main import main as cli_main
    from bmk.composition import build_production

    lock = tmp_path / "t.lock"
    monkeypatch.setenv(bmk_toollock.LOCK_PATH_ENV, str(lock))
    monkeypatch.delenv(bmk_toollock.LOCK_HELD_ENV, raising=False)

    cli_main(["--version"], services_factory=build_production)

    assert lock.exists(), "bmk did not take the shared tool lock"
    assert os.environ.get(bmk_toollock.LOCK_HELD_ENV), "children cannot tell the lock is held"


@pytest.mark.os_agnostic
def test_a_failing_command_explains_a_replaced_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The message must fire on a FAILING run whose environment moved under it.

    Not only on an ImportError: a replaced env usually kills a spawned pyright or pip-audit,
    which surfaces as a non-zero stage rather than as an exception inside bmk.
    """
    main_mod = importlib.import_module("bmk.adapters.cli.main")
    from bmk.composition import build_production

    monkeypatch.setenv(bmk_toollock.LOCK_PATH_ENV, str(tmp_path / "t.lock"))
    monkeypatch.setattr(main_mod.bmk_toollock, "env_changed", _replaced)

    main_mod.main(["no-such-command-at-all"], services_factory=build_production)

    assert "environment was replaced" in capsys.readouterr().err.lower()


@pytest.mark.os_agnostic
def test_a_normal_failure_is_not_blamed_on_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The anti-cheat: an ordinary failure must NOT claim the environment moved."""
    main_mod = importlib.import_module("bmk.adapters.cli.main")
    from bmk.composition import build_production

    monkeypatch.setenv(bmk_toollock.LOCK_PATH_ENV, str(tmp_path / "t.lock"))
    monkeypatch.setattr(main_mod.bmk_toollock, "env_changed", _untouched)

    main_mod.main(["no-such-command-at-all"], services_factory=build_production)

    assert "environment was replaced" not in capsys.readouterr().err.lower()


# --- The recipe itself, not just the module ---------------------------------------------
#
# Every other Makefile assertion in this repo is a TEXT assertion. Those cannot tell that
# make parses the recipe, that `$(wildcard ...)` expands where expected, or that the guard
# resolves the same lock file the readers use. This one runs it.
#
# It found a real defect in its own first draft: a fake tool env without a `pyvenv.cfg` puts
# `sys.prefix` at the base interpreter, so the guard correctly decided it was not a tool env
# and let the upgrade through. A fake that is not faithful proves nothing.


def _replaced(_before: tuple[int, int, int] | None, _env: Path | None = None) -> bool:
    """Stand in for `env_changed` reporting that the tool env moved under this run."""
    return True


def _untouched(_before: tuple[int, int, int] | None, _env: Path | None = None) -> bool:
    """Stand in for `env_changed` reporting an ordinary, self-inflicted failure."""
    return False


def _fake_tool_env(root: Path) -> Path:
    """A directory uv would recognise as a tool env, faithful enough for `sys.prefix`."""
    env = root / "tools" / "bmk"
    (env / "bin").mkdir(parents=True)
    (env / bmk_toollock.RECEIPT_NAME).write_text("[tool]\n", encoding="utf-8")
    # pyvenv.cfg is what makes a symlinked interpreter report sys.prefix INSIDE the env.
    home = Path(sys.executable).resolve().parent
    (env / "pyvenv.cfg").write_text(f"home = {home}\ninclude-system-site-packages = false\n", encoding="utf-8")
    (env / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    return env


@pytest.mark.os_posix
@pytest.mark.skipif(sys.platform == "win32", reason="drives GNU make through a POSIX shell")
def test_the_generated_recipe_really_defers_to_a_running_bmk(tmp_path: Path, holder: object) -> None:
    """Run the SHIPPED `_ensure_bmk` against a stub `uv` and see whether it mutates."""
    if shutil.which("make") is None:
        pytest.skip("make is not installed")

    env = _fake_tool_env(tmp_path)
    tools, mutations = env.parent, tmp_path / "mutations.log"

    binder = tmp_path / "bin"
    binder.mkdir()
    stub = binder / "uv"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then\n'
        f'  if [ "$3" = "--bin" ]; then echo "{tools}/bin"; else echo "{tools}"; fi\n  exit 0\nfi\n'
        'if [ "$1" = "tool" ]; then\n'
        f'  echo MUTATED >> "{mutations}"\nfi\nexit 0\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    project = tmp_path / "proj"
    project.mkdir()
    template = Path(__file__).resolve().parent.parent / "src" / "bmk" / "makefile" / "Makefile"
    # The shipped timeout is 10s, deliberately. Shortened here so one test does not add ten
    # seconds to every run; that the REAL value is bounded and skippable is asserted by
    # tests/test_makefile_template_integrity.py, which reads the shipped text.
    (project / "Makefile").write_text(
        template.read_text(encoding="utf-8").replace("--timeout 10 ", "--timeout 1 "), encoding="utf-8"
    )

    run_env = {**os.environ, "PATH": f"{binder}{os.pathsep}{os.environ['PATH']}", "PYTHONPATH": _SRC}
    run_env.pop(bmk_toollock.LOCK_HELD_ENV, None)

    def make() -> None:
        subprocess.run(["make", "_ensure_bmk"], cwd=project, env=run_env, capture_output=True, timeout=120, check=False)

    make()
    assert mutations.exists(), "the uncontended upgrade never ran, so this test proves nothing"
    mutations.unlink()

    holder(bmk_toollock.lock_path(tools), mode="shared")  # type: ignore[operator]
    make()
    assert not mutations.exists(), "the upgrade rebuilt the environment while a bmk was using it"
