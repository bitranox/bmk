"""Strictly-typed wrappers for the tomlkit functions bmk uses.

tomlkit ships ``py.typed``, but its public surface is annotated with ``Any``
(``dumps(data: Mapping[str, Any]) -> str``, and a parsed document's item access
yields ``Any``). pyright in strict mode treats that as *partially unknown* and
reports ``reportUnknownMemberType`` at every call site.

Wrapping the two functions bmk needs behind explicit, fully-known signatures
keeps the rest of the code strict-clean without disabling the rule anywhere. This
module is the single boundary that touches tomlkit's untyped surface, so the only
``# pyright: ignore`` for this gap lives here - mirroring
``adapters/cli/typed_click.py``, which does the same for rich_click.

Why the return types are ``...[str, Any]`` and not something tighter: a TOML
document is heterogeneous by nature, and an EXPLICIT ``Any`` is accepted by
strict mode, whereas the implicit *Unknown* leaking out of tomlkit is not. The
explicit annotation is what converts the one into the other.

Use this for EDITING a TOML file, where comments and formatting must survive.
For merely READING configuration, use ``_toml_config.load_pyproject_config``,
which parses into typed Pydantic models via rtoml.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Table

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping

__all__ = ["TOMLKitError", "dumps", "inline_table", "is_standard_table", "parse", "table"]


def parse(text: str) -> MutableMapping[str, Any]:
    """Parse TOML text into an editable, comment-preserving document.

    Raises:
        TOMLKitError: If ``text`` is not valid TOML.
    """
    return tomlkit.parse(text)  # pyright: ignore[reportUnknownMemberType]


def dumps(document: Mapping[str, Any]) -> str:
    """Serialize a parsed document back to TOML, byte-identical but for edits."""
    return tomlkit.dumps(document)  # pyright: ignore[reportUnknownMemberType]


def table(*, super_table: bool = False) -> MutableMapping[str, Any]:
    """A new ``[table]``; a super table renders only through its sub-tables (``[tool.uv]``)."""
    return tomlkit.table(is_super_table=super_table)


def inline_table() -> MutableMapping[str, Any]:
    """A new ``{ key = value }`` table."""
    return tomlkit.inline_table()


def is_standard_table(value: object) -> bool:
    """Whether ``value`` is a ``[table]`` of a parsed document, as opposed to an inline ``{ ... }`` one."""
    return isinstance(value, Table)
