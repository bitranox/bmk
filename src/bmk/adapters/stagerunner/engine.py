"""Stage-runner engine: run a pipeline as sequential batches with parallel stages.

Stages are grouped by ``order``; batches run in sequence (fail-fast between
them), and stages within a batch run concurrently on a thread pool. Thread-based
concurrency is right here because every stage is subprocess-bound and releases
the GIL while waiting on its child.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from bmk.domain.enums import ToolOutputFormat
from bmk.domain.stages import (
    PipelineSummary,
    StageResult,
    group_into_batches,
    normalize_returncode,
)

from .output import (
    CapturingSink,
    OutputSink,
    PassthroughSink,
    PrefixedLockedSink,
    SupportsWrite,
    report_batch_failures,
    report_success_summary,
)
from .signals import install_signal_handlers

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .model import Stage, StageContext


def _sink_for(stage: Stage, ctx: StageContext, out: SupportsWrite, *, lock: threading.Lock | None) -> OutputSink:
    """Pick the output sink for a stage.

    JSON mode captures each non-interactive stage for show-on-failure. Text mode streams
    live: a lone or interactive stage passes straight through, but a stage sharing a
    concurrent batch (``lock`` set) goes through a lock-guarded, ``[stage]``-prefixed sink
    so parallel stages do not interleave mid-line.
    """
    if ctx.output_format is not ToolOutputFormat.TEXT and not stage.interactive:
        return CapturingSink()
    if lock is not None and not stage.interactive:
        return PrefixedLockedSink(out, lock, f"[{stage.name}] ")
    return PassthroughSink(out)


def run_stage(
    stage: Stage, ctx: StageContext, out: SupportsWrite, *, lock: threading.Lock | None = None
) -> StageResult:
    """Run one stage, returning its normalized result and captured output.

    An exception from the action (e.g. a crash in an in-process helper) is
    reported as a stage failure with the traceback captured, rather than crashing
    the runner - matching how a subprocess stage's non-zero exit is handled.
    ``SystemExit`` (raised by the signal handler) is a ``BaseException`` and is
    intentionally not caught here.
    """
    sink = _sink_for(stage, ctx, out, lock=lock)
    start = time.monotonic()
    try:
        returncode = normalize_returncode(stage.action(ctx, sink))
    except Exception:  # a stage action crash is a stage failure, not a harness crash
        sink.write(f"\n{stage.name} raised an unexpected error:\n{traceback.format_exc()}")
        returncode = 1
    return StageResult(
        name=stage.name,
        returncode=returncode,
        output=sink.getvalue(),
        duration_s=time.monotonic() - start,
    )


def run_batch(batch: list[Stage], ctx: StageContext, out: SupportsWrite) -> list[StageResult]:
    """Run a batch of same-order stages, preserving declaration order in results."""
    if len(batch) == 1:
        return [run_stage(batch[0], ctx, out)]

    # Text mode streams live, so a concurrent batch needs a shared lock to keep parallel
    # stages' lines whole and attributed; JSON mode captures per stage and needs none.
    lock = threading.Lock() if ctx.output_format is ToolOutputFormat.TEXT else None

    def run_one(stage: Stage) -> StageResult:
        return run_stage(stage, ctx, out, lock=lock)

    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
        return list(pool.map(run_one, batch))


def run_pipeline(stages: Sequence[Stage], ctx: StageContext, *, out: SupportsWrite | None = None) -> int:
    """Run a whole pipeline; return the first failing exit code, or 0.

    Batches run in order with fail-fast between them. On success in JSON mode a
    single summary line is emitted; on failure the failing stages' captured
    output is shown.
    """
    stream = out if out is not None else sys.stdout
    quiet = ctx.output_format is not ToolOutputFormat.TEXT
    batches = group_into_batches(list(stages), key=lambda stage: stage.order)

    with install_signal_handlers():
        for batch in batches:
            results = run_batch(batch, ctx, stream)
            failures = [r for r in results if r.returncode != 0]
            if failures:
                report_batch_failures(results, quiet=quiet, out=stream)
                return failures[0].returncode

    report_success_summary(
        PipelineSummary("pass", len(batches), len(stages)),
        quiet=quiet,
        out=stream,
    )
    return 0
