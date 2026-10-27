"""Run a project's pytest across processes with pytest-xdist, when the project declares it.

bmk never brings pytest-xdist itself: the suite runs in the project's own venv, the one its lock
pins and CI installs, so parallel runs start only once the project lists ``pytest-xdist`` in its
dev extra. Until then it stays serial, which is what a suite that was never written to run in
parallel needs.

A parallel run always uses ``--dist loadgroup``: every test carrying the same
``@pytest.mark.xdist_group("<name>")`` goes to one worker and runs one after another, while the
rest of the suite spreads out. That is how a project keeps tests that share an external resource
(a test database, a fixed port) out of the parallel part without giving up the speed elsewhere.
``[tool.scripts.test] workers = 1`` (or ``BMK_TEST_WORKERS=1``) runs the suite in one process, also
when the project's own ``addopts`` passes ``-n``: bmk then adds ``-n 0``, which pytest-xdist reads
as "do not distribute".

What the run will load is asked of the project's own pytest, with its configuration fully parsed,
never inferred from what is importable: plugin autoload can be off
(``PYTEST_DISABLE_PLUGIN_AUTOLOAD``), addopts can block a plugin (``-p no:xdist``), and a project
that already passes ``-n`` or ``--dist`` keeps its own choice.
"""

from __future__ import annotations

import subprocess
import tempfile
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from bmk.domain.enums import RefusalKind
from bmk.domain.errors import RefusalError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AUTO",
    "WORKERS_ENV",
    "ParallelProbe",
    "ParallelSupport",
    "PytestPlugins",
    "normalise_workers",
    "probe_parallel",
    "resolve_test_workers",
    "split_workers",
    "xdist_args",
]

#: Overrides ``[tool.scripts.test] workers`` for one run; empty or unset means "read the project".
WORKERS_ENV = "BMK_TEST_WORKERS"
AUTO = "auto"

# Runs in the PROJECT's interpreter. pytest.main builds the real configuration (ini files, addopts,
# PYTEST_ADDOPTS, plugin autoload and blocks), then the probe's tryfirst cmdline hook records what
# that configuration loaded and returns before anything is collected. The answer goes to a file,
# because pytest's global output capture may own stdout at that point.
_PROBE = """
import importlib.util, json, sys
facts = {
    "xdist_installed": importlib.util.find_spec("xdist") is not None,
    "cov_installed": importlib.util.find_spec("pytest_cov") is not None,
}
try:
    import pytest
except ImportError:
    pytest = None
if pytest is not None:
    class _Probe:
        @pytest.hookimpl(tryfirst=True)
        def pytest_cmdline_main(self, config):
            plugins = config.pluginmanager
            facts["xdist_loaded"] = plugins.hasplugin("xdist")
            facts["cov_loaded"] = plugins.hasplugin("pytest_cov")
            facts["project_workers"] = getattr(config.option, "numprocesses", None) is not None
            facts["project_dist"] = getattr(config.option, "dist", "no") not in ("no", None)
            return 0
    pytest.main(["-p", "no:cacheprovider"], plugins=[_Probe()])
with open(sys.argv[1], "w", encoding="utf-8") as out:
    json.dump(facts, out)
"""


class ParallelSupport(Enum):
    """What the project's pytest can do for a parallel run."""

    READY = "ready"  # pytest-xdist and pytest-cov loaded: a parallel run with coverage
    XDIST_ONLY = "xdist-only"  # parallel without coverage (enough for test-all's cells)
    NO_XDIST = "no-xdist"  # the project has not declared pytest-xdist
    DISABLED = "disabled"  # installed, but the project's configuration does not load it
    UNKNOWN = "unknown"  # the interpreter did not answer; stay serial and say nothing


class PytestPlugins(BaseModel):
    """What the project's pytest loads and how its own configuration already runs xdist.

    Attributes:
        answered: False when the interpreter could not be asked; every other field is then unknown.
        xdist_installed: ``xdist`` is importable in the project's venv.
        xdist_loaded: The project's configured pytest loads it.
        cov_installed: ``pytest_cov`` is importable in the project's venv.
        cov_loaded: The project's configured pytest loads it.
        project_workers: The project's own configuration already passes ``-n``.
        project_dist: The project's own configuration already passes a ``--dist`` mode.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    answered: bool = True
    xdist_installed: bool = False
    xdist_loaded: bool = False
    cov_installed: bool = False
    cov_loaded: bool = False
    project_workers: bool = False
    project_dist: bool = False

    @property
    def support(self) -> ParallelSupport:
        """The parallel run these plugins allow."""
        if not self.answered:
            return ParallelSupport.UNKNOWN
        if self.xdist_loaded:
            return ParallelSupport.READY if self.cov_loaded else ParallelSupport.XDIST_ONLY
        return ParallelSupport.DISABLED if self.xdist_installed else ParallelSupport.NO_XDIST

    @property
    def missing(self) -> str | None:
        """The package to add for a parallel run with coverage; None when nothing is missing.

        A plugin that is installed but switched off is the project's own decision, so it is
        never reported as missing.
        """
        if not self.answered or (self.xdist_installed and not self.xdist_loaded):
            return None
        if not self.xdist_installed:
            return "pytest-xdist"
        if not self.cov_installed:
            return "pytest-cov"
        return None


class ParallelProbe(Protocol):
    """Asks a project's interpreter which parallel-run plugins its pytest loads (``probe_parallel``)."""

    def __call__(self, python: str, /, *, env: Mapping[str, str], cwd: Path) -> PytestPlugins: ...


def normalise_workers(raw: object) -> str:
    """``"auto"`` or a positive count as text.

    Raises:
        ValueError: ``raw`` is neither; the message names the setting.
    """
    if isinstance(raw, str) and raw.strip().lower() == AUTO:
        return AUTO
    # bool is an int subclass, and `workers = true` is no count.
    if isinstance(raw, int) and not isinstance(raw, bool):
        count = raw
    elif isinstance(raw, str) and raw.strip().isascii() and raw.strip().isdigit():
        count = int(raw.strip())
    else:
        msg = f'workers must be "auto" or a whole number >= 1 (1 means serial), got: {raw!r}'
        raise ValueError(msg)
    if count < 1:
        msg = f"workers must be >= 1 (1 means serial), got: {count}"
        raise ValueError(msg)
    return str(count)


def resolve_test_workers(configured: str, *, env: Mapping[str, str]) -> str:
    """The worker setting for this run: ``BMK_TEST_WORKERS`` if set, else the project's.

    Args:
        configured: ``[tool.scripts.test] workers``, already normalised.
        env: The environment to read the override from.

    Raises:
        RefusalError: the environment variable holds something other than a worker setting.
    """
    raw = env.get(WORKERS_ENV, "").strip()
    if not raw:
        return configured
    try:
        return normalise_workers(raw)
    except ValueError as exc:
        msg = f"{WORKERS_ENV}: {exc}"
        raise RefusalError(msg, kind=RefusalKind.INVALID_ARGUMENT) from exc


def split_workers(workers: str, *, cells: int, cpus: int | None) -> str:
    """The workers ONE test-all cell gets while ``cells`` cells run at once.

    ``auto`` shares the CPUs between the cells, so six cells on 16 CPUs do not start 96 pytest
    workers. An explicit count is kept as the project wrote it. An unknown CPU count stays serial:
    guessing high would oversubscribe the machine, and serial is what every cell did before.
    """
    if workers != AUTO:
        return workers
    if not cpus:
        return "1"
    return str(max(1, cpus // max(1, cells)))


def xdist_args(workers: str, *, project: PytestPlugins) -> list[str]:
    """The pytest arguments for ``workers``.

    pytest puts addopts before the command line and the last value wins, so an ``-n`` or
    ``--dist`` from bmk would silently replace one the project chose. For a parallel run that is
    the project's call: a project that already passes ``-n`` gets nothing added, one that passes
    only ``--dist`` keeps its mode. A serial run is bmk's call, because it is either the off
    switch (``workers = 1``) or a run whose coverage only one process can measure, so a project's
    own ``-n`` is overridden with ``-n 0``. Without xdist loaded pytest would reject ``-n``, and
    the project cannot be passing one.
    """
    if workers == "1":
        return ["-n", "0"] if project.xdist_loaded and project.project_workers else []
    if project.project_workers:
        return []
    dist = [] if project.project_dist else ["--dist", "loadgroup"]
    return ["-n", workers, *dist]


def probe_parallel(python: str, *, env: Mapping[str, str], cwd: Path) -> PytestPlugins:
    """Ask the project's own pytest which parallel-run plugins its configuration loads.

    A subprocess, because the plugins live in the PROJECT's venv, never in bmk's own, and run from
    ``cwd`` so the project's ini files and addopts apply.
    """
    with tempfile.TemporaryDirectory() as tmp:
        answer = Path(tmp) / "plugins.json"
        try:
            subprocess.run(  # argv list, the project's own interpreter
                [python, "-c", _PROBE, str(answer)],
                cwd=cwd,
                env=dict(env),
                capture_output=True,
                check=False,
                timeout=60,
            )
            return PytestPlugins.model_validate_json(answer.read_bytes())
        except (OSError, subprocess.TimeoutExpired, ValidationError):
            return PytestPlugins(answered=False)
