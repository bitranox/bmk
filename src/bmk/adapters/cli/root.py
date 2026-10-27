"""Root CLI command group and global option handling.

Defines the top-level Click command group that serves as the entry point for
all subcommands. Handles global flags like --traceback, --profile, and --set.

Contents:
    * :func:`cli` - Root command group with global options.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import rich_click as click

from bmk import __init__conf__

from . import safe_console
from .config_load import load_config, start_logging
from .constants import CLICK_CONTEXT_SETTINGS
from .context import apply_traceback_preferences, store_cli_context
from .typed_click import option, version_option

if TYPE_CHECKING:
    from collections.abc import Callable

    from bmk.composition import AppServices


# Commands that must not rewrite the Makefile first. `install` writes it itself. A release refuses a
# working tree with uncommitted changes, so a Makefile it had just rewritten would make every release
# after a new bmk version refuse, naming a change the same command made; the next target updates it.
_SKIP_MAKEFILE_CHECK = frozenset({"install", "release", "rel", "r"})


@click.group(
    help=__init__conf__.title,
    context_settings=CLICK_CONTEXT_SETTINGS,
    invoke_without_command=True,
)
@version_option(
    version=__init__conf__.version,
    prog_name=__init__conf__.shell_command,
    message=f"{__init__conf__.shell_command} version {__init__conf__.version}",
)
@option(
    "--traceback/--no-traceback",
    is_flag=True,
    default=False,
    help="Show full Python traceback on errors",
)
@option(
    "--profile",
    type=str,
    default=None,
    help="Load configuration from a named profile (e.g., 'production', 'test')",
)
@option(
    "--set",
    "set_overrides",
    multiple=True,
    default=(),
    metavar="SECTION.KEY=VALUE",
    help="Override a configuration setting (repeatable).",
)
@option(
    "--env-file",
    "env_file",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True),
    default=None,
    help="Explicit .env file path (skips upward directory search).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    traceback: bool,
    profile: str | None,
    set_overrides: tuple[str, ...],
    env_file: str | None,
) -> None:
    """Root command storing global flags and syncing shared traceback state.

    Loads configuration once with the profile, applies any ``--set`` overrides,
    and stores it in the Click context for all subcommands to access. A load
    failure is stored rather than raised, so a command that does not read the
    configuration still runs. Mirrors
    the traceback flag into ``lib_cli_exit_tools.config`` so downstream helpers
    observe the preference.

    Example:
        >>> from click.testing import CliRunner
        >>> runner = CliRunner()
        >>> result = runner.invoke(cli, ["info"])
        >>> result.exit_code
        0
    """
    # ctx.obj is always the services factory (production or test). click types it as Any, which
    # callable() would narrow to a callable returning object; declared first, it keeps its type.
    factory: Callable[[], AppServices] | None = ctx.obj
    if not callable(factory):
        raise RuntimeError("Services factory not provided. This is a bug.")
    services = factory()
    # A load failure is recorded, not reported here: see config_load for who reports it.
    loaded = load_config(services, profile=profile, env_file=env_file, set_overrides=set_overrides)
    loaded = start_logging(services, loaded.config, loaded.error, env_file=env_file)
    store_cli_context(
        ctx,
        traceback=traceback,
        config=loaded.config,
        services=services,
        profile=profile,
        set_overrides=set_overrides,
        env_file=env_file,
        config_error=loaded.error,
    )
    apply_traceback_preferences(traceback)

    if ctx.invoked_subcommand is not None and ctx.invoked_subcommand not in _SKIP_MAKEFILE_CHECK:
        try:
            # Same lazy-import rationale as `_register_commands` below: importing
            # `.commands` here (before `cli` finishes definition) is deferred by convention.
            from .commands.install_cmd import check_makefile_update  # noqa: PLC0415

            check_makefile_update()
        except (OSError, UnicodeDecodeError, click.Abort):
            # Best-effort convenience check; an I/O error, a Makefile that is not UTF-8 text, or
            # a declined prompt (non-interactive Abort) must never block the command the user
            # actually ran.
            pass

    if ctx.invoked_subcommand is None:
        safe_console.echo(ctx.get_help())


# Deferred import required to break a circular dependency: this module defines
# the ``cli`` group, commands register themselves onto it, and those command
# modules import from package ancestors. This is the standard Click pattern.
def _register_commands() -> None:
    from .commands import (  # noqa: PLC0415 - deferred: breaks the root<->commands circular import (see above)
        cli_b,
        cli_bld,
        cli_bmp,
        cli_build,
        cli_bump,
        cli_c,
        cli_cl,
        cli_clean,
        cli_clean_all,
        cli_cln,
        cli_codecov,
        cli_commit,
        cli_config,
        cli_config_deploy,
        cli_config_generate_examples,
        cli_cov,
        cli_coverage,
        cli_custom,
        cli_d,
        cli_dependencies,
        cli_deps,
        cli_ensure,
        cli_fail,
        cli_info,
        cli_install,
        cli_logdemo,
        cli_psh,
        cli_push,
        cli_push_p,
        cli_r,
        cli_rel,
        cli_release,
        cli_run,
        cli_send_email,
        cli_send_notification,
        cli_sh,
        cli_ship,
        cli_t,
        cli_test,
        cli_test_all,
        cli_testi,
        cli_testintegration,
        cli_ti,
    )

    for cmd in (
        cli_b,
        cli_bld,
        cli_bmp,
        cli_build,
        cli_bump,
        cli_c,
        cli_cl,
        cli_clean,
        cli_clean_all,
        cli_cln,
        cli_codecov,
        cli_commit,
        cli_cov,
        cli_coverage,
        cli_custom,
        cli_d,
        cli_dependencies,
        cli_deps,
        cli_ensure,
        cli_info,
        cli_install,
        cli_fail,
        cli_config,
        cli_config_deploy,
        cli_config_generate_examples,
        cli_logdemo,
        cli_psh,
        cli_push,
        cli_push_p,
        cli_r,
        cli_rel,
        cli_release,
        cli_run,
        cli_send_email,
        cli_send_notification,
        cli_sh,
        cli_ship,
        cli_t,
        cli_test,
        cli_test_all,
        cli_testintegration,
        cli_testi,
        cli_ti,
    ):
        cli.add_command(cmd)


_register_commands()


__all__ = ["cli"]
