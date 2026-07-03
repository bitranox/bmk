"""Stage actions: how a stage does its work.

- :func:`run_argv` / :class:`ToolAction` spawn an external tool via an argv list
  (never ``shell=True`` - the cross-OS, injection-safe contract).
- :class:`HelperAction` calls a migrated Python helper in-process.
- :class:`PipelineAction` runs another pipeline (the delegator pattern).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

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


class ToolActionWithSetup:
    """Run a best-effort setup argv, then the main tool argv, into one sink.

    Both run through :func:`run_argv`, so their output is captured and shown only on
    failure (JSON mode). Setup is best-effort: its exit code does not by itself fail
    the stage, the main tool decides. This lets a transient ``uv`` hiccup pass when
    pip is already current, while a genuinely-missing pip still fails via the tool.
    """

    def __init__(
        self,
        setup_argv: Callable[[StageContext], list[str]],
        build_argv: Callable[[StageContext], list[str]],
    ) -> None:
        self._setup_argv = setup_argv
        self._build_argv = build_argv

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        run_argv(self._setup_argv(ctx), ctx, sink)  # best-effort; output captured
        return run_argv(self._build_argv(ctx), ctx, sink)


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
