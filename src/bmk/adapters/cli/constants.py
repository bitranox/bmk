"""Shared CLI constants.

Centralizes configuration values used across CLI modules to ensure consistency.

Contents:
    * :data:`CLICK_CONTEXT_SETTINGS` - Shared Click settings for help display.
    * :data:`PASSTHROUGH_CONTEXT_SETTINGS` - Settings for commands that forward args to scripts.
    * :data:`TRACEBACK_SUMMARY_LIMIT` - Character budget for truncated tracebacks.
    * :data:`TRACEBACK_VERBOSE_LIMIT` - Character budget for verbose tracebacks.
"""

from __future__ import annotations

from typing import Any, Final

#: Shared Click context flags so help output stays consistent across commands.
CLICK_CONTEXT_SETTINGS: Final[dict[str, list[str]]] = {"help_option_names": ["-h", "--help"]}

#: Context settings for pass-through commands that accept arbitrary arguments.
#: ignore_unknown_options: Allows --flags to be passed through to the script
#: allow_extra_args: Allows extra positional arguments
#: allow_interspersed_args: Prevents Click from consuming args meant for the script
PASSTHROUGH_CONTEXT_SETTINGS: dict[str, Any] = {
    **CLICK_CONTEXT_SETTINGS,
    "ignore_unknown_options": True,
    "allow_extra_args": True,
    "allow_interspersed_args": False,
}

#: Character budget used when printing truncated tracebacks.
TRACEBACK_SUMMARY_LIMIT: Final[int] = 500

#: Character budget used when verbose tracebacks are enabled.
TRACEBACK_VERBOSE_LIMIT: Final[int] = 10_000

__all__ = [
    "CLICK_CONTEXT_SETTINGS",
    "PASSTHROUGH_CONTEXT_SETTINGS",
    "TRACEBACK_SUMMARY_LIMIT",
    "TRACEBACK_VERBOSE_LIMIT",
]
