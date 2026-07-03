"""Stage actions: how a stage does its work.

- :func:`run_argv` / :class:`ToolAction` spawn an external tool via an argv list
  (never ``shell=True`` - the cross-OS, injection-safe contract).
- :class:`HelperAction` calls a migrated Python helper in-process.
- :class:`PipelineAction` runs another pipeline (the delegator pattern).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from bmk.domain.stages import normalize_returncode

from . import signals
from .model import StageContext
from .output import OutputSink


def run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
    """Run ``argv`` in the project dir, stream combined output to ``sink``.

    Uses an argv list with ``shell=False`` for cross-OS behaviour and to avoid
    shell interpolation. The child is tracked so a signal handler can terminate
    it mid-run.
    """
    proc = subprocess.Popen(  # noqa: S603 - argv list, never shell=True
        list(argv),
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
