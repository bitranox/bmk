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
        return subprocess.run(argv, cwd=cwd, stdout=output, stderr=output, check=False).returncode
    except OSError:
        # uv missing from PATH. Degrade to the caller's fallback rather than
        # breaking a run that may not have needed the venv at all.
        return 1


def _git(argv: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git command in ``cwd``, returning (exit code, stdout)."""
    try:
        result = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return 1, ""
    return result.returncode, result.stdout


def _is_git_worktree(cwd: Path) -> bool:
    """Whether ``cwd`` sits inside a git work tree."""
    code, out = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    return code == 0 and out.strip() == "true"


def _untrack(cwd: Path, name: str) -> bool:
    """Drop ``name`` from the index if git tracks it, keeping it on disk.

    A tracked venv is not a cosmetic problem: the sync rewrites its contents on
    every run, so git would see thousands of modified files each time and any
    commit would sweep them in.

    Returns:
        True if something was untracked.
    """
    code, out = _git(["ls-files", "--", name], cwd)
    if code != 0 or not out.strip():
        return False
    count = len(out.strip().splitlines())
    if _git(["rm", "-r", "--cached", "--quiet", "--", name], cwd)[0] != 0:
        return False
    # Announce unconditionally, never gated on quiet: this stages deletions in
    # the user's index, and `push` commits automatically.
    print(f"[bmk] untracked {count} file(s) under '{name}' (kept on disk; the deletion is staged)")
    return True


def _ignore_entries(cwd: Path, venv: Path) -> list[str]:
    """Names that should be gitignored: the managed venv plus the usual pair.

    ``.venv-win`` earns its place even on Linux: one checkout reached from two
    operating systems needs a venv each, and the sibling's directory is
    otherwise permanently untracked noise in `git status`.
    """
    names = [".venv", ".venv-win"]
    try:
        relative = venv.resolve().relative_to(cwd.resolve())
    except ValueError:
        return names  # venv lives outside the repo; nothing to ignore for it
    managed = relative.parts[0]
    return names if managed in names else [managed, *names]


def _is_declared(cwd: Path, name: str) -> bool:
    """Whether the REPOSITORY's own rules ignore ``name``.

    Not simply "is this path ignored": ``uv venv`` drops a ``.gitignore``
    containing ``*`` INSIDE every venv it creates, so a uv-made venv reports as
    ignored by its own nested file. That is uv hiding its artifact, not the repo
    declaring the name, and treating it as declared would leave ``.venv``
    undeclared while its ``.venv-win`` sibling got written - the names applied
    inconsistently across repos.

    ``check-ignore -v`` reports ``<source>:<line>:<pattern>\\t<path>``, so the
    source file tells the two apart.

    Queried with a trailing slash: a ``dir/`` rule only matches a path git knows
    is a directory, which it cannot for one that does not exist yet.
    """
    code, out = _git(["check-ignore", "-v", "--", f"{name}/"], cwd)
    if code != 0 or not out.strip():
        return False
    source = out.split(":", 1)[0]
    return not source.startswith(f"{name}/")


def _append_to_gitignore(cwd: Path, missing: list[str]) -> None:
    """Append ``missing`` entries to .gitignore under a labelled section."""
    gitignore = cwd / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = "\n# Python virtual environments (managed by bmk)\n" + "".join(f"{n}/\n" for n in missing)
    gitignore.write_text(existing + prefix + block, encoding="utf-8")
    print(f"[bmk] added to .gitignore: {', '.join(missing)}")


def ensure_venv_ignored(cwd: Path, venv: Path) -> None:
    """Keep the venv out of git: untrack it if tracked, gitignore it if not ignored.

    bmk creates this directory, so bmk is responsible for it not polluting the
    repository. Never raises: a git problem must not fail a build.
    """
    if not _is_git_worktree(cwd):
        return

    entries = _ignore_entries(cwd, venv)
    for name in entries:
        _untrack(cwd, name)

    # git decides what is already covered, so an existing rule - a wildcard, a
    # nested .gitignore, a global excludesFile - is respected rather than
    # duplicated. A text search over .gitignore would see none of those.
    missing = [n for n in entries if not _is_declared(cwd, n)]
    if missing:
        _append_to_gitignore(cwd, missing)


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

    Because bmk creates this directory, it also keeps it out of git
    (``ensure_venv_ignored``).

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

    ensure_venv_ignored(cwd, venv)

    python = venv_python(venv)
    for target in _INSTALL_TARGETS:
        argv = ["uv", "pip", "install", "--python", str(python), "--exact", "--upgrade", "-e", target]
        if _run(argv, cwd, quiet=quiet) == 0:
            return venv
    return None
