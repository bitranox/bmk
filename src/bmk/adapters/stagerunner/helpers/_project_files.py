"""Discovery of a project's own source files of one kind, for the lint stages.

Purpose
-------
Answer "which ``.sh`` (or ``.ps1``) files belong to this project?" the way git sees the
project, so a linter never reads a file the project does not own.

Contents
--------
* ``find_project_files`` -- The project's files ending in a suffix, sorted.

System Role
-----------
Shared by ``_shellcheck.py`` and ``_psscriptanalyzer.py``. Inside a git work tree it
lists tracked files plus untracked files git does not ignore, so a scratch script in a
gitignored directory is not linted; outside one it walks the directory. Either way,
vendored directories, virtualenvs and nested checkouts are dropped.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_EXCLUDED_DIRS: tuple[str, ...] = (
    "node_modules",
    ".git",
)

# Inherited from the environment, these change git's answer. git reads the repository-
# scoping ones before the cwd, and a push from a linked worktree exports GIT_DIR to its
# hooks, so git would answer for a different repository. git exports the pathspec ones to
# its children for ``git --literal-pathspecs`` (Magit passes it), and they turn ``*.sh``
# into a literal name or a non-recursive glob, which lists nothing.
_GIT_INHERITED_VARS: frozenset[str] = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_LITERAL_PATHSPECS",
        "GIT_GLOB_PATHSPECS",
        "GIT_NOGLOB_PATHSPECS",
        "GIT_ICASE_PATHSPECS",
    }
)

__all__ = ["find_project_files", "git_listed_files"]


def find_project_files(project_dir: Path, suffix: str) -> list[Path]:
    """Find the project's own files ending in ``suffix`` under ``project_dir``.

    Inside a git work tree the candidates are git's tracked files plus untracked files
    that no ``.gitignore`` excludes; outside one, or when the work tree's own repository
    ignores ``project_dir``, every file found by walking the tree. On Windows the suffix
    matches in any letter case, as the walk does there. Files under a virtualenv, ``node_modules``, ``.git`` or a nested checkout (a linked
    worktree or a nested clone) are dropped either way.

    Args:
        project_dir: Root directory of the project.
        suffix: File suffix including the dot, e.g. ``".sh"``.

    Returns:
        Sorted list of existing file paths.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     root = Path(tmp)
        ...     _ = (root / "build.sh").write_text("# build")
        ...     [p.name for p in find_project_files(root, ".sh")]
        ['build.sh']
    """
    listed = git_listed_files(project_dir, suffix, case_insensitive=os.name == "nt")
    candidates: Iterable[Path] = listed if listed is not None else project_dir.rglob(f"*{suffix}")
    return sorted({p for p in candidates if _is_project_file(p, project_dir)})


def git_listed_files(project_dir: Path, suffix: str, *, case_insensitive: bool) -> list[Path] | None:
    """Return git's tracked plus untracked-not-ignored files ending in ``suffix``.

    ``-z`` keeps a non-ASCII name unquoted (git quotes it as ``"a\\303\\244.sh"``
    otherwise, which names no file). The listing is relative to ``project_dir``.

    Args:
        project_dir: Root directory of the project.
        suffix: File suffix including the dot.
        case_insensitive: Match the suffix in any letter case (git's ``:(icase)`` magic).

    Returns:
        The listed paths, or ``None`` - the caller then walks the directory - when
        ``project_dir`` is outside a git work tree, its repository ignores it, or git
        cannot list it (which, inside a checkout, is reported on stderr).
    """
    magic = ":(icase)" if case_insensitive else ""
    listing = _run_git(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", f"{magic}*{suffix}"], project_dir
    )
    if listing is None or listing.returncode != 0:
        _warn_if_inside_a_checkout(project_dir, listing.stderr if listing else b"git could not be started")
        return None
    if _is_ignored_by_its_repository(project_dir):
        return None
    return [project_dir / os.fsdecode(name) for name in listing.stdout.split(b"\0") if name]


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes] | None:
    """Run git in ``cwd`` without the inherited variables that change its answer; ``None`` if it cannot start."""
    env = {key: value for key, value in os.environ.items() if key not in _GIT_INHERITED_VARS}
    try:
        return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, check=False)
    except OSError:
        return None


def _is_ignored_by_its_repository(project_dir: Path) -> bool:
    """Whether the enclosing repository ignores ``project_dir`` itself (``check-ignore`` exits 0).

    A project placed inside an unrelated repository that ignores it (a dotfiles repository
    in the home directory) is not that repository's source, so it is walked instead.

    ``--no-index`` matters: without it git never reports a directory as ignored once the
    index tracks any file inside it. A repository's own root is never ignored, although a
    root ``.gitignore`` of ``*`` matches ``.`` too - so an empty ``--show-prefix`` answers no.
    """
    prefix = _run_git(["rev-parse", "--show-prefix"], project_dir)
    if prefix is None or prefix.returncode != 0 or not prefix.stdout.strip():
        return False
    result = _run_git(["check-ignore", "-q", "--no-index", "."], project_dir)
    return result is not None and result.returncode == 0


def _warn_if_inside_a_checkout(project_dir: Path, stderr: bytes) -> None:
    """Report a git failure inside a checkout, where the walk lints ignored scripts again.

    git exits 128 both outside any repository (the ordinary case, kept silent) and for a
    repository it refuses, such as one with dubious ownership. A real ``.git`` at or above
    ``project_dir`` tells the second case apart; a missing git binary is reported there too.
    """
    resolved = project_dir.resolve()
    if not any(_is_git_marker(directory / ".git") for directory in (resolved, *resolved.parents)):
        return
    lines = os.fsdecode(stderr).strip().splitlines()
    reason = lines[0] if lines else "no message from git"
    print(
        f"WARNING: git could not list the files of {project_dir} ({reason}); walking the "
        "directory instead, which also lints scripts git ignores.",
        file=sys.stderr,
    )


def _is_git_marker(path: Path) -> bool:
    """Whether ``path`` is a real ``.git``: a directory holding ``HEAD``, or a ``gitdir:`` file."""
    if path.is_dir():
        return (path / "HEAD").is_file()
    try:
        return path.read_bytes().startswith(b"gitdir:")
    except OSError:
        return False


def _is_project_file(path: Path, project_dir: Path) -> bool:
    """Whether ``path`` exists as a file and lies outside vendored dirs and nested checkouts."""
    if not path.is_file():
        return False
    rel = path.relative_to(project_dir)
    return not _is_excluded_dir(rel) and not _is_nested_checkout(rel.parts[:-1], project_dir)


def _is_excluded_dir(path: Path) -> bool:
    """Return True if any path component is a virtualenv or vendored directory.

    A component starting with ``.venv`` counts as a Python virtualenv - the plain
    ``.venv`` plus the dual-OS ``.venv-win`` / ``.venv-linux`` layout - so vendored
    scripts bundled inside any of them never trip a linter. ``node_modules`` and
    ``.git`` match exactly.
    """
    parts = path.parts
    if any(part.startswith(".venv") for part in parts):
        return True
    return any(excluded in parts for excluded in _EXCLUDED_DIRS)


def _is_nested_checkout(dir_parts: tuple[str, ...], project_dir: Path) -> bool:
    """Return True if a directory between ``project_dir`` and the file is its own git checkout.

    A ``.git`` entry marks a separate repository: a plain nested clone or submodule has
    a ``.git`` directory, a linked git worktree (e.g. ``.claude/worktrees/<branch>``) has
    a ``.git`` FILE containing a ``gitdir:`` pointer instead. Either way the directory's
    contents belong to a different branch/repo checkout than ``project_dir`` and must not
    be linted as this project's own source.

    Only directories STRICTLY BELOW ``project_dir`` are checked (the loop starts by
    descending from ``project_dir``, never testing it directly), so the project root's
    own ``.git`` never excludes the project's own files.
    """
    current = project_dir
    for part in dir_parts:
        current = current / part
        if (current / ".git").exists():
            return True
    return False
