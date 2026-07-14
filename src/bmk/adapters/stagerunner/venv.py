"""Resolve, create and sync the target project's virtual environment.

bmk's gates only tell the truth if the interpreter they inspect matches the
project's ``pyproject.toml``. This module is the single source of truth for two
questions: *which* venv is the project's, and *is it current*.

Provisioning runs before the pipeline starts (see
:func:`bmk.adapters.cli.commands._shared.run_command`), not as a stage. That is a
hard requirement, not a preference: :func:`context.build_context` pins
``VIRTUAL_ENV`` / ``PIPAPI_PYTHON_LOCATION`` once, up front, and ``StageContext``
is frozen, so a venv created by a stage could not repair the pins for the stages
that follow it in the same run.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

# Sync targets, tried in order: a project with no ``[dev]`` extra (bmk itself is
# one - all its tooling is a runtime dependency by design) must still sync.
# Mirrors the fallback chain in ``src/bmk/makefile/Makefile``.
_INSTALL_TARGETS: tuple[str, ...] = (".[dev]", ".")


def resolve_project_venv(cwd: Path, env: Mapping[str, str]) -> Path:
    """Path of the project's venv.

    Honours uv's ``UV_PROJECT_ENVIRONMENT`` (absolute, or relative to ``cwd``)
    rather than hardcoding ``.venv``. A tree shared between OSes cannot use one
    venv path for both: on the bitranox softdev mount ``.venv`` is the Linux venv
    and Windows points ``UV_PROJECT_ENVIRONMENT`` at ``.venv-win``, so syncing
    ``.venv`` from Windows would rebuild it and break the Linux side.
    """
    configured = env.get("UV_PROJECT_ENVIRONMENT", "").strip()
    if not configured:
        return cwd / ".venv"
    candidate = Path(configured)
    return candidate if candidate.is_absolute() else cwd / candidate


def venv_python(venv: Path) -> Path:
    """Interpreter inside ``venv`` for the current OS."""
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def is_venv(venv: Path) -> bool:
    """Whether ``venv`` is a usable virtual environment.

    ``pyvenv.cfg`` is the marker: a bare directory that merely shares the name is
    not a venv, and pinning tools at one would point them at nothing.
    """
    return venv.is_dir() and (venv / "pyvenv.cfg").is_file()


def _run(argv: list[str], cwd: Path, *, quiet: bool) -> int:
    """Run ``argv`` in ``cwd``, silencing output when quiet."""
    output = subprocess.DEVNULL if quiet else None
    try:
        # argv is built from literals and a resolved path, never from user
        # input, and runs without a shell.
        return subprocess.run(  # noqa: S603
            argv, cwd=cwd, stdout=output, stderr=output, check=False
        ).returncode
    except OSError:
        # uv missing from PATH. Degrade to the caller's fallback rather than
        # breaking a run that may not have needed the venv at all.
        return 1


def ensure_project_venv(cwd: Path, env: Mapping[str, str], *, quiet: bool = True) -> Path | None:
    """Create the project venv if absent, then sync it to ``pyproject.toml``.

    An existing venv is updated in place and never recreated, so its path - and
    therefore the pins derived from it - stay stable across the run.

    The sync needs ``--exact`` *and* ``--upgrade``; either alone leaves the venv
    lying about what the project resolves, in a different way:

    * ``--exact`` removes packages the manifest no longer asks for. Without it, a
      dropped dependency lingers and pip-audit reports CVEs against a package the
      project does not actually resolve.
    * ``--upgrade`` re-resolves packages that are already installed. Without it,
      uv keeps any installed version that still satisfies its constraint, so a
      stale *unconstrained* transitive (``setuptools`` via ``pbr``, say) never
      moves off a vulnerable release even though a fresh resolution would pick the
      fixed one.

    The trade-off is that packages installed into the venv by hand do not survive
    a sync.

    ``--exact`` also removes ``pip`` (a uv-created venv ships none anyway); the
    ``pip_audit`` stage bootstraps a current pip into the resolved interpreter
    before every audit, so that repairs itself.

    Returns:
        The venv path, or ``None`` if it could not be provisioned. Never raises:
        a provisioning failure must degrade to bmk's previous behaviour (gates
        run against bmk's own interpreter), not abort the command.
    """
    if not (cwd / "pyproject.toml").is_file():
        return None

    venv = resolve_project_venv(cwd, env)
    if not is_venv(venv) and _run(["uv", "venv", str(venv)], cwd, quiet=quiet) != 0:
        return None
    if not is_venv(venv):
        return None

    python = venv_python(venv)
    for target in _INSTALL_TARGETS:
        argv = ["uv", "pip", "install", "--python", str(python), "--exact", "--upgrade", "-e", target]
        if _run(argv, cwd, quiet=quiet) == 0:
            return venv
    return None
