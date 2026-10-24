"""PyPI's JSON API at the network edge: a real ``httpx2.Client`` running on ``httpx2.MockTransport``.

Every PyPI download in ``helpers/_dependencies.py`` goes through an ``httpx2.Client`` (one per
``_one_fetch_per_package`` block, else a one-off), so replacing the CLIENT's transport is the one
seam that reaches all of them. The real client still streams the body, raises on an error status
and enforces nothing the test did not ask for, so a test asserts what bmk does with a real
response rather than with a ``MagicMock`` shaped like one. ``httpx2.Client`` is patched only to
add ``transport=``: that is the third-party edge, never bmk's own code.

Imported by bare module name: ``tests/`` has no ``__init__.py`` (see ``uv_stub.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx2

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

__all__ = ["PYPI_JSON_PREFIX", "document_path", "serve_pypi"]

PYPI_JSON_PREFIX = "https://pypi.org/pypi/"


def document_path(request: httpx2.Request) -> str:
    """The ``<name>`` or ``<name>/<version>`` part of a ``https://pypi.org/pypi/.../json`` request.

    Examples:
        >>> document_path(httpx2.Request("GET", "https://pypi.org/pypi/widget/1.2/json"))
        'widget/1.2'
    """
    return str(request.url).removeprefix(PYPI_JSON_PREFIX).removesuffix("/json")


def serve_pypi(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx2.Request], httpx2.Response]) -> None:
    """Route every ``httpx2.Client`` built during the test through ``handler``.

    ``handler`` returns the response, or raises an ``httpx2.RequestError`` (``ConnectError``,
    ``ReadTimeout``) to stand for an unreachable index.
    """
    real_client = httpx2.Client

    def client(**kwargs: Any) -> httpx2.Client:
        return real_client(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx2, "Client", client)
