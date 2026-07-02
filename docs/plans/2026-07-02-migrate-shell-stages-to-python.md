# Migrate bmk Shell/PowerShell Stage Scripts to Cross-OS Python  -  Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `bitranox:process-agents-subagent-driven-development` (recommended) or `bitranox:process-plan-executor` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Also apply `bitranox:python-clean-architecture`, `bitranox:process-test-driven-development`, and `bitranox:coding-python-use-modern-libraries` throughout.

**Goal:** Replace bmk's 39 `.sh` + 39 `.ps1` stage scripts and their bash/PowerShell stagerunner with a single, tested, cross-OS Python stage-runner, eliminating the dual-maintenance twin-script burden.

**Architecture:** A pure-domain stage model (`bmk/domain/stages.py`) plus a side-effecting engine (`bmk/adapters/stagerunner/`) that discovers stages from a declarative in-code registry, runs order-groups sequentially with within-group parallelism (`concurrent.futures.ThreadPoolExecutor`), captures output shown only on failure in JSON mode, and forwards to tools via argv-list `subprocess.run` (never `shell=True`). Pipelines cut over one at a time behind a `BMK_RUNNER` selector; both paths coexist until the last pipeline lands.

**Tech Stack:** Python 3.10+, stdlib `subprocess` / `concurrent.futures` / `signal` / `tomllib`, pytest (real-objects style), pyright strict, ruff, import-linter.

## Context

**Why this change.** bmk *is* a build/test orchestration tool, yet its own stage pipeline violates the org's standing rule ("write the logic in Python, not bash or jq; bash only as a thin launcher shim"). Today every stage exists twice  -  a `.sh` and a hand-kept `.ps1` twin  -  which silently drift. The recent pip-audit `PIPAPI_PYTHON_LOCATION` bug (release 2.9.6) was exactly this class of shell-level environment subtlety; a single tested Python implementation would have caught it in a unit test. The 39 shell scripts are effectively untested  -  the 1044-test suite covers the Python core, not the shell layer. Meanwhile 13 Python helper modules (`_clean.py`, `_coverage.py`, ...) already do all the real work; the shell scripts are thin wrappers plus one orchestrator (`_btx_stagerunner.{sh,ps1}`, ~399 lines each).

**Intended outcome.** One cross-OS Python codebase for the whole pipeline; the `.ps1` twins and the "every `.sh` must have a `.ps1` twin" CLAUDE.md rule are retired; the pyright `exclude` on `makescripts/` shrinks to nothing; stages become type-checked, unit-testable data; downstream projects customize via a safe declarative **TOML overlay** (user decision) rather than dropping shell files.

**User decisions (locked in for this plan):**
- **Override mechanism:** TOML overlay only  -  projects add/remove/replace stages declaratively (argv-list actions) via `[tool.bmk.pipelines]` in `pyproject.toml` or `bmk_makescripts/stages.toml`. No Python-plugin hook.
- **Legacy shell overrides:** Keep executing legacy `bmk_makescripts/*.sh` overrides (via a `ShellStageAction`) *during* the migration for backward compatibility; remove that path in the final phase once the TOML overlay is in place.

## Global Constraints

- **Python floor:** 3.10+ (`tomllib` is 3.11+; use `tomli` fallback already implied by project deps, or `rtoml` which is a project dep  -  prefer `rtoml` for reads to match the codebase).
- **Clean Architecture / import-linter:** domain (`bmk.domain`) stays pure  -  no subprocess, threads, signals, I/O, or framework imports; may not import `bmk.adapters`/`bmk.composition`. The engine lives in `bmk.adapters.stagerunner` (adapters layer) and is called from `bmk.adapters.cli.commands` (same layer  -  legal). Run `lint-imports` after each task.
- **Typing:** pyright `strict`. New modules must pass strict and be *removed* from the `[tool.pyright] exclude` list as they land. Follow the CLAUDE.md "typed facade" rule for any untyped third-party surface.
- **Subprocess safety:** always argv lists, `cwd=project_dir`, `check=False`, never `shell=True` (keeps the existing `# noqa: S603` boundary contained).
- **Style:** ruff line-length 120; small focused functions (project style); comments explain *why*, not *what*; docs describe current code, no migration narrative in docstrings.
- **No attribution:** never add `Co-Authored-By` or Claude mentions to commits/PRs.
- **Test discipline:** TDD  -  write the failing test first, watch it fail, implement minimal, watch it pass, commit. Use real objects over mocks per `tests/conftest.py` conventions; mock only the `subprocess`/`signal` boundary.
- **Parity during migration:** a ported pipeline deletes **both** its `.sh` and `.ps1` at once (never one without the other).

---

## Target File Structure

**New (created):**
- `src/bmk/domain/stages.py`  -  pure model + ordering: `Stage`-agnostic `group_into_batches()`, `StageResult`, `PipelineSummary`, `normalize_returncode()` (lifted from `_shared.py`).
- `src/bmk/adapters/stagerunner/__init__.py`  -  package marker + public surface (`run_pipeline`, `PIPELINES`).
- `src/bmk/adapters/stagerunner/model.py`  -  `Stage` dataclass, `StageAction` Protocol, `StageContext` dataclass.
- `src/bmk/adapters/stagerunner/actions.py`  -  `run_argv`, `ToolAction`, `HelperAction`, `PipelineAction`, `ShellStageAction`.
- `src/bmk/adapters/stagerunner/output.py`  -  `OutputSink` protocol, `CapturingSink`, `PassthroughSink`, `extract_warnings`, exit-hint table, reporter functions.
- `src/bmk/adapters/stagerunner/signals.py`  -  live-`Popen` registry + `install_signal_handlers` context manager.
- `src/bmk/adapters/stagerunner/context.py`  -  `build_context()` (ports the env/venv/`PIPAPI_PYTHON_LOCATION` setup out of `execute_script`).
- `src/bmk/adapters/stagerunner/engine.py`  -  `run_stage`, `run_batch`, `run_pipeline`.
- `src/bmk/adapters/stagerunner/registry.py`  -  built-in `PIPELINES` dict; grows one pipeline per phase.
- `src/bmk/adapters/stagerunner/overrides.py`  -  TOML overlay load + merge; legacy `bmk_makescripts/*.sh` resolution (temporary).
- `src/bmk/adapters/stagerunner/helpers/`  -  the 13 migrated `_*.py` modules become a normal subpackage (imported, not dynamically loaded).
- `tests/test_stagerunner_*.py`  -  engine/model/actions/output/overrides tests.

**Modified:**
- `src/bmk/adapters/cli/commands/_shared.py`  -  add `BMK_RUNNER` selector; delegate ported prefixes to `run_pipeline` in-process; keep shell-out for unported prefixes; import `normalize_returncode` from domain.
- `pyproject.toml`  -  shrink `[tool.pyright] exclude`; drop `.ps1`/`.sh` wheel `include` globs as pipelines retire; (final phase) remove twin-parity rule references.
- `src/bmk/makescripts/`  -  delete `{prefix}_NN_*.{sh,ps1}` pairs as each pipeline ports; finally delete `_btx_stagerunner.{sh,ps1}`, `_resolve_python.*`, `_bump_lib.*`.

**Deleted (final phase):** `_loader.py` (dynamic-import shim no longer needed), `tests/test_makescripts_ps1.py`, `test_makescripts_shellcheck.py`, `test_makescripts_psscriptanalyzer.py`, and the `_shellcheck.py`/`_psscriptanalyzer.py` stages (they lint shell/ps1 sources that no longer exist in bmk itself  -  but see Risks re: target-project scripts).

---

## Phase 1  -  Domain model + engine + `clean` vertical slice

Goal: prove the whole spine end-to-end on the simplest pipeline (single-stage, one helper action), with both runner paths coexisting.

### Task 1: Pure stage-ordering primitives in the domain layer

**Files:**
- Create: `src/bmk/domain/stages.py`
- Test: `tests/test_domain_stages.py`

**Interfaces:**
- Produces: `normalize_returncode(code: int) -> int`; `group_into_batches(items: Sequence[T], key: Callable[[T], int]) -> list[list[T]]`; frozen dataclasses `StageResult(name: str, returncode: int, output: str, duration_s: float)` and `PipelineSummary(result: str, stages: int, scripts: int, first_failure: str | None)`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_domain_stages.py
from bmk.domain.stages import group_into_batches, normalize_returncode

def test_group_into_batches_groups_equal_keys_and_sorts() -> None:
    items = [("a", 40), ("b", 10), ("c", 40), ("d", 20)]
    batches = group_into_batches(items, key=lambda t: t[1])
    assert [[t[0] for t in b] for b in batches] == [["b"], ["d"], ["a", "c"]]

def test_group_into_batches_preserves_declaration_order_within_batch() -> None:
    items = [("a", 40), ("c", 40), ("b", 40)]
    batches = group_into_batches(items, key=lambda t: t[1])
    assert [t[0] for t in batches[0]] == ["a", "c", "b"]

def test_normalize_returncode_maps_signal_to_128_plus_n() -> None:
    assert normalize_returncode(-2) == 130
    assert normalize_returncode(0) == 0
    assert normalize_returncode(1) == 1
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_domain_stages.py -v`
Expected: FAIL  -  `ModuleNotFoundError: bmk.domain.stages`.

- [ ] **Step 3: Write minimal implementation**
```python
# src/bmk/domain/stages.py
"""Pure stage-ordering primitives (no I/O, no subprocess, no framework deps)."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import groupby
from typing import TypeVar

T = TypeVar("T")


def normalize_returncode(code: int) -> int:
    """Convert negative signal return codes to the POSIX 128+N convention."""
    return 128 + abs(code) if code < 0 else code


def group_into_batches(items: Sequence[T], key: Callable[[T], int]) -> list[list[T]]:
    """Group items into ascending-key batches; equal keys share one batch.

    Declaration order is preserved within a batch  -  the same semantics the
    ``{prefix}_NN_*`` filename glob gave, with NN being the stage order.
    """
    ordered = sorted(range(len(items)), key=lambda i: key(items[i]))
    batches: list[list[T]] = []
    for _, idx_group in groupby(ordered, key=lambda i: key(items[i])):
        idxs = sorted(idx_group)  # restore declaration order inside the batch
        batches.append([items[i] for i in idxs])
    return batches


@dataclass(frozen=True, slots=True)
class StageResult:
    name: str
    returncode: int
    output: str
    duration_s: float


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    result: str
    stages: int
    scripts: int
    first_failure: str | None
```

- [ ] **Step 4: Run tests + lint-imports**
Run: `pytest tests/test_domain_stages.py -v && lint-imports`
Expected: PASS; import-linter reports contracts kept.

- [ ] **Step 5: Commit**
```bash
git add src/bmk/domain/stages.py tests/test_domain_stages.py
git commit -m "feat(stagerunner): pure domain stage-ordering primitives"
```

### Task 2: Stage model, StageContext, and the StageAction protocol

**Files:**
- Create: `src/bmk/adapters/stagerunner/__init__.py`, `src/bmk/adapters/stagerunner/model.py`
- Test: `tests/test_stagerunner_model.py`

**Interfaces:**
- Produces:
  - `class StageAction(Protocol): def __call__(self, ctx: StageContext, sink: OutputSink) -> int: ...`
  - `@dataclass(frozen=True, slots=True) class Stage: name: str; order: int; action: StageAction; interactive: bool = False`
  - `@dataclass(frozen=True, slots=True) class StageContext: project_dir: Path; args: tuple[str, ...]; output_format: str; python_cmd: str; package_name: str; env: Mapping[str, str]; show_warnings: bool`
- Consumes: `OutputSink` from `output.py` (Task 3)  -  for this task, forward-reference it via `typing.TYPE_CHECKING` to avoid a cycle.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_stagerunner_model.py
from pathlib import Path
from bmk.adapters.stagerunner.model import Stage, StageContext

def test_stage_is_frozen_and_defaults_non_interactive() -> None:
    s = Stage(name="ruff_lint", order=40, action=lambda ctx, sink: 0)
    assert s.interactive is False
    assert s.order == 40

def test_stage_context_carries_project_dir_and_args() -> None:
    ctx = StageContext(
        project_dir=Path("/proj"), args=("--x",), output_format="json",
        python_cmd="python3", package_name="bmk", env={}, show_warnings=True,
    )
    assert ctx.project_dir == Path("/proj")
    assert ctx.args == ("--x",)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_stagerunner_model.py -v`
Expected: FAIL  -  module missing.

- [ ] **Step 3: Write minimal implementation**
```python
# src/bmk/adapters/stagerunner/model.py
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .output import OutputSink


@dataclass(frozen=True, slots=True)
class StageContext:
    project_dir: Path
    args: tuple[str, ...]
    output_format: str  # "json" | "text"
    python_cmd: str
    package_name: str
    env: Mapping[str, str]
    show_warnings: bool


class StageAction(Protocol):
    def __call__(self, ctx: StageContext, sink: OutputSink) -> int: ...


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    order: int
    action: StageAction
    interactive: bool = False
```
```python
# src/bmk/adapters/stagerunner/__init__.py
"""Cross-OS Python stage runner (replaces the bash/PowerShell stagerunner)."""
```

- [ ] **Step 4: Run tests + pyright + lint-imports**
Run: `pytest tests/test_stagerunner_model.py -v && pyright src/bmk/adapters/stagerunner/model.py && lint-imports`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add src/bmk/adapters/stagerunner/__init__.py src/bmk/adapters/stagerunner/model.py tests/test_stagerunner_model.py
git commit -m "feat(stagerunner): Stage model, StageContext, StageAction protocol"
```

### Task 3: Output sinks + reporter (capture-shown-only-on-failure)

**Files:**
- Create: `src/bmk/adapters/stagerunner/output.py`
- Test: `tests/test_stagerunner_output.py`

**Interfaces:**
- Produces:
  - `class OutputSink(Protocol): def write(self, text: str) -> None: ...; def getvalue(self) -> str: ...`
  - `class CapturingSink` (buffers to `io.StringIO`) and `class PassthroughSink` (writes to a target stream, default `sys.stdout`).
  - `def extract_warnings(output: str) -> list[str]`  -  lines matching `warning` (case-insensitive), excluding a trailing `N warnings?` summary (port of the shell `grep -i warning | grep -v -E '[0-9]+ warnings?'`).
  - `EXIT_HINTS: dict[str, dict[int, str]]` and `def hint_for(tool: str, code: int) -> str | None` (ports the per-script `explain_exit_code` case-statements into one table).
  - `def report_batch_failures(results: list[StageResult], *, quiet: bool, out: TextIO) -> None` and `def report_success_summary(summary: PipelineSummary, *, quiet: bool, out: TextIO) -> None`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_stagerunner_output.py
import io
from bmk.adapters.stagerunner.output import CapturingSink, extract_warnings, hint_for

def test_capturing_sink_buffers_text() -> None:
    sink = CapturingSink()
    sink.write("hello\n")
    sink.write("world\n")
    assert sink.getvalue() == "hello\nworld\n"

def test_extract_warnings_drops_summary_line() -> None:
    out = "src/a.py: warning: unused import\nfound 3 warnings\nok\n"
    assert extract_warnings(out) == ["src/a.py: warning: unused import"]

def test_hint_for_ruff_lint_violation() -> None:
    assert hint_for("ruff", 1) == "Lint violations found"
    assert hint_for("ruff", 99) is None
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_stagerunner_output.py -v`
Expected: FAIL  -  module missing.

- [ ] **Step 3: Write minimal implementation**
```python
# src/bmk/adapters/stagerunner/output.py
from __future__ import annotations

import io
import re
import sys
from typing import Protocol, TextIO

from bmk.domain.stages import PipelineSummary, StageResult

_WARNING_SUMMARY = re.compile(r"\b\d+\s+warnings?\b", re.IGNORECASE)

EXIT_HINTS: dict[str, dict[int, str]] = {
    "ruff": {1: "Lint violations found", 2: "Configuration or CLI error"},
    "git-commit": {1: "Commit failed (nothing to commit or pre-commit hook failed)",
                   128: "Fatal git error", 129: "Git usage error"},
    # extended per pipeline as ports land
}


def hint_for(tool: str, code: int) -> str | None:
    return EXIT_HINTS.get(tool, {}).get(code)


def extract_warnings(output: str) -> list[str]:
    lines = [ln for ln in output.splitlines() if "warning" in ln.lower()]
    return [ln for ln in lines if not _WARNING_SUMMARY.search(ln)]


class OutputSink(Protocol):
    def write(self, text: str) -> None: ...
    def getvalue(self) -> str: ...


class CapturingSink:
    def __init__(self) -> None:
        self._buf = io.StringIO()

    def write(self, text: str) -> None:
        self._buf.write(text)

    def getvalue(self) -> str:
        return self._buf.getvalue()


class PassthroughSink:
    def __init__(self, target: TextIO | None = None) -> None:
        self._target = target if target is not None else sys.stdout

    def write(self, text: str) -> None:
        self._target.write(text)

    def getvalue(self) -> str:
        return ""


def report_batch_failures(results: list[StageResult], *, quiet: bool, out: TextIO) -> None:
    for r in (r for r in results if r.returncode != 0):
        out.write(f"\n[{r.name}] (exit code: {r.returncode})\n")
        out.write(r.output or "(no output captured)\n")
    out.write("\n")


def report_success_summary(summary: PipelineSummary, *, quiet: bool, out: TextIO) -> None:
    if quiet:
        out.write(
            f'{{"result":"{summary.result}","stages":{summary.stages},'
            f'"scripts":{summary.scripts}}}\n'
        )
```

- [ ] **Step 4: Run tests + pyright**
Run: `pytest tests/test_stagerunner_output.py -v && pyright src/bmk/adapters/stagerunner/output.py`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add src/bmk/adapters/stagerunner/output.py tests/test_stagerunner_output.py
git commit -m "feat(stagerunner): output sinks, warning extraction, exit-hint table"
```

### Task 4: Actions (run_argv, ToolAction, HelperAction) + signal handling

**Files:**
- Create: `src/bmk/adapters/stagerunner/signals.py`, `src/bmk/adapters/stagerunner/actions.py`
- Test: `tests/test_stagerunner_actions.py`, `tests/test_stagerunner_signals.py`

**Interfaces:**
- Produces:
  - `def run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int`  -  `subprocess.Popen(list, cwd=ctx.project_dir, env=dict(ctx.env), stdout=PIPE, stderr=STDOUT, text=True)`, registers the live `Popen` in the signal registry, streams to `sink`, returns `normalize_returncode(proc.wait())`. No `shell=True`.
  - `class ToolAction`: wraps `build_argv: Callable[[StageContext], list[str]]`; `__call__` delegates to `run_argv`.
  - `class HelperAction`: wraps `func: Callable[[StageContext], int]`; `__call__` calls it in-process (see Task 5).
  - `signals.register(proc) / unregister(proc)`, `install_signal_handlers() -> ContextManager[None]` that on SIGINT/SIGTERM calls `.terminate()` on every live `Popen` then raises `SystemExit(128+N)`.
- Consumes: `StageContext`, `OutputSink`, `normalize_returncode`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_stagerunner_actions.py
import sys
from pathlib import Path
from bmk.adapters.stagerunner.actions import ToolAction, run_argv
from bmk.adapters.stagerunner.model import StageContext
from bmk.adapters.stagerunner.output import CapturingSink

def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(project_dir=tmp_path, args=(), output_format="json",
                        python_cmd=sys.executable, package_name="x", env={}, show_warnings=True)

def test_run_argv_captures_output_and_returncode(tmp_path: Path) -> None:
    sink = CapturingSink()
    rc = run_argv([sys.executable, "-c", "print('hi'); raise SystemExit(3)"], _ctx(tmp_path), sink)
    assert rc == 3
    assert "hi" in sink.getvalue()

def test_tool_action_builds_argv_from_context(tmp_path: Path) -> None:
    action = ToolAction(lambda ctx: [sys.executable, "-c", "print('ok')"])
    sink = CapturingSink()
    assert action(_ctx(tmp_path), sink) == 0
    assert "ok" in sink.getvalue()
```

- [ ] **Step 2: Run to verify it fails**
Run: `pytest tests/test_stagerunner_actions.py -v`
Expected: FAIL  -  module missing.

- [ ] **Step 3: Write minimal implementation** (signals.py first, then actions.py)
```python
# src/bmk/adapters/stagerunner/signals.py
from __future__ import annotations

import contextlib
import signal
import subprocess
import threading
from collections.abc import Iterator

_LIVE: set[subprocess.Popen[str]] = set()
_LOCK = threading.Lock()


def register(proc: subprocess.Popen[str]) -> None:
    with _LOCK:
        _LIVE.add(proc)


def unregister(proc: subprocess.Popen[str]) -> None:
    with _LOCK:
        _LIVE.discard(proc)


def _terminate_all() -> None:
    with _LOCK:
        procs = list(_LIVE)
    for p in procs:
        with contextlib.suppress(ProcessLookupError, OSError):
            p.terminate()


@contextlib.contextmanager
def install_signal_handlers() -> Iterator[None]:
    def handler(signum: int, _frame: object) -> None:
        _terminate_all()
        raise SystemExit(128 + signum)

    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    for s in previous:
        signal.signal(s, handler)
    try:
        yield
    finally:
        for s, prev in previous.items():
            signal.signal(s, prev)
```
```python
# src/bmk/adapters/stagerunner/actions.py
from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

from bmk.domain.stages import normalize_returncode

from . import signals
from .model import StageContext
from .output import OutputSink


def run_argv(argv: Sequence[str], ctx: StageContext, sink: OutputSink) -> int:
    proc = subprocess.Popen(  # noqa: S603  -  argv list, never shell=True
        list(argv), cwd=ctx.project_dir, env=dict(ctx.env),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    signals.register(proc)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sink.write(line)
        return normalize_returncode(proc.wait())
    finally:
        signals.unregister(proc)


class ToolAction:
    def __init__(self, build_argv: Callable[[StageContext], list[str]]) -> None:
        self._build_argv = build_argv

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        return run_argv(self._build_argv(ctx), ctx, sink)


class HelperAction:
    def __init__(self, func: Callable[[StageContext], int]) -> None:
        self._func = func

    def __call__(self, ctx: StageContext, sink: OutputSink) -> int:
        return self._func(ctx)
```

- [ ] **Step 4: Run tests + pyright**
Run: `pytest tests/test_stagerunner_actions.py tests/test_stagerunner_signals.py -v && pyright src/bmk/adapters/stagerunner/`
Expected: PASS. (Write `tests/test_stagerunner_signals.py`: launch a `sys.executable -c "import time; time.sleep(30)"` via `run_argv` in a thread, register fires, send SIGINT to a subprocess wrapper, assert 130 and empty live registry  -  see Risks: Signals for the exact fixture.)

- [ ] **Step 5: Commit**
```bash
git add src/bmk/adapters/stagerunner/signals.py src/bmk/adapters/stagerunner/actions.py tests/test_stagerunner_actions.py tests/test_stagerunner_signals.py
git commit -m "feat(stagerunner): argv/tool/helper actions + SIGINT/SIGTERM handling"
```

### Task 5: Migrate `_clean.py` into helpers/ and wire the `clean` HelperAction

**Files:**
- Create: `src/bmk/adapters/stagerunner/helpers/__init__.py`
- Move: `src/bmk/makescripts/_clean.py` -> `src/bmk/adapters/stagerunner/helpers/clean.py` (use `git mv`)
- Modify: `src/bmk/adapters/stagerunner/registry.py` (create), `pyproject.toml` (`[tool.pyright] exclude`  -  remove the moved file from exclusion by keeping it under the non-excluded adapters path)
- Modify: `tests/test_makescripts_clean.py`  -  re-point import to `bmk.adapters.stagerunner.helpers.clean`
- Test: `tests/test_stagerunner_registry.py`

**Interfaces:**
- Consumes: `_clean.main(*, project_dir, dry_run, verbose) -> int` (already keyword-only, returns int  -  unchanged).
- Produces: `def clean_action(ctx: StageContext) -> int` and `PIPELINES["clean"] = (Stage("clean", 10, HelperAction(clean_action)),)`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_stagerunner_registry.py
from bmk.adapters.stagerunner.registry import PIPELINES

def test_clean_pipeline_registered_single_stage() -> None:
    stages = PIPELINES["clean"]
    assert [s.name for s in stages] == ["clean"]
    assert stages[0].order == 10
```

- [ ] **Step 2: Run to verify it fails**
Run: `pytest tests/test_stagerunner_registry.py -v`
Expected: FAIL  -  `registry` missing / KeyError.

- [ ] **Step 3: Implement**
```bash
git mv src/bmk/makescripts/_clean.py src/bmk/adapters/stagerunner/helpers/clean.py
```
```python
# src/bmk/adapters/stagerunner/helpers/__init__.py
"""In-process stage helper modules (migrated from makescripts/_*.py)."""
```
```python
# src/bmk/adapters/stagerunner/registry.py
from __future__ import annotations

from .actions import HelperAction
from .helpers import clean as clean_helper
from .model import Stage, StageContext


def clean_action(ctx: StageContext) -> int:
    return clean_helper.main(project_dir=ctx.project_dir, dry_run=False, verbose=False)


PIPELINES: dict[str, tuple[Stage, ...]] = {
    "clean": (Stage("clean", 10, HelperAction(clean_action)),),
}
```
Update `pyproject.toml` `[tool.pyright] exclude` so the new `helpers/clean.py` (under `adapters/`, not `makescripts/`) is type-checked; run `pyright` and fix any strict findings surfaced by moving it under strict.

- [ ] **Step 4: Run tests + pyright + lint-imports**
Run: `pytest tests/test_stagerunner_registry.py tests/test_makescripts_clean.py -v && pyright src/bmk/adapters/stagerunner/ && lint-imports`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "refactor(stagerunner): migrate _clean into helpers, register clean pipeline"
```

### Task 6: The engine  -  run_stage / run_batch / run_pipeline (parallel, fail-fast)

**Files:**
- Create: `src/bmk/adapters/stagerunner/engine.py`
- Test: `tests/test_stagerunner_engine.py`

**Interfaces:**
- Consumes: `Stage`, `StageContext`, sinks, `group_into_batches`, `StageResult`, `PipelineSummary`, `install_signal_handlers`.
- Produces:
  - `def run_stage(stage: Stage, ctx: StageContext) -> StageResult`  -  pick `CapturingSink` (json + non-interactive) or `PassthroughSink`; time it; return result.
  - `def run_batch(batch: list[Stage], ctx: StageContext) -> list[StageResult]`  -  one stage inline; else `ThreadPoolExecutor(max_workers=len(batch))`, results in declaration order.
  - `def run_pipeline(stages: Sequence[Stage], ctx: StageContext, *, out: TextIO = sys.stdout) -> int`  -  batches sequential (fail-fast between batches), report failures, emit success JSON summary, return first-failure normalized code.

- [ ] **Step 1: Write the failing tests** (fake stages, no subprocess)
```python
# tests/test_stagerunner_engine.py
import time
from pathlib import Path
from bmk.adapters.stagerunner.engine import run_pipeline
from bmk.adapters.stagerunner.model import Stage, StageContext

def _ctx(tmp_path: Path) -> StageContext:
    return StageContext(project_dir=tmp_path, args=(), output_format="json",
                        python_cmd="python3", package_name="x", env={}, show_warnings=True)

def test_run_pipeline_fail_fast_skips_later_batches(tmp_path: Path) -> None:
    called: list[str] = []
    def ok(ctx, sink): called.append("a"); return 0
    def boom(ctx, sink): called.append("b"); return 7
    def never(ctx, sink): called.append("c"); return 0
    stages = [Stage("a", 10, ok), Stage("b", 20, boom), Stage("c", 30, never)]
    rc = run_pipeline(stages, _ctx(tmp_path))
    assert rc == 7
    assert "c" not in called  # later batch never runs

def test_run_batch_runs_equal_order_in_parallel(tmp_path: Path) -> None:
    starts: list[float] = []
    def slow(ctx, sink):
        starts.append(time.monotonic()); time.sleep(0.3); return 0
    stages = [Stage("x", 40, slow), Stage("y", 40, slow)]
    t0 = time.monotonic()
    assert run_pipeline(stages, _ctx(tmp_path)) == 0
    assert time.monotonic() - t0 < 0.55  # overlapped, not 0.6 serial
```

- [ ] **Step 2: Run to verify it fails**
Run: `pytest tests/test_stagerunner_engine.py -v`
Expected: FAIL  -  `engine` missing.

- [ ] **Step 3: Implement** (small functions; use `concurrent.futures.ThreadPoolExecutor`; preserve declaration order when collecting results; wrap the run in `install_signal_handlers()`). Emit `PipelineSummary("pass", len(batches), total_stages, None)` on success via `report_success_summary`.

- [ ] **Step 4: Run tests + pyright**
Run: `pytest tests/test_stagerunner_engine.py -v && pyright src/bmk/adapters/stagerunner/engine.py`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add src/bmk/adapters/stagerunner/engine.py tests/test_stagerunner_engine.py
git commit -m "feat(stagerunner): sequential-batch engine with parallel within-batch + fail-fast"
```

### Task 7: Context builder + CLI selector; cut `clean` over behind `BMK_RUNNER`

**Files:**
- Create: `src/bmk/adapters/stagerunner/context.py`
- Modify: `src/bmk/adapters/cli/commands/_shared.py`
- Test: `tests/test_stagerunner_context.py`, extend `tests/test_cli_*` for the clean command

**Interfaces:**
- Produces: `def build_context(cwd, args, *, command_prefix, output_format, show_warnings, package_name="") -> StageContext`  -  ports the env/venv/`VIRTUAL_ENV`/`PIPAPI_PYTHON_LOCATION` logic verbatim from `execute_script` (`_shared.py:104-133`) into a returned `env` mapping; derives `package_name` via the migrated `_derive_package_name` helper when empty.
- Modifies `execute_script`: read `BMK_RUNNER` (env -> default `"shell"`). When `"python"` **and** `command_prefix in PORTED_PREFIXES` -> `return run_pipeline(list(PIPELINES[command_prefix]), build_context(...))`; else fall through to the existing shell-out. Import `normalize_returncode` from `bmk.domain.stages` (delete the local copy).

- [ ] **Step 1: Write the failing test**
```python
# tests/test_stagerunner_context.py
from pathlib import Path
from bmk.adapters.stagerunner.context import build_context

def test_build_context_sets_project_env(tmp_path: Path) -> None:
    ctx = build_context(tmp_path, (), command_prefix="clean", output_format="json", show_warnings=True)
    assert ctx.env["BMK_PROJECT_DIR"] == str(tmp_path)
    assert ctx.env["BMK_COMMAND_PREFIX"] == "clean"

def test_build_context_omits_virtualenv_when_no_venv(tmp_path: Path) -> None:
    ctx = build_context(tmp_path, (), command_prefix="clean", output_format="json", show_warnings=True)
    assert "VIRTUAL_ENV" not in ctx.env
```

- [ ] **Step 2: Run to verify it fails**
Run: `pytest tests/test_stagerunner_context.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `build_context` (move the venv/PIPAPI logic; keep the CLAUDE.md comment about `PIPAPI_PYTHON_LOCATION` verbatim) and the `execute_script` selector with `PORTED_PREFIXES = frozenset({"clean"})`.

- [ ] **Step 4: Verify both runner paths**
Run:
```bash
pytest tests/test_stagerunner_context.py tests/test_cli_clean* -v
# Real end-to-end, both paths, in a scratch project:
BMK_RUNNER=python bmk clean   # in-process engine
BMK_RUNNER=shell  bmk clean   # legacy shell path still works
```
Expected: identical artifact removal + exit code from both.

- [ ] **Step 5: Commit**
```bash
git add -A
git commit -m "feat(stagerunner): context builder + BMK_RUNNER selector; cut clean over to Python"
```

---

## Phase 2  -  Overlay + delegators: `deps`, `deps_update`

Goal: prove `PipelineAction` (pipeline-composes-pipeline) and the TOML overlay.

- **Task 8  -  `PipelineAction`:** add `class PipelineAction` to `actions.py` whose `__call__` invokes `run_pipeline(list(PIPELINES[self._prefix]), ctx)`. Test: a two-pipeline registry where the outer delegates to the inner; assert inner stages ran. Replaces the shell delegator pattern (`test_010_update_deps.sh` re-exec'ing the stagerunner).
- **Task 9  -  migrate `_dependencies.py`, `_derive_package_name.py`, `_loader`-dependents:** `git mv` into `helpers/`; register `deps` (`Stage("deps", 10, HelperAction(...))`) and `deps_update`. Re-point `tests/test_makescripts_dependencies.py` imports. Add both to `PORTED_PREFIXES`. Delete `deps_010_deps.{sh,ps1}`, `deps_update_010_*.{sh,ps1}`.
- **Task 10  -  TOML overlay (`overrides.py`):** `def load_overlay(cwd, prefix) -> Overlay | None` reading `[tool.bmk.pipelines.<prefix>]` from `pyproject.toml` or `bmk_makescripts/stages.toml`; `def apply_overlay(stages, overlay) -> tuple[Stage, ...]` supporting `add` (name/order/argv), `remove` (by name), `replace` (by name -> argv `ToolAction`). Overlay actions are argv-list `ToolAction`s only (declarative, safe). Unit-test add/remove/replace against a fake pipeline; integration-test one real overlay in a tmp cwd. Wire `run_pipeline` callers to apply the overlay before running.
- **Task 11  -  legacy shell-override fallback (`ShellStageAction`, temporary):** in override resolution, if `bmk_makescripts/{prefix}_NN_*.sh` exists, run those via `ShellStageAction` (execs the file with the same env) instead of the built-in pipeline  -  preserving today's "override replaces bundled entirely" rule for not-yet-migrated downstream projects. Mark clearly as removed in Phase 5. Test with a tmp project shipping a shell override.

Each task: failing test -> fail -> implement -> pass -> `lint-imports`/`pyright` -> commit. Delete the `.sh` **and** `.ps1` twin for every ported stage in the same commit.

---

## Phase 3  -  The CI-critical path: `test`, `test_integration`, `cov`

Goal: port the real stress case  -  a multi-batch pipeline with a wide parallel batch at order 40.

Port these `test_*` stages to registry entries, reusing the pattern from the three representative examples:

- **Simple tool-runner** (e.g. `test_040_ruff_lint.sh`, `test_040_ruff_format_check.sh`, `test_040_bandit.sh`, `test_040_pyright.sh`, `test_040_lint_imports.sh`, `test_040_pip_audit.sh`, `test_020_ruff_format_apply.sh`, `test_030_ruff_fix_apply.sh`):
```python
def ruff_lint_argv(ctx: StageContext) -> list[str]:
    argv = ["ruff", "check"]
    if ctx.output_format == "json":
        argv += ["--output-format", "json"]
    return [*argv, "."]
Stage("ruff_lint", 40, ToolAction(ruff_lint_argv))
```
The per-script `explain_exit_code` case-statement is *not* re-implemented per stage  -  extend `EXIT_HINTS` once (Task 3) and let the reporter consult `hint_for(tool, code)` on failure.

- **Helper caller** (`test_040_pytest.sh` -> `_coverage.py`, `test_integration_010_pytest.sh`, `cov_010_coverage.sh`, `cov_020_clean.sh`):
```python
def run_pytest_coverage(ctx: StageContext) -> int:
    from .helpers import coverage
    return coverage.main(project_dir=ctx.project_dir, run_tests=True, upload=True,
                         quiet=ctx.output_format == "json")
Stage("pytest", 40, HelperAction(run_pytest_coverage))
```
`_coverage.main()` is already keyword-only and returns int (verified). `git mv _coverage.py -> helpers/coverage.py`; re-point `tests/test_makescripts_coverage.py`.

- **pip-audit stage:** migrate `_extract_pip_audit_ignores.py` into `helpers/`; the `PIPAPI_PYTHON_LOCATION` env pin already lives in `build_context` (Task 7). Add a regression unit test asserting the context env pins pip-audit to the project venv interpreter (this is the exact 2.9.6 bug  -  lock it down with a test now).

**Critical  -  parallel in-process capture (see Risks: stdout):** stages sharing order 40 run concurrently. Pure-Python `HelperAction`s that print to global `sys.stdout` are **not** thread-safe under capture. Mitigation for this phase: keep capturing helpers as subprocesses where they already are (pytest is a subprocess inside `_coverage`), and for any pure-Python printing helper in a parallel batch, pass `sink` down as an explicit stream argument rather than relying on `redirect_stdout`. Add a test that two capturing helpers in one batch keep separate buffers.

Cut `test`, `test_integration`, `cov` into `PORTED_PREFIXES`. Delete all ported `test_*`/`cov_*` `.sh`+`.ps1` twins. **Flip the `BMK_RUNNER` default to `"python"` only after `make test` is green on Linux and Windows.**

---

## Phase 4  -  Logic-heavy & git pipelines: `bump_*`, `commit`, `push`, `rel`, `run`, `custom`

Port the remaining pipelines; the logic-carrying ones get pure, unit-testable sub-functions.

**`commit` (from `commit_010_commit.sh`) -> `helpers/commit.py`:**
```python
def resolve_message(args: tuple[str, ...], *, env: Mapping[str, str], isatty: bool) -> str:
    """arg-join -> BMK_COMMIT_MESSAGE -> prompt (only if isatty) -> 'chores'."""
def timestamp_prefix(now: datetime) -> str:              # "%Y-%m-%d %H:%M:%S"  -  pure
def detect_sensitive(staged: Sequence[str]) -> list[str]  # regex \.env$|credentials|secret|\.key$|\.pem$|id_rsa  -  pure
def commit(ctx: StageContext) -> int:                     # git add -A; warn; --allow-empty when `git diff --cached --quiet`; git commit -m
Stage("commit", 10, HelperAction(commit), interactive=True)
```
`interactive=True` makes the engine use `PassthroughSink` so the `read`-equivalent prompt is visible; the prompt fires only when `sys.stdin.isatty()` (ports `[[ -t 0 ]]`). Timestamp / sensitive-detection / message-resolution are pure and tested without touching git. Port the `git-commit` `EXIT_HINTS` entry (already seeded in Task 3).

**`push` (`push_050_push.sh` + delegators):** delegators (`push_020_build`, `push_020_test`, ...) become `PipelineAction`s; `push_050_push` becomes `helpers/push.py` using `git rev-parse --abbrev-ref HEAD` for branch resolution  -  argv lists, `cwd=project_dir`. Note `push_020_build` and `push_020_test` share order 20 -> they run in parallel exactly as the shell did.

**`bump_*` (`_bump_version.py` + `_sync_initconf.py`, sharing `_bump_lib.sh`):** the shared-lib init/run collapses into a single `bump_action(kind)` factory; `git mv` both helpers into `helpers/`. Register `bump_major`/`bump_minor`/`bump_patch` as two-stage pipelines (`010_bump`, `020_sync_initconf`).

**`rel` (`_release.py`) and `run` (`_run.py`):** `git mv` into `helpers/`, register single-stage `HelperAction`s, re-point `tests/test_makescripts_release.py`/`test_makescripts_run.py`. **`custom`** stays prefix-driven  -  it reads a user-named pipeline from the TOML overlay.

Add every pipeline to `PORTED_PREFIXES`; delete the corresponding `.sh`+`.ps1` twins per commit.

---

## Phase 5  -  Retire the shell layer

Once every prefix is in `PORTED_PREFIXES` and `make test` is green on Linux + Windows:

- Delete `_btx_stagerunner.sh`, `_btx_stagerunner.ps1`, `_resolve_python.{sh,ps1}`, `_bump_lib.{sh,ps1}`, and any remaining `*.sh`/`*.ps1` under `makescripts/`.
- Remove the legacy `ShellStageAction` override path (Task 11) and its tests; the TOML overlay is now the sole customization mechanism.
- Delete `_loader.py` (dynamic-import shim  -  helpers are now normal imports).
- Delete `tests/test_makescripts_ps1.py`, `tests/test_makescripts_shellcheck.py`, `tests/test_makescripts_psscriptanalyzer.py`. **Decide (out of scope note):** if bmk should still *lint a target project's own* shell/ps1 scripts, keep `_shellcheck.py`/`_psscriptanalyzer.py` as helpers behind opt-in stages; otherwise delete them. They only ever linted bmk's own now-deleted shell sources by default.
- In `_shared.py`: remove `get_script_name`, the `.ps1` `pwsh -File` branch, and the shell-out fallback; `execute_script` becomes a thin adapter over `run_pipeline`. **Also fix the pre-existing bug** in `require_script_path` (`_shared.py:176`): the bundled-path error message uses three `.parent` hops (`adapters/makescripts`) where `resolve_script_path` correctly uses four (`bmk/makescripts`)  -  this whole function likely disappears in this phase, but if any part survives, correct the hop count.
- `pyproject.toml`: remove the `makescripts` entry from `[tool.pyright] exclude` entirely; drop the `*.sh`/`*.ps1` wheel `include` globs.
- `CLAUDE.md`: delete the "PowerShell / Bash Script Parity" and "Makescripts Argument Forwarding" sections and the twin-parity rule; document the new registry + TOML overlay model instead.
- Retire the bundled-`Makefile` shellcheck/psscriptanalyzer stage references.

Final commit gate: `make test` green on Linux and Windows; `lint-imports` clean; `pyright` strict clean with `makescripts` no longer excluded.

---

## Verification (end-to-end)

Run after each phase and at completion:

1. **Unit + integration suite:** `make test` (must stay green throughout; new engine/model/actions/output/overrides tests included). Confirm real parallelism, fail-fast, capture-on-failure, signal handling, and overlay merge are all covered.
2. **Both runner paths agree (during migration):** for each ported prefix, run `BMK_RUNNER=python bmk <cmd>` and `BMK_RUNNER=shell bmk <cmd>` in a scratch project and diff exit code + observable effect. They must match before deleting the shell twin.
3. **Real pipelines against a scratch project:** `bmk clean`, `bmk test`, `bmk push` (dry, on a throwaway branch)  -  verify artifacts removed, tools run in the right order/parallelism, JSON summary emitted on success and full captured output shown only on failure.
4. **Cross-OS:** run the engine tests and at least `bmk clean` + `bmk test` on Windows (no `pwsh` needed) to confirm argv-list `subprocess.run` resolves `ruff`/`pyright`/`pytest`/`git` on PATH.
5. **Signal behavior:** start `bmk test`, Ctrl-C mid-run; confirm children are terminated and the process exits 130, no orphaned tool processes.
6. **Architecture gates:** `lint-imports` (layer contracts) and `pyright` strict with the shrinking/removed `makescripts` exclusion.

## Risks / shell-behavior-to-preserve

- **Signals (highest risk):** the shell's `kill 0` kills the whole process group. Python can't force-kill a `ThreadPoolExecutor` worker mid-`wait()`, so `signals.py` tracks live `Popen`s and `.terminate()`s them; the worker's `run_argv` returns once its child dies. Test with a real sleeper subprocess + delivered SIGINT asserting 130 and an empty live registry.
- **Parallel in-process stdout capture:** `contextlib.redirect_stdout` is process-global and *not* thread-safe  -  two capturing pure-Python `HelperAction`s in the same order-batch would clobber each other. Mitigation: capturing helpers pass `sink` as an explicit stream (no global redirect), or run as subprocesses (pytest already is). Enforced by a test (Phase 3).
- **Interactive commit prompt:** must keep `sys.stdin.isatty()` gating and run the stage in passthrough (`interactive=True`) so the prompt is visible; commit/push are single-stage order-10 so no parallel-batch conflict.
- **git semantics:** preserve `cwd=project_dir`, env, `--allow-empty` via `git diff --cached --quiet`, and branch resolution via `git rev-parse --abbrev-ref HEAD`; real `git commit` still fires pre-commit hooks.
- **Windows:** dropping `pwsh` is a simplification, but verify tool resolution on PATH; argv-list `subprocess.run` (no `shell=True`) is the cross-OS guarantee.
- **shellcheck/psscriptanalyzer stages** become moot for bmk's own (deleted) shell sources  -  decide in Phase 5 whether to keep them for linting *target-project* scripts.
- **Snapshot before the bulk deletes** (Phase 5 removes many files at once): `git commit` first so `git reset --hard HEAD~1` is a clean recovery (org rule).
```
