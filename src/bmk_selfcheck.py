"""Structural integrity check for the interpreter bmk is installed into.

Deliberately a TOP-LEVEL module, not part of the ``bmk`` package: the deployed
Makefile runs it as ``python -m bmk_selfcheck`` before every target, and ``-m``
on a submodule would execute ``bmk/__init__.py`` first. That import costs 0.7s
(measured) against 0.07s for a bare interpreter start, and it would also make
the check depend on the very package whose environment it is auditing.

For the same reason nothing here imports bmk, or anything outside the standard
library.

What it detects: a package tree that was written only PARTIALLY. uv falls back
to a full copy when it cannot hardlink across a filesystem boundary, and that
fallback has repeatedly left a dependency half-installed - a missing
``pip_api._hash``, a missing ``pydantic.functional_serializers``. Every such
file is still listed in its distribution's ``RECORD``, so comparing RECORD
against the filesystem finds it without importing anything.

Contents:
    * :func:`missing_files` - RECORD entries that are not on disk.
    * :func:`main` - Exit 0 when the environment is intact, 1 when it is not.
"""

from __future__ import annotations

import csv
import sys
import sysconfig
from collections.abc import Iterator
from pathlib import Path

# Reported before giving up on listing. The caller reinstalls on ANY miss, so the
# full list is noise; a few names are enough to explain why the repair happened.
_MAX_REPORTED = 5


def _site_packages() -> Path | None:
    """Return the interpreter's ``purelib`` directory, or None if unavailable.

    ``sysconfig`` rather than a ``lib/python*`` glob, because Windows lays the
    directory out as ``Lib/site-packages``.
    """
    location = sysconfig.get_paths().get("purelib")
    if not location:
        return None
    directory = Path(location)
    return directory if directory.is_dir() else None


def _recorded_paths(record: Path) -> Iterator[str]:
    """Yield the relative path from each row of a ``RECORD`` file.

    Bytecode is skipped: ``.pyc`` files are regenerated on demand and are
    routinely removed by cache cleaning, so treating them as damage would report
    a healthy environment as broken.
    """
    with record.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle):
            if not row or not row[0]:
                continue
            relative = row[0]
            if relative.endswith(".pyc") or "__pycache__" in relative:
                continue
            yield relative


def missing_files(site_packages: Path) -> list[str]:
    """Return the RECORD-listed paths that are absent from ``site_packages``.

    An unreadable ``RECORD`` is skipped rather than reported: the caller acts on
    a non-empty result by rebuilding the whole environment, so a permission
    error or a malformed file must not masquerade as corruption and trigger that
    on every run. The decode and CSV errors are as load-bearing as the OS one; a
    RECORD that is not valid UTF-8 otherwise propagates out of the check and
    turns every make into a full rebuild.
    """
    missing: list[str] = []
    for record in site_packages.glob("*.dist-info/RECORD"):
        try:
            recorded = list(_recorded_paths(record))
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        missing.extend(relative for relative in recorded if not (site_packages / relative).exists())
    return missing


def main() -> int:
    """Report environment integrity as a process exit code.

    Returns:
        0 when every recorded file is present, or when the layout cannot be
        inspected at all; 1 when at least one recorded file is missing.

    An uninspectable layout deliberately reports SUCCESS. The caller repairs on
    failure, so answering "broken" whenever the check cannot tell would rebuild
    the environment on every single invocation, on any interpreter layout this
    module does not recognise.
    """
    site_packages = _site_packages()
    if site_packages is None:
        return 0

    missing = missing_files(site_packages)
    if not missing:
        return 0

    # sys.stderr directly, not print: this module is stdlib-only by design and cannot reach
    # for the project's usual output adapters, and the repo bans bare print in src.
    for relative in missing[:_MAX_REPORTED]:
        sys.stderr.write(f"bmk: missing from its environment: {relative}\n")
    if len(missing) > _MAX_REPORTED:
        sys.stderr.write(f"bmk: ... and {len(missing) - _MAX_REPORTED} more\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
