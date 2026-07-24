"""Output sinks and reporting for the stage runner.

In JSON mode a stage's output is buffered and shown only if the stage fails; on
all-pass a single JSON summary line is emitted. In text mode output passes
straight through. This mirrors the bash runner's quiet/verbose behaviour.
"""

from __future__ import annotations

import io
import re
import sys
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import threading

    from bmk.domain.stages import PipelineSummary, StageResult


class SupportsWrite(Protocol):
    """Anything with a text ``write`` (a stream or a sink).

    Lets a nested pipeline write its output into a parent stage's sink while a
    top-level pipeline writes to ``sys.stdout`` - both satisfy this.
    """

    def write(self, text: str, /) -> object: ...


# A trailing "N warnings" tool summary is not itself a warning line to surface.
_WARNING_SUMMARY = re.compile(r"\b\d+\s+warnings?\b", re.IGNORECASE)

# Per-tool exit-code explanations, consulted by the reporter on failure. This
# replaces the per-script ``explain_exit_code`` case-statements with one table.
EXIT_HINTS: dict[str, dict[int, str]] = {
    "ruff": {1: "Lint violations found", 2: "Configuration or CLI error"},
    "git-commit": {
        1: "Commit failed (nothing to commit or pre-commit hook failed)",
        128: "Fatal git error",
        129: "Git usage error",
    },
}


def hint_for(tool: str, code: int) -> str | None:
    """Return a human hint for ``tool`` exiting with ``code``, or ``None``."""
    return EXIT_HINTS.get(tool, {}).get(code)


def extract_warnings(output: str) -> list[str]:
    """Return warning lines from ``output``, excluding a trailing count summary."""
    lines = [line for line in output.splitlines() if "warning" in line.lower()]
    return [line for line in lines if not _WARNING_SUMMARY.search(line)]


class OutputSink(Protocol):
    """A destination for a stage's combined stdout/stderr stream."""

    def write(self, text: str) -> None: ...

    def getvalue(self) -> str: ...


class CapturingSink:
    """Buffers output in memory; shown by the reporter only on failure."""

    def __init__(self) -> None:
        self._buffer = io.StringIO()

    def write(self, text: str) -> None:
        self._buffer.write(text)

    def getvalue(self) -> str:
        return self._buffer.getvalue()


class PassthroughSink:
    """Writes output straight to a target stream (default ``sys.stdout``)."""

    def __init__(self, target: SupportsWrite | None = None) -> None:
        self._target: SupportsWrite = target if target is not None else sys.stdout

    def write(self, text: str) -> None:
        self._target.write(text)

    def getvalue(self) -> str:
        return ""


class PrefixedLockedSink:
    """Passthrough for a concurrent TEXT-mode batch: whole, attributed lines.

    Several stages in a batch run at once and, in text mode, stream to the same
    stream. Writing straight through interleaves their output mid-line with no way to
    tell which tool a line came from. This sink buffers a partial line until its
    newline, then, under a lock shared across the batch, writes each complete line with
    a ``[stage] `` prefix - so lines are never torn and always attributed.

    ``getvalue`` doubles as the end-of-stage flush (it is called exactly once, when the
    stage finishes): any trailing text with no newline is emitted then. Like
    :class:`PassthroughSink` it captures nothing, so it returns ``""`` and the
    failure/success reporting paths behave exactly as they do for a live text stream.
    """

    def __init__(self, target: SupportsWrite, lock: threading.Lock, prefix: str) -> None:
        self._target = target
        self._lock = lock
        self._prefix = prefix
        self._pending = ""

    def write(self, text: str) -> None:
        self._pending += text
        if "\n" not in self._pending:
            return
        head, self._pending = self._pending.rsplit("\n", 1)
        with self._lock:
            for line in head.split("\n"):
                self._target.write(f"{self._prefix}{line}\n")

    def getvalue(self) -> str:
        if self._pending:
            with self._lock:
                self._target.write(f"{self._prefix}{self._pending}\n")
            self._pending = ""
        return ""


def report_batch_failures(results: list[StageResult], *, quiet: bool, out: SupportsWrite) -> None:
    """Print name, exit code, and captured output for each failed stage."""
    failures = [r for r in results if r.returncode != 0]
    if not failures:
        return
    for result in failures:
        out.write(f"\n[{result.name}] (exit code: {result.returncode})\n")
        out.write(result.output or "(no output captured)\n")
    out.write("\n")


def report_success_summary(summary: PipelineSummary, *, quiet: bool, out: SupportsWrite) -> None:
    """Emit a single JSON summary line on success in quiet (JSON) mode."""
    if quiet:
        out.write(f'{{"result":"{summary.result}","stages":{summary.stages},"scripts":{summary.scripts}}}\n')
