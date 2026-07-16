"""Type-safe domain enums for output formats and deployment targets."""

from __future__ import annotations

from enum import Enum


class OutputFormat(str, Enum):
    """Output format options for configuration display.

    Defines valid output format choices for the config command.
    Inherits from str to allow direct string comparison and Click integration.

    Attributes:
        HUMAN: Human-readable TOML-like output format.
        JSON: Machine-readable JSON output format.

    Example:
        >>> OutputFormat.HUMAN.value
        'human'
        >>> OutputFormat.JSON == "json"
        True
    """

    HUMAN = "human"
    JSON = "json"


class ToolOutputFormat(str, Enum):
    """Tool output mode for the stage runner.

    ``JSON`` captures tool output and shows it only on failure (machine-readable,
    the default); ``TEXT`` streams full verbose output. Distinct from
    :class:`OutputFormat` (which is ``human`` vs ``json`` for config display).

    Example:
        >>> ToolOutputFormat.JSON == "json"
        True
    """

    TEXT = "text"
    JSON = "json"

    @classmethod
    def from_env(cls, value: str | None) -> ToolOutputFormat:
        """Decode a raw ``BMK_OUTPUT_FORMAT`` value to a member.

        ``TEXT`` only when the value is exactly ``"text"``; unset or anything else is the
        ``JSON`` default. The single place that env var's string is interpreted, so the
        ``BMK_OUTPUT_FORMAT`` rule cannot drift between call sites.
        """
        return cls.TEXT if value == cls.TEXT.value else cls.JSON


class BumpPart(str, Enum):
    """Semantic-version component to increment on a version bump.

    Inherits from str so the value crosses the CLI/subprocess boundary unchanged
    (argparse ``choices`` and the ``_bump_version`` helper argv both use the wire
    strings) while business logic dispatches on typed members.

    Attributes:
        MAJOR: Increment the major component (X+1.0.0).
        MINOR: Increment the minor component (X.Y+1.0).
        PATCH: Increment the patch component (X.Y.Z+1).

    Example:
        >>> BumpPart.MINOR.value
        'minor'
        >>> BumpPart.PATCH == "patch"
        True
    """

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class DeployTarget(str, Enum):
    """Configuration deployment target layers.

    Defines valid target layers for configuration file deployment.
    Inherits from str to allow direct string comparison and Click integration.

    Attributes:
        APP: System-wide application configuration (requires privileges).
        HOST: System-wide host-specific configuration (requires privileges).
        USER: User-specific configuration (~/.config on Linux).

    Example:
        >>> DeployTarget.USER.value
        'user'
        >>> DeployTarget.APP == "app"
        True
    """

    APP = "app"
    HOST = "host"
    USER = "user"


__all__ = [
    "BumpPart",
    "DeployTarget",
    "OutputFormat",
    "ToolOutputFormat",
]
