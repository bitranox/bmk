"""CLI command implementations.

Collects all subcommand functions and re-exports them for registration
with the root CLI group.

Contents:
    * Info commands from :mod:`.info`
    * Config commands from :mod:`.config`
    * Email commands from :mod:`.email` (subpackage)
    * Logging commands from :mod:`.logging`
    * Test commands from :mod:`.testsuite_cmd`
    * Commit commands from :mod:`.commit_cmd`
    * Bump commands from :mod:`.bump_cmd`
    * Build commands from :mod:`.build_cmd`
    * Push commands from :mod:`.push_cmd`
    * Dependencies commands from :mod:`.dependencies_cmd`
    * Clean commands from :mod:`.clean_cmd`
    * Coverage commands from :mod:`.cov_cmd`
    * Release commands from :mod:`.release_cmd`
    * Run commands from :mod:`.run_cmd`
    * Custom commands from :mod:`.custom_cmd`
    * Install commands from :mod:`.install_cmd`
"""

from __future__ import annotations

from .build_cmd import cli_bld, cli_build
from .bump_cmd import cli_b, cli_bmp, cli_bump
from .clean_cmd import cli_cl, cli_clean, cli_cln
from .commit_cmd import cli_c, cli_commit
from .config import cli_config, cli_config_deploy, cli_config_generate_examples
from .cov_cmd import cli_codecov, cli_cov, cli_coverage
from .custom_cmd import cli_custom
from .dependencies_cmd import cli_d, cli_dependencies, cli_deps
from .email import cli_send_email, cli_send_notification
from .info import cli_fail, cli_hello, cli_info
from .install_cmd import cli_install
from .logging import cli_logdemo
from .push_cmd import cli_psh, cli_push, cli_push_p
from .release_cmd import cli_r, cli_rel, cli_release
from .run_cmd import cli_run
from .test_integration_cmd import cli_testi, cli_testintegration, cli_ti
from .testsuite_cmd import cli_t, cli_test

__all__ = [
    "cli_b",
    "cli_bld",
    "cli_bmp",
    "cli_build",
    "cli_bump",
    "cli_c",
    "cli_cl",
    "cli_clean",
    "cli_cln",
    "cli_codecov",
    "cli_commit",
    "cli_config",
    "cli_config_deploy",
    "cli_config_generate_examples",
    "cli_cov",
    "cli_coverage",
    "cli_custom",
    "cli_d",
    "cli_dependencies",
    "cli_deps",
    "cli_fail",
    "cli_hello",
    "cli_info",
    "cli_install",
    "cli_logdemo",
    "cli_psh",
    "cli_push",
    "cli_push_p",
    "cli_r",
    "cli_rel",
    "cli_release",
    "cli_run",
    "cli_send_email",
    "cli_send_notification",
    "cli_t",
    "cli_test",
    "cli_testintegration",
    "cli_testi",
    "cli_ti",
]
