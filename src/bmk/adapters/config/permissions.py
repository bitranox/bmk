"""Permission settings loader for config deployment.

Provides functions to load permission defaults from configuration and
compute effective permission modes for deployment targets.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from lib_layered_config import (
    DEFAULT_APP_DIR_MODE,
    DEFAULT_APP_FILE_MODE,
    DEFAULT_USER_DIR_MODE,
    DEFAULT_USER_FILE_MODE,
)
from pydantic import BaseModel, ConfigDict

from bmk.domain.enums import DeployTarget

if TYPE_CHECKING:
    from lib_layered_config import Config

logger = logging.getLogger(__name__)


def parse_mode(value: int | str, default: int) -> int:
    """Parse a permission mode value from config.

    Accepts either an integer or an octal string (e.g., "0o755" or "755").

    Args:
        value: Integer mode or octal string.
        default: Fallback value if parsing fails.

    Returns:
        Integer permission mode.

    Example:
        >>> parse_mode(493, 0o755)
        493
        >>> parse_mode("0o755", 0o644)
        493
        >>> parse_mode("755", 0o644)
        493
    """
    if isinstance(value, int):
        return value
    # value is str at this point
    try:
        # Handle both "755" and "0o755" formats
        if value.startswith("0o"):
            return int(value, 0)  # int() auto-detects 0o prefix
        return int(value, 8)  # Plain "755" needs explicit base 8
    except ValueError:
        logger.warning("Invalid permission mode '%s', falling back to default %o", value, default)
        return default


def _get_mode(section: dict[str, int | str | bool], key: str, default: int) -> int:
    """Get a mode value from config section, parsing octal strings."""
    raw = section.get(key, default)
    if isinstance(raw, bool):
        return default
    return parse_mode(raw, default)


class PermissionDefaults(BaseModel):
    """The deploy permission modes, one field per layer.

    A fixed schema, so it is a model rather than a dict. As a dict it was indexed with a
    constructed key - ``defaults[f"{layer}_directory"]`` - which needed an int() cast and a
    comment arguing the cast was safe. Neither is needed once the fields are typed, and a
    typo in a layer name is now a static error rather than a KeyError at deploy time.
    """

    model_config = ConfigDict(frozen=True)

    app_directory: int = DEFAULT_APP_DIR_MODE
    app_file: int = DEFAULT_APP_FILE_MODE
    # lib_layered_config defines no separate HOST_* constants: the host layer shares the
    # app layer's defaults, both world-readable (755/644). Intentional, see CLAUDE.md
    # "Deployment Permissions".
    host_directory: int = DEFAULT_APP_DIR_MODE
    host_file: int = DEFAULT_APP_FILE_MODE
    user_directory: int = DEFAULT_USER_DIR_MODE
    user_file: int = DEFAULT_USER_FILE_MODE
    enabled: bool = True

    def modes_for(self, target: DeployTarget) -> tuple[int, int]:
        """Return (dir_mode, file_mode) for one layer."""
        return {
            DeployTarget.APP: (self.app_directory, self.app_file),
            DeployTarget.HOST: (self.host_directory, self.host_file),
            DeployTarget.USER: (self.user_directory, self.user_file),
        }[target]


def get_permission_defaults(config: Config) -> PermissionDefaults:
    """Load permission defaults from [lib_layered_config.default_permissions].

    Reads configurable permission defaults for each deployment layer, falling back to
    lib_layered_config's own defaults where the key is absent or unparseable.

    Args:
        config: Configuration object with merged settings.

    Returns:
        A PermissionDefaults; every field has a default, so this never fails.

    Example:
        >>> from lib_layered_config import Config
        >>> config = Config({}, {})  # Empty config
        >>> get_permission_defaults(config).user_directory == 0o700
        True
    """
    section = config.get("lib_layered_config", {}).get("default_permissions", {})
    # Each mode is read through _get_mode rather than handed to Pydantic raw: a mode may be
    # written as 0o755, "0o755", "755" or 493, and a bad one must fall back to the default
    # with a warning rather than fail the deploy.
    return PermissionDefaults(
        app_directory=_get_mode(section, "app_directory", DEFAULT_APP_DIR_MODE),
        app_file=_get_mode(section, "app_file", DEFAULT_APP_FILE_MODE),
        host_directory=_get_mode(section, "host_directory", DEFAULT_APP_DIR_MODE),
        host_file=_get_mode(section, "host_file", DEFAULT_APP_FILE_MODE),
        user_directory=_get_mode(section, "user_directory", DEFAULT_USER_DIR_MODE),
        user_file=_get_mode(section, "user_file", DEFAULT_USER_FILE_MODE),
        enabled=bool(section.get("enabled", True)),
    )


def get_modes_for_target(
    target: DeployTarget,
    config: Config,
    *,
    dir_mode_override: int | None = None,
    file_mode_override: int | None = None,
) -> tuple[int, int]:
    """Get dir_mode and file_mode for a target, applying overrides.

    Retrieves permission modes for a deployment target from configuration,
    then applies any CLI overrides. CLI overrides take precedence over
    configured defaults.

    Args:
        target: The deployment target layer (app, host, or user).
        config: Configuration object with merged settings.
        dir_mode_override: CLI override for directory mode. If provided,
            takes precedence over configuration.
        file_mode_override: CLI override for file mode. If provided,
            takes precedence over configuration.

    Returns:
        Tuple of (dir_mode, file_mode) to pass to deploy_config.
        Values are integers (octal mode values). Always returns valid modes
        since get_permission_defaults provides fallbacks for all targets.

    Example:
        >>> from lib_layered_config import Config
        >>> config = Config({}, {})
        >>> dir_mode, file_mode = get_modes_for_target(
        ...     DeployTarget.USER, config
        ... )
        >>> dir_mode == 0o700
        True
    """
    dir_default, file_default = get_permission_defaults(config).modes_for(target)
    dir_mode = dir_mode_override if dir_mode_override is not None else dir_default
    file_mode = file_mode_override if file_mode_override is not None else file_default
    return dir_mode, file_mode


__all__ = [
    "get_modes_for_target",
    "get_permission_defaults",
    "parse_mode",
]
