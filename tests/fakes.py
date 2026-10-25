"""Typed stand-ins for a module function a test replaces with ``monkeypatch.setattr``.

A ``lambda`` passed to ``monkeypatch.setattr`` has no declared parameter types, so pyright strict
reports it as partially unknown, and nothing checks that the fake returns what the real function
returns. :func:`fake_of` reads the real function for its type only: the fake it builds has the
same signature, and the value it returns must have the real return type.

The two steps (``fake_of(real).returning(value)``) are what make that second check real. A single
``returning(real, value)`` call solves the return type from BOTH arguments, so a wrong value just
widens it to a union and type-checks.

Use it for a function with ONE signature (bmk's own helpers). For an overloaded one such as
``shutil.which`` or ``subprocess.run``, pyright binds the overload that fits the platform and Python
it is checking, so the fake's type changes per CI cell; write a small typed function instead.

Imported by bare module name: ``tests/`` has no ``__init__.py`` (see ``uv_stub.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["fake_of"]

_P = ParamSpec("_P")
_R = TypeVar("_R")


class _FakeOf(Generic[_P, _R]):
    """The signature and return type of one real function, ready to build a fake from."""

    def __init__(self, real: Callable[_P, _R]) -> None:
        self._real = real

    def returning(self, value: _R) -> Callable[_P, _R]:
        """A fake that ignores its arguments and always returns ``value``."""

        def fake(*_args: _P.args, **_kwargs: _P.kwargs) -> _R:
            return value

        return fake


def fake_of(real: Callable[_P, _R]) -> _FakeOf[_P, _R]:
    """Start a fake for ``real``, typed exactly like it; ``real`` is never called.

    Example:
        >>> def latest(name: str) -> str | None: ...
        >>> fake_of(latest).returning("1.0.0")("anything")
        '1.0.0'
    """
    return _FakeOf(real)
