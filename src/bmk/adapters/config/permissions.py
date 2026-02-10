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


def get_permission_defaults(config: Config) -> dict[str, int | bool]:
    """Load permission defaults from [lib_layered_config.default_permissions].

    Reads configurable permission defaults for each deployment layer.
    Falls back to lib_layered_config library defaults if not configured.

    Args:
        config: Configuration object with merged settings.

    Returns:
        Dictionary with keys:
            - app_directory: Directory mode for app layer (default 0o755)
            - app_file: File mode for app layer (default 0o644)
            - host_directory: Directory mode for host layer (default 0o755)
            - host_file: File mode for host layer (default 0o644)
            - user_directory: Directory mode for user layer (default 0o700)
            - user_file: File mode for user layer (default 0o600)
            - enabled: Whether permission setting is enabled (default True)

    Example:
        >>> from lib_layered_config import Config
        >>> config = Config({}, {})  # Empty config
        >>> defaults = get_permission_defaults(config)
        >>> defaults["user_directory"] == 0o700
        True
    """
    section = config.get("lib_layered_config", {}).get("default_permissions", {})
    # NOTE: lib_layered_config does not define separate HOST_* constants.
    # Host layer shares defaults with app layer (both world-readable: 755/644).
    # This is intentional per CLAUDE.md "Deployment Permissions" documentation.
    return {
        "app_directory": _get_mode(section, "app_directory", DEFAULT_APP_DIR_MODE),
        "app_file": _get_mode(section, "app_file", DEFAULT_APP_FILE_MODE),
        "host_directory": _get_mode(section, "host_directory", DEFAULT_APP_DIR_MODE),
        "host_file": _get_mode(section, "host_file", DEFAULT_APP_FILE_MODE),
        "user_directory": _get_mode(section, "user_directory", DEFAULT_USER_DIR_MODE),
        "user_file": _get_mode(section, "user_file", DEFAULT_USER_FILE_MODE),
        "enabled": section.get("enabled", True),
    }


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
    defaults = get_permission_defaults(config)
    layer = target.value  # "app", "host", or "user"

    # defaults always contains int values for all layer keys (get_permission_defaults
    # uses lib_layered_config defaults as fallbacks), so cast is safe here.
    dir_mode: int = dir_mode_override if dir_mode_override is not None else int(defaults[f"{layer}_directory"])
    file_mode: int = file_mode_override if file_mode_override is not None else int(defaults[f"{layer}_file"])

    return dir_mode, file_mode


__all__ = [
    "get_modes_for_target",
    "get_permission_defaults",
    "parse_mode",
]
