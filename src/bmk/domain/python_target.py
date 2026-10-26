"""One Python build to provision and test on: a minor plus its build variant.

Purpose
-------
``test-all`` runs a cell per declared minor, plus a free-threaded cell for each minor
``[tool.ci] free-threaded`` names, the way the CI matrix does. uv spells the free-threaded
build of ``3.15`` as the request ``3.15t``, and that string reaches every uv call and names the
cell's venv (``.venv-3.15t``). The code that compares a venv or a uv listing against the target
needs the minor and the variant separately, so the request is parsed here, once, instead of
being sliced wherever a ``t`` matters.

System Role
-----------
Domain layer: pure value logic, no I/O.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from bmk.domain.enums import PythonVariant

# ASCII digits only: `\d` and str.isdigit() also accept other scripts' digits, which no
# classifier and no uv request uses.
_REQUEST = re.compile(r"([0-9]+\.[0-9]+)(t?)")


class PythonTarget(NamedTuple):
    """A Python minor and the build of it to use.

    Attributes:
        minor: ``X.Y``, as a ``Programming Language :: Python :: X.Y`` classifier names it.
        variant: :attr:`PythonVariant.DEFAULT` (the GIL build) or :attr:`PythonVariant.FREETHREADED`.

    Example:
        >>> PythonTarget.from_request("3.15t")
        PythonTarget(minor='3.15', variant=<PythonVariant.FREETHREADED: 'freethreaded'>)
        >>> PythonTarget("3.15", PythonVariant.FREETHREADED).request
        '3.15t'
    """

    minor: str
    variant: PythonVariant = PythonVariant.DEFAULT

    @property
    def request(self) -> str:
        """The uv request for this build (``3.15`` or ``3.15t``); also the cell's label."""
        return f"{self.minor}t" if self.variant is PythonVariant.FREETHREADED else self.minor

    @classmethod
    def from_request(cls, request: str) -> PythonTarget | None:
        """Parse ``X.Y`` or ``X.Yt``; None for any other spelling.

        uv accepts many more request forms (``3.15.0``, ``pypy@3.15``, ``>=3.12``), but a target
        is only what a classifier names, with or without the free-threaded ``t``.
        """
        match = _REQUEST.fullmatch(request)
        if match is None:
            return None
        variant = PythonVariant.FREETHREADED if match[2] else PythonVariant.DEFAULT
        return cls(match[1], variant)


__all__ = ["PythonTarget"]
