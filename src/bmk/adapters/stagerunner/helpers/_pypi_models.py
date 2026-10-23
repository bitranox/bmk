"""PyPI's JSON API documents, read once at the boundary into typed models.

Purpose
-------
``https://pypi.org/pypi/<name>/json`` (and ``/<name>/<version>/json``) is external data. It is
validated here, once, so the dependency check and the supply-chain cooldown read typed fields and
never crawl a raw dictionary again.

The reading is deliberately lenient field by field: a malformed field or file entry degrades to
what the check treats as "nothing known" (no upload time, no Requires-Python, no requirements)
instead of rejecting the whole document. One bad wheel record must not hide every release of a
package; only a document that is not a JSON object at all is refused.

Contents
--------
* ``parse_moment`` - an RFC 3339 timestamp as an aware datetime, or None.
* ``PypiFile`` - one distribution file of a release (yanked, Requires-Python, upload time).
* ``PypiInfo`` - the ``info`` block (version, requirements).
* ``PypiDocument`` - a whole package or release document.
* ``PypiReleases`` - the ``releases`` map: version string to its files.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "PypiDocument",
    "PypiFile",
    "PypiInfo",
    "PypiReleases",
    "parse_moment",
]

# RFC 3339 allows any number of fraction digits; datetime parses at most six.
_RE_LONG_FRACTION = re.compile(r"(\.\d{6})\d+")


def parse_moment(text: str) -> datetime | None:
    """``text`` as an aware datetime, or None when it is not an RFC 3339 timestamp with a zone.

    Example:
        >>> parse_moment("2026-10-12T00:15:37.7212281Z").isoformat()
        '2026-10-12T00:15:37.721228+00:00'
        >>> parse_moment("2026-10-12T00:15:37") is None
        True
    """
    try:
        moment = datetime.fromisoformat(_RE_LONG_FRACTION.sub(r"\1", text.replace("Z", "+00:00")))
    except ValueError:
        return None
    # An upload time and a locked cutoff are UTC; a naive one would silently mean this machine's zone.
    return moment if moment.tzinfo is not None else None


class PypiFile(BaseModel):
    """One distribution file of a release, as the check judges it.

    Attributes:
        yanked: Whether the file is yanked (PEP 592).
        requires_python: The file's Requires-Python metadata; None when absent or empty.
        uploaded: The upload time; None when absent or not an RFC 3339 timestamp with a zone.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    yanked: bool = False
    requires_python: str | None = None
    uploaded: datetime | None = Field(default=None, alias="upload_time_iso_8601")

    @field_validator("yanked", mode="before")
    @classmethod
    def _yanked_by_truth(cls, value: object) -> bool:
        # Truth, not type: a yanked file must never be offered, whatever spelling the flag arrives in.
        return bool(value)

    @field_validator("requires_python", mode="before")
    @classmethod
    def _requires_python_text(cls, value: object) -> str | None:
        # Missing or empty metadata admits every Python, as pip treats it; anything else is judged as
        # text, and text that is no specifier admits too (see _dependencies._installs_on).
        return str(value) if value else None

    @field_validator("uploaded", mode="before")
    @classmethod
    def _upload_moment(cls, value: object) -> datetime | None:
        # Parsed here with parse_moment, not pydantic's own datetime reader, so the timestamps
        # accepted are exactly the ones a locked cutoff accepts, and a naive one never counts.
        return parse_moment(value) if isinstance(value, str) else None


PypiReleases: TypeAlias = Mapping[str, tuple[PypiFile, ...]]


class PypiInfo(BaseModel):
    """The ``info`` block of a package or release document.

    Attributes:
        version: The newest release (package document) or this release (release document); empty
            when PyPI names none.
        requires_dist: The release's requirement strings; empty when PyPI lists none.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    version: str = ""
    requires_dist: tuple[str, ...] = ()

    @field_validator("version", mode="before")
    @classmethod
    def _version_text(cls, value: object) -> str:
        return str(value) if value else ""

    @field_validator("requires_dist", mode="before")
    @classmethod
    def _requirement_texts(cls, value: object) -> tuple[str, ...]:
        # PyPI sends null for a release without requirements; each entry is judged as text, and one
        # that is no PEP 508 requirement is skipped later, as an installer skips it.
        if not isinstance(value, list):
            return ()
        return tuple(str(entry) for entry in cast("list[object]", value))


class PypiDocument(BaseModel):
    """A package (``/pypi/<name>/json``) or release (``/pypi/<name>/<version>/json``) document.

    Attributes:
        info: The ``info`` block; None when the document carries none.
        releases: Every release's files by version string; None when the document carries no map.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    info: PypiInfo | None = None
    releases: dict[str, tuple[PypiFile, ...]] | None = None

    @field_validator("info", mode="before")
    @classmethod
    def _info_object(cls, value: object) -> dict[str, object] | None:
        # An info that is not an object reads as no info: no version, requirements unreadable.
        return cast("dict[str, object]", value) if isinstance(value, dict) else None

    @field_validator("releases", mode="before")
    @classmethod
    def _release_files(cls, value: object) -> dict[str, list[object]] | None:
        # Tolerant per release and per file: a release whose files are not a list keeps its version
        # (the version alone decides prereleases and the in-range search) with no files, and an entry
        # that is not an object is no file at all.
        if not isinstance(value, dict):
            return None
        return {str(version): _file_objects(files) for version, files in cast("dict[object, object]", value).items()}


def _file_objects(files: object) -> list[object]:
    """The entries of one release's file list that are objects; none when it is not a list."""
    if not isinstance(files, list):
        return []
    return [entry for entry in cast("list[object]", files) if isinstance(entry, dict)]
