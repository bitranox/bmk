"""Pure stage-ordering primitives (no I/O, no subprocess, no framework deps).

These types and functions model how the stage runner orders and groups work,
independent of any execution mechanism. They live in the domain layer so both
the CLI adapter and the stage-runner engine share one definition.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import groupby
from typing import TypeVar

T = TypeVar("T")


def normalize_returncode(code: int) -> int:
    """Convert negative signal return codes to the POSIX 128+N convention.

    ``subprocess`` reports a signal-killed child as a negative value (``-2`` for
    SIGINT); POSIX shells report ``128 + N`` (``130``). Callers compare against
    shell exit codes, so normalize here.
    """
    return 128 + abs(code) if code < 0 else code


def group_into_batches(items: Sequence[T], key: Callable[[T], int]) -> list[list[T]]:
    """Group items into ascending-key batches; items sharing a key form one batch.

    Declaration order is preserved within a batch. This mirrors the semantics the
    ``{prefix}_NN_*`` filename glob gave the shell runner, where ``NN`` is the
    stage order and equal ``NN`` values ran in parallel.
    """
    order = sorted(range(len(items)), key=lambda i: key(items[i]))
    batches: list[list[T]] = []
    for _, index_group in groupby(order, key=lambda i: key(items[i])):
        indices = sorted(index_group)  # restore declaration order inside the batch
        batches.append([items[i] for i in indices])
    return batches


@dataclass(frozen=True, slots=True)
class StageResult:
    """Outcome of running a single stage."""

    name: str
    returncode: int
    output: str
    duration_s: float


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    """Aggregate outcome of running a whole pipeline."""

    result: str
    stages: int
    scripts: int
    first_failure: str | None
