"""bmk's own ``[bmk]`` configuration section, validated once where the CLI reads it.

Every pipeline command reaches the stage runner through one dispatcher, and that dispatcher
reads this section, so a key here applies to every command alike rather than to whichever
command remembered to pass it on.

Contents:
    * :class:`BmkSettings` - ``package_name``, ``show_warnings`` and ``[bmk.supply_chain]``.
    * :class:`BmkSettingsError` - the section holds a value bmk refuses; one line per problem.
    * :func:`parse_bmk_settings` - the section as settings, or the refusal.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .helpers._supply_chain import SupplyChainSettings

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails


class BmkSettings(BaseModel):
    """The ``[bmk]`` section; a missing key keeps its default, an unknown key is ignored.

    Attributes:
        package_name: Import package override; empty derives it from pyproject.toml.
        show_warnings: Show warnings from stages that passed.
        supply_chain: The cooldown settings bmk writes into a project's ``[tool.uv]``.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    package_name: str = ""
    show_warnings: bool = True
    supply_chain: SupplyChainSettings = SupplyChainSettings()

    @field_validator("package_name", mode="before")
    @classmethod
    def _as_text(cls, value: object) -> str:
        # lib_layered_config reads an unquoted all-digit environment value as an int; the name is
        # still the text the operator wrote.
        return value if isinstance(value, str) else str(value)


class BmkSettingsError(ValueError):
    """The ``[bmk]`` section holds a value bmk refuses.

    Attributes:
        problems: One line per refused value, each naming its key.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def parse_bmk_settings(section: object) -> BmkSettings:
    """Validate the ``[bmk]`` section; anything that is not a table reads as an empty one.

    Args:
        section: The raw ``[bmk]`` value of the loaded configuration.

    Returns:
        The validated settings.

    Raises:
        BmkSettingsError: A value bmk must not use, one line per problem.

    Example:
        >>> parse_bmk_settings({"package_name": "mytool_core"}).package_name
        'mytool_core'
        >>> try:
        ...     parse_bmk_settings({"supply_chain": {"cooldown": "14 Days"}})
        ... except BmkSettingsError as exc:
        ...     print(exc.problems[0].split(":")[0])
        bmk.supply_chain.cooldown '14 Days' is not one bmk may write
    """
    try:
        # Any mapping, not only dict: a section that silently read as empty would run every
        # command under defaults nobody chose.
        raw = dict(cast("Mapping[str, object]", section)) if isinstance(section, Mapping) else {}
        return BmkSettings.model_validate(raw)
    except ValidationError as exc:
        raise BmkSettingsError([_problem(item) for item in exc.errors(include_url=False)]) from exc


def _problem(item: ErrorDetails) -> str:
    """One refusal line: a validator's own sentence verbatim, else ``bmk.<key>: <reason>``."""
    ctx = item.get("ctx") or {}
    if item["type"] == "value_error" and "error" in ctx:
        # The supply-chain validators already name the key and quote the value in their sentence.
        return str(ctx["error"])
    location = ".".join(str(part) for part in item["loc"])
    return f"bmk.{location}: {item['msg']}"


__all__ = ["BmkSettings", "BmkSettingsError", "parse_bmk_settings"]
