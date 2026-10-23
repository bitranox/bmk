#!/usr/bin/env python3
"""Version bump utility for pyproject.toml and CHANGELOG.md.

Standalone script that bumps the project version in project files:
- Updates version in pyproject.toml (preserves file formatting)
- Renames [Unreleased] section in CHANGELOG.md to new version with timestamp
- Creates new [Unreleased] section above the versioned entry

The version rules themselves live in ``bmk.domain.version``, shared with the release
gate so the two cannot disagree about what a project version may be. A bump always
lands on a plain release: a non-final version (``1.2.3rc1``, ``1.2.3.dev4``) is
FINALIZED to ``1.2.3`` rather than stepped past it.

Uses _toml_config for TOML parsing to centralize configuration access,
and a tomlkit round-trip to preserve file formatting when writing.

A bump is all or nothing. It also writes the files ``_sync_initconf`` keeps in line with the
version (``src/<pkg>/__init__conf__.py``, ``src/<pkg>/makefile/Makefile``,
``.claude-plugin/plugin.json``) and re-locks a committed ``uv.lock``, and every one of those is
put back byte for byte when the bump stops short of success: an exception, Ctrl-C, SIGTERM or
SIGHUP (a CI cancel, a closed terminal). Half-applied, a re-run would bump a second time and skip a
version. One case cannot be undone: on Windows a parent's ``terminate()`` is TerminateProcess,
which ends the process without running any of its code.

Contents:
    * :func:`update_pyproject` - Update version in pyproject.toml.
    * :func:`update_changelog` - Update CHANGELOG.md with new version section.
    * :func:`main` - CLI entry point.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from bmk.adapters.stagerunner.helpers import _typed_tomlkit
from bmk.adapters.stagerunner.helpers._sync_initconf import (
    sync_initconf_version,
    sync_makefile_cooldown,
    sync_makefile_version,
    sync_plugin_version,
    synced_paths,
)
from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config
from bmk.adapters.stagerunner.venv import lock_project
from bmk.domain.enums import BumpPart
from bmk.domain.version import next_version

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from types import FrameType

# What signal.signal accepts and returns: a function, SIG_DFL / SIG_IGN, or None for a handler
# installed outside Python.
_Handler: TypeAlias = "Callable[[int, FrameType | None], Any] | int | None"


def update_pyproject(project_dir: Path, new_version: str) -> str:
    """Update version in pyproject.toml, preserving file formatting.

    Uses toml_config for reading and a tomlkit round-trip for writing, which keeps comments,
    formatting, ordering and the value's quote style. A text match on ``version = "..."`` is what
    this replaced: it missed ``version="0.1.0"`` (changing nothing while the bump reported success)
    and could rewrite a ``version`` key in another table that came first.

    Args:
        project_dir: Path to project root containing pyproject.toml.
        new_version: New version string to set.

    Returns:
        Previous version string.

    Raises:
        ValueError: If [project].version not found in pyproject.toml.
        FileNotFoundError: If pyproject.toml does not exist.
    """
    pyproject_path = project_dir / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")

    # Parse TOML to get current version using toml_config
    config = load_pyproject_config(pyproject_path)
    old_version = config.project.version
    if not old_version:
        msg = "Could not find [project].version in pyproject.toml"
        raise ValueError(msg)

    document = _typed_tomlkit.parse(content)
    project = document["project"]
    project["version"] = _typed_tomlkit.string_like(project["version"], new_version)
    pyproject_path.write_text(_typed_tomlkit.dumps(document), encoding="utf-8")
    return old_version


def find_unreleased_line(lines: list[str]) -> int | None:
    """Find index of ## [Unreleased] line (case-insensitive).

    Args:
        lines: List of lines from CHANGELOG.md.

    Returns:
        Line index if found, None otherwise.
    """
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("## [unreleased]"):
            return i
    return None


def find_first_version_line(lines: list[str]) -> int | None:
    """Find index of the first versioned ``## [...]`` line (any version spelling).

    Args:
        lines: List of lines from CHANGELOG.md.

    Returns:
        Line index of first versioned section, None if not found.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## [") and not stripped.lower().startswith("## [unreleased]"):
            return i
    return None


def update_changelog(project_dir: Path, new_version: str) -> None:
    """Update CHANGELOG.md - rename [Unreleased] to new version, add new [Unreleased].

    If [Unreleased] section exists:
    - Keeps [Unreleased] header
    - Inserts blank line and new version header below it

    If no [Unreleased] section:
    - Inserts [Unreleased] and new version before first existing version

    Args:
        project_dir: Path to project root containing CHANGELOG.md.
        new_version: New version string to add.
    """
    changelog_path = project_dir / "CHANGELOG.md"
    if not changelog_path.exists():
        return

    content = changelog_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_version_line = f"## [{new_version}] {timestamp}"

    unreleased_idx = find_unreleased_line(lines)

    if unreleased_idx is not None:
        # Replace [Unreleased] with new [Unreleased] + new version
        lines[unreleased_idx] = "## [Unreleased]"
        lines.insert(unreleased_idx + 1, "")
        lines.insert(unreleased_idx + 2, new_version_line)
    else:
        # No [Unreleased] - insert before first version entry
        first_version_idx = find_first_version_line(lines)
        if first_version_idx is not None:
            lines.insert(first_version_idx, "## [Unreleased]")
            lines.insert(first_version_idx + 1, "")
            lines.insert(first_version_idx + 2, new_version_line)
            lines.insert(first_version_idx + 3, "")

    changelog_path.write_text("\n".join(lines), encoding="utf-8")


# A file's bytes before the bump, or None when it did not exist yet (the bump may create it).
_Snapshot: TypeAlias = "dict[Path, bytes | None]"


def _snapshot(project_dir: Path) -> _Snapshot:
    """The files a bump rewrites, byte for byte, and the ones it may create, as None.

    Bytes, not text: a text round trip turns CRLF into the platform's newline, so an undone
    bump would still leave a whole-file diff behind. uv.lock is in it because the re-lock
    rewrites it, and a Ctrl-C after that write would otherwise leave it on the new version;
    the synced files because the bump writes them too.
    """
    paths = [
        project_dir / "pyproject.toml",
        project_dir / "CHANGELOG.md",
        project_dir / "uv.lock",
        *synced_paths(project_dir),
    ]
    # Only a path that does not exist at all is recorded as created-by-the-bump: one that exists
    # without being a file (a directory, a dangling symlink) is not the bump's to delete.
    return {
        path: path.read_bytes() if path.is_file() else None
        for path in paths
        if path.is_file() or not os.path.lexists(path)
    }


def _restore_one(path: Path, data: bytes | None) -> str | None:
    """Put one file back unless it already holds ``data``; returns why it could not be, or None.

    ``None`` means the file did not exist before the bump, so a copy the bump created is removed.

    Written in place, never by temp file and rename: a rename would replace a symlink rather than
    the file behind it, and needs write access to the directory, which the bump itself never did.
    The price is that a write failing midway (disk full) leaves neither version, so the reason
    says the contents may be incomplete rather than calling the file still bumped.
    """
    if data is None:
        return _remove_created(path)
    try:
        if path.read_bytes() == data:
            return None
    except FileNotFoundError:
        pass  # deleted during the bump: the write below recreates it
    except OSError as error:
        return f"could not be read, so it was not rewritten ({error.strerror or error})"
    try:
        path.write_bytes(data)
    except OSError as error:
        return f"could not be rewritten, its contents may be incomplete ({error.strerror or error})"
    return None


def _remove_created(path: Path) -> str | None:
    """Remove a file the bump created; returns why it could not be, or None."""
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        return f"was created by the bump and could not be removed ({error.strerror or error})"
    return None


def _restore(originals: _Snapshot) -> list[tuple[Path, str]]:
    """Put back what :func:`_snapshot` read, every file on its own; returns the ones that failed."""
    outcomes = ((path, _restore_one(path, data)) for path, data in originals.items())
    return [(path, reason) for path, reason in outcomes if reason is not None]


class _Terminated(BaseException):
    """A SIGTERM or SIGHUP turned into an exception, so the bump's undo runs before the process exits.

    A BaseException, like KeyboardInterrupt: an ``except Exception`` on the way must not swallow it.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


# Set while the undo runs; read by the signal handler, which cannot be handed any state.
_UNDOING = threading.Event()


def _on_signal(signum: int, _frame: object) -> None:
    # A second signal (the stage runner terminating its children after a Ctrl-C) must not cut
    # the undo short and leave half the files restored.
    if _UNDOING.is_set():
        return
    raise _Terminated(signum)


def _termination_signals() -> list[signal.Signals]:
    """SIGTERM, and SIGHUP where it exists (not on Windows)."""
    return [sig for name in ("SIGTERM", "SIGHUP") if (sig := getattr(signal, name, None)) is not None]


@contextmanager
def _handlers(handlers: dict[signal.Signals, _Handler]) -> Generator[None]:
    """Install ``handlers`` for the block and put the previous ones back after it.

    Restored because ``main`` also runs in-process (the tests): a handler left behind would turn
    the host process's own SIGTERM into this module's exception. Python accepts a handler only in
    the main thread, so elsewhere the block runs with the handlers as they are.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {sig: signal.signal(sig, handler) for sig, handler in handlers.items()}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _undo_bump(originals: _Snapshot, new_version: str) -> int:
    """Restore the snapshot and say exactly what state the files are in; always exit code 1.

    Ctrl-C, SIGTERM and SIGHUP are held off while the files are written back: the process is
    ending either way, and an interrupted restore is the one outcome worse than none.
    """
    _UNDOING.set()
    try:
        with _handlers({signal.SIGINT: signal.SIG_IGN}):
            failed = _restore(originals)
    finally:
        _UNDOING.clear()
    if not failed:
        print(f"Error: the bump to {new_version} was undone; fix the cause and bump again", file=sys.stderr)
        return 1
    print(f"Error: the bump to {new_version} could NOT be fully undone; not back as they were:", file=sys.stderr)
    for path, reason in failed:
        print(f"  {path}: {reason}", file=sys.stderr)
    print(
        "Restore those files before bumping again (git checkout -- <file>; `uv lock` rebuilds uv.lock).",
        file=sys.stderr,
    )
    return 1


def _apply_bump(project_dir: Path, new_version: str) -> str | None:
    """Write the bump, sync the files that carry the version, and re-lock.

    Returns:
        Why it failed, or None when it is complete.
    """
    update_pyproject(project_dir, new_version)
    update_changelog(project_dir, new_version)
    sync_initconf_version(project_dir)
    sync_makefile_version(project_dir)
    sync_makefile_cooldown(project_dir)
    sync_plugin_version(project_dir)
    # uv.lock records the project's own version; left stale it fails `uv sync --locked`
    # and CI's `uv export --locked` on the very commit that is about to be released.
    # Not quiet: when it fails, uv's own reason is the only useful part of the message.
    if (project_dir / "uv.lock").is_file() and not lock_project(project_dir, quiet=False):
        return "`uv lock` failed (see above)"
    return None


def _read_bump(project_dir: Path, part: str) -> tuple[str, str, _Snapshot]:
    """Current version, next version and the snapshot - everything read before the first write."""
    config = load_pyproject_config(project_dir / "pyproject.toml")
    current_version = config.project.version
    if not current_version:
        msg = "Could not find [project].version in pyproject.toml"
        raise ValueError(msg)
    return current_version, next_version(current_version, BumpPart(part)), _snapshot(project_dir)


def main() -> int:
    """CLI entry point for version bump utility.

    SIGTERM and SIGHUP raise :class:`_Terminated` while it runs, so they undo a bump the way
    Ctrl-C does; the ``__main__`` block turns that into exit code 128 + the signal number.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    parser = argparse.ArgumentParser(description="Bump version in pyproject.toml and CHANGELOG.md")
    parser.add_argument("part", choices=[p.value for p in BumpPart], help="Version part to bump")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory")
    args, _unknown = parser.parse_known_args()

    with _handlers(dict.fromkeys(_termination_signals(), _on_signal)):
        return _bump(args.project_dir, args.part)


def _bump(project_dir: Path, part: str) -> int:
    """Read, apply and on any way out short of success undo the bump; the exit code."""
    try:
        old_version, new_version, originals = _read_bump(project_dir, part)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: File not found - {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Undone on ANY way out short of success (a failed re-lock, an unwritable file, Ctrl-C,
    # SIGTERM, SIGHUP): half-applied, a re-run would bump a second time and skip a version.
    try:
        failure = _apply_bump(project_dir, new_version)
    except (ValueError, OSError) as e:
        failure = str(e)
    except BaseException:
        _undo_bump(originals, new_version)
        raise
    if failure is not None:
        print(f"Error: {failure}", file=sys.stderr)
        return _undo_bump(originals, new_version)

    print(f"Bumped version: {old_version} -> {new_version}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except _Terminated as terminated:
        # The shell convention for a process ended by a signal it handled.
        sys.exit(128 + terminated.signum)
