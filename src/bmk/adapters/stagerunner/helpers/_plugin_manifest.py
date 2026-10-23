"""Typed boundary model for a Claude Code ``.claude-plugin/plugin.json`` manifest.

bmk reads exactly one key of this file - ``version`` - and writes it back when the
package version moves past it (``_sync_initconf.sync_plugin_version``), and compares it
across tags before a release (``_release.shipped_skill_needs_a_bump``). Every other key
belongs to Claude Code's marketplace machinery, so the model keeps them untouched
(``extra="allow"``) and in their original order: a rewrite must change ``version`` and
nothing else, byte for byte, or every sync would churn the manifest's diff.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PrivateAttr,
    ValidationError,
    ValidatorFunctionWrapHandler,
    model_validator,
)

__all__ = ["PluginManifest", "PluginManifestError"]


class PluginManifestError(ValueError):
    """The manifest text is not a JSON object, so it holds no version to read."""


def _coerce_version(v: Any) -> str:
    """Stringify whatever the manifest holds under ``version``.

    ``str()`` of the raw JSON value, never a stricter parse: a number (``1.5``) still
    orders as a PEP 440 version, and a ``null`` or ``true`` becomes text that does not,
    so the caller's version check refuses it rather than this model raising. Only an
    ABSENT key reads as ``""`` (the field default).
    """
    return v if isinstance(v, str) else str(v)


class PluginManifest(BaseModel):
    """``.claude-plugin/plugin.json``: the version bmk syncs, plus every key it does not own.

    Attributes:
        version: The plugin version as text; ``""`` when the manifest has none.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    version: Annotated[str, BeforeValidator(_coerce_version)] = ""

    # The source's key order. Pydantic dumps declared fields before extras, which would
    # move "version" to the top of a manifest that had it after "name"; this restores the
    # order the file had, so a rewrite differs from the original in the version value only.
    _key_order: tuple[str, ...] = PrivateAttr(default=())

    @model_validator(mode="wrap")
    @classmethod
    def _remember_key_order(cls, data: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        manifest = handler(data)
        if isinstance(manifest, PluginManifest) and isinstance(data, dict):
            manifest._key_order = tuple(str(key) for key in cast("dict[str, Any]", data))
        return manifest

    @classmethod
    def from_json(cls, text: str) -> PluginManifest:
        """Parse manifest text.

        The stdlib parser, not pydantic's, so number, duplicate-key and escape handling
        are exactly what a ``json.dumps`` round trip of the same file preserves.

        Args:
            text: The manifest file's content.

        Returns:
            The parsed manifest.

        Raises:
            json.JSONDecodeError: The text is not JSON.
            PluginManifestError: The JSON is not an object (a list, a string, ...).

        Example:
            >>> PluginManifest.from_json('{"name": "x", "version": "1.2.0"}').version
            '1.2.0'
        """
        try:
            return cls.model_validate(json.loads(text))
        except ValidationError as exc:
            raise PluginManifestError("not a JSON object") from exc

    def with_version(self, version: str) -> PluginManifest:
        """A copy carrying ``version``, every other key unchanged.

        Args:
            version: The new plugin version.

        Returns:
            The updated manifest.
        """
        return self.model_copy(update={"version": version})

    def to_json(self) -> str:
        """Serialise the way ``json.dumps(data, indent=2)`` plus a newline always has.

        Keys keep the source's order; a key the source lacked (a ``version`` added to a
        manifest that had none) goes last, as assigning it into the parsed dict did. An
        unset ``version`` stays absent rather than appearing as ``""``.

        Returns:
            The manifest text, ending in a newline.

        Example:
            >>> PluginManifest.from_json('{"name": "x", "version": "1"}').with_version("2").to_json()
            '{\\n  "name": "x",\\n  "version": "2"\\n}\\n'
        """
        dumped = self.model_dump(exclude_unset=True)
        ordered: dict[str, Any] = {key: dumped[key] for key in self._key_order if key in dumped}
        ordered.update(dumped)
        return json.dumps(ordered, indent=2) + "\n"
