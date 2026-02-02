"""CLI command implementations.

Collects all subcommand functions and re-exports them for registration
with the root CLI group.

Contents:
    * Info commands from :mod:`.info`
    * Config commands from :mod:`.config`
    * Email commands from :mod:`.email` (subpackage)
    * Logging commands from :mod:`.logging`
    * Test commands from :mod:`.test_cmd`
    * Commit commands from :mod:`.commit_cmd`
"""

from __future__ import annotations

from .commit_cmd import cli_c, cli_commit
from .config import cli_config, cli_config_deploy, cli_config_generate_examples
from .email import cli_send_email, cli_send_notification
from .info import cli_fail, cli_hello, cli_info
from .logging import cli_logdemo
from .test_cmd import cli_t, cli_test
from .test_integration_cmd import cli_testi, cli_testintegration, cli_ti

__all__ = [
    "cli_c",
    "cli_commit",
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
    "cli_testintegration",
    "cli_testi",
    "cli_ti",
]
