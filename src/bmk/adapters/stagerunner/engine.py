"""Stage-runner engine: run a pipeline as sequential batches with parallel stages.

Stages are grouped by ``order``; batches run in sequence (fail-fast between
them), and stages within a batch run concurrently on a thread pool. Thread-based
concurrency is right here because every stage is subprocess-bound and releases
the GIL while waiting on its child.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from bmk.domain.stages import (
    PipelineSummary,
    StageResult,
    group_into_batches,
    normalize_returncode,
)

from .model import Stage, StageContext
from .output import (
    CapturingSink,
    OutputSink,
    PassthroughSink,
    SupportsWrite,
    report_batch_failures,
    report_success_summary,
)
from .signals import install_signal_handlers


def _sink_for(stage: Stage, ctx: StageContext, out: SupportsWrite) -> OutputSink:
    """Capture output for later (JSON mode) unless the stage is interactive."""
    if ctx.output_format != "text" and not stage.interactive:
        return CapturingSink()
    return PassthroughSink(out)


def run_stage(stage: Stage, ctx: StageContext, out: SupportsWrite) -> StageResult:
    """Run one stage, returning its normalized result and captured output."""
    sink = _sink_for(stage, ctx, out)
    start = time.monotonic()
    returncode = normalize_returncode(stage.action(ctx, sink))
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

    def run_one(stage: Stage) -> StageResult:
        return run_stage(stage, ctx, out)

    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
        return list(pool.map(run_one, batch))


def run_pipeline(stages: Sequence[Stage], ctx: StageContext, *, out: SupportsWrite | None = None) -> int:
    """Run a whole pipeline; return the first failing exit code, or 0.

    Batches run in order with fail-fast between them. On success in JSON mode a
    single summary line is emitted; on failure the failing stages' captured
    output is shown.
    """
    stream = out if out is not None else sys.stdout
    quiet = ctx.output_format != "text"
    batches = group_into_batches(list(stages), key=lambda stage: stage.order)

    with install_signal_handlers():
        for batch in batches:
            results = run_batch(batch, ctx, stream)
            failures = [r for r in results if r.returncode != 0]
            if failures:
                report_batch_failures(results, quiet=quiet, out=stream)
                return failures[0].returncode

    report_success_summary(
        PipelineSummary("pass", len(batches), len(stages), None),
        quiet=quiet,
        out=stream,
    )
    return 0
