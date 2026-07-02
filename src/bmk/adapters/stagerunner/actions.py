"""Stage actions: how a stage does its work.

- :func:`run_argv` / :class:`ToolAction` spawn an external tool via an argv list
  (never ``shell=True`` - the cross-OS, injection-safe contract).
- :class:`HelperAction` calls a migrated Python helper in-process.
- :class:`PipelineAction` runs another pipeline (the delegator pattern).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
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


class ShellStageAction:
    """Run a legacy ``bmk_makescripts`` shell/PowerShell override script.

    Bridges downstream projects still shipping shell overrides during the
    migration. Retired in the final phase with the rest of the shell layer.
    """

    def __init__(self, script: Path) -> None:
        self._script = script

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        if self._script.suffix == ".ps1":
            argv = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(self._script), *ctx.args]
        else:
            argv = [str(self._script), *ctx.args]
        return run_argv(argv, ctx, sink)
