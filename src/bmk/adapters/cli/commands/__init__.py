"""CLI command implementations.

Collects all subcommand functions and re-exports them for registration
with the root CLI group.

Contents:
    * Info commands from :mod:`.info`
    * Config commands from :mod:`.config`
    * Email commands from :mod:`.email` (subpackage)
    * Logging commands from :mod:`.logging`
    * Test commands from :mod:`.test_cmd`
"""

from __future__ import annotations

from .config import cli_config, cli_config_deploy, cli_config_generate_examples
from .email import cli_send_email, cli_send_notification
from .info import cli_fail, cli_hello, cli_info
from .logging import cli_logdemo
from .test_cmd import cli_t, cli_test

__all__ = [
    "cli_config",
    "cli_config_deploy",
    "cli_config_generate_examples",
    "cli_fail",
    "cli_hello",
    "cli_info",
    "cli_logdemo",
    "cli_send_email",
    "cli_send_notification",
    "cli_t",
    "cli_test",
]
