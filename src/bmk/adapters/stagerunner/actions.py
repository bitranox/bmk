"""Stage actions: how a stage does its work.

- :func:`run_argv` / :class:`ToolAction` spawn an external tool via an argv list
  (never ``shell=True`` - the cross-OS, injection-safe contract).
- :class:`HelperAction` calls a migrated Python helper in-process.
- :class:`PipelineAction` runs another pipeline (the delegator pattern).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from bmk.domain.stages import normalize_returncode

from . import signals
from .model import StageContext
from .output import OutputSink


def _resolve_executable(argv: Sequence[str], env: Mapping[str, str]) -> list[str]:
    """Resolve ``argv[0]`` to an absolute path against the child env's PATH.

    On Windows, ``CreateProcess`` locates the executable using the *parent*
    process's ``PATH``, not the ``env`` passed to the child - so prepending bmk's
    tool-venv bin dir to ``env['PATH']`` (see ``context._prepend_tool_bin_to_path``)
    is not enough to find bare-name tools like ``ruff`` / ``pytest`` / ``pyright``
    installed in that venv. Resolve ``argv[0]`` here via ``shutil.which`` against the
    child ``PATH`` (which also honours ``PATHEXT`` on Windows, appending ``.exe``) so
    the spawn receives an absolute path. Absolute argv[0] (e.g. ``sys.executable``)
    and tools on the inherited PATH (``git`` / ``uv``) resolve unchanged; a tool that
    cannot be found is left as-is so ``Popen`` raises the original ``FileNotFoundError``.
    """
    resolved = list(argv)
    if resolved:
        found = shutil.which(resolved[0], path=env.get("PATH"))
        if found:
            resolved[0] = found
    return resolved


def run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
    """Run ``argv`` in the project dir, stream combined output to ``sink``.

    Uses an argv list with ``shell=False`` for cross-OS behaviour and to avoid
    shell interpolation. ``argv[0]`` is resolved to an absolute path against the
    child ``PATH`` first (see :func:`_resolve_executable`) so bmk's own toolchain is
    found on Windows. The child is tracked so a signal handler can terminate it
    mid-run.

    The child is never left running: if reading its output raises, the ``finally``
    kills and reaps it. Without that, an exception mid-stream abandons a live child -
    ``text=True`` decodes strictly, so a tool emitting a single undecodable byte raises
    ``UnicodeDecodeError`` here and would orphan the whole tool run (verified).
    """
    proc = subprocess.Popen(  # noqa: S603 - argv list, never shell=True
        _resolve_executable(argv, ctx.env),
        cwd=ctx.project_dir,
        env=dict(ctx.env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    signals.register(proc)
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                sink.write(line)
        return normalize_returncode(proc.wait())
    finally:
        # poll() is None only when the child outlived the try block, i.e. an exception
        # skipped the wait() above. On the normal path this is a no-op.
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        signals.unregister(proc)


class ToolAction:
    """Run an external tool; ``build_argv`` produces the argv from the context."""

    def __init__(self, build_argv: Callable[[StageContext], list[str]]) -> None:
        self._build_argv = build_argv

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        return run_argv(self._build_argv(ctx), ctx, sink)


class PipAuditAction:
    """Run pip-audit against a run-time-resolved, self-healing interpreter.

    ``resolve_python`` picks the interpreter to audit when the stage runs (the pinned
    project ``.venv`` while it exists, else bmk's own interpreter), so pip-audit does
    not crash on a ``PIPAPI_PYTHON_LOCATION`` that an earlier ``clean`` removed (the
    ``.venv``-vs-clean race). ``PIPAPI_PYTHON_LOCATION`` is repointed at the resolved
    interpreter for both child processes. A current pip is bootstrapped into it first
    (best-effort - uv venvs ship no pip); its exit code does not fail the stage, only
    pip-audit's does. Both run through :func:`run_argv` so their output is captured and
    shown only on failure (JSON mode).

    If pip-audit fails *and* the resolved interpreter has since vanished (a ``clean``
    removed the project ``.venv`` between resolution and the audit - the TOCTOU window a
    concurrent clean could still open), it retries once against bmk's own interpreter,
    which is never a clean target. Real audit findings (interpreter still present) are
    not retried.
    """

    def __init__(
        self,
        resolve_python: Callable[[StageContext], str],
        setup_argv: Callable[[StageContext], list[str]],
        build_argv: Callable[[StageContext], list[str]],
    ) -> None:
        self._resolve_python = resolve_python
        self._setup_argv = setup_argv
        self._build_argv = build_argv

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        python = self._resolve_python(ctx)
        rc = self._audit(ctx, python, sink)
        if rc != 0 and python != ctx.python_cmd and not Path(python).exists():
            rc = self._audit(ctx, ctx.python_cmd, sink)  # pinned interpreter vanished mid-audit; self-heal
        return rc

    def _audit(self, ctx: StageContext, python: str, sink: OutputSink) -> int:
        audit_ctx = replace(ctx, env={**ctx.env, "PIPAPI_PYTHON_LOCATION": python})
        run_argv(self._setup_argv(audit_ctx), audit_ctx, sink)  # best-effort pip bootstrap
        return run_argv(self._build_argv(audit_ctx), audit_ctx, sink)


class HelperAction:
    """Call a migrated Python helper in-process; ``func`` returns an exit code."""

    def __init__(self, func: Callable[[StageContext], int]) -> None:
        self._func = func

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        return self._func(ctx)


class PipelineAction:
    """Run another registered pipeline (the pipeline-composes-pipeline delegator).

    Replaces the shell delegator that re-entered the stagerunner with a different
    ``BMK_COMMAND_PREFIX``. The sub-pipeline writes into the parent stage's sink,
    so in JSON mode its output is captured and shown only if the delegate fails.
    """

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        # Deferred imports: registry imports this module, and the engine is a
        # sibling; importing them at call time avoids an import cycle.
        from . import registry
        from .engine import run_pipeline

        return run_pipeline(list(registry.PIPELINES[self._prefix]), ctx, out=sink)
