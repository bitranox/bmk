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
    "DeployTarget",
    "OutputFormat",
    "ToolOutputFormat",
]
