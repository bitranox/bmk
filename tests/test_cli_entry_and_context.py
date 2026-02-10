"""Behaviour tests for CLI entry point, context helpers, and edge cases."""

from __future__ import annotations

import lib_cli_exit_tools
import pytest
import rich_click as click
from click.testing import CliRunner, Result
from lib_layered_config import Config

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.context import (
    CLIContext,
    apply_traceback_preferences,
    get_cli_context,
    restore_traceback_state,
    snapshot_traceback_state,
    store_cli_context,
)
from bmk.adapters.cli.main import main

# ---------------------------------------------------------------------------
# main() — missing services_factory
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_raises_when_services_factory_is_none() -> None:
    """main() raises ValueError when services_factory is not provided."""
    with pytest.raises(ValueError, match="services_factory is required"):
        main(["--help"], services_factory=None)


# ---------------------------------------------------------------------------
# main() — ClickException handling
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_handles_click_exception(managed_traceback_state: None) -> None:
    """ClickException from CLI returns its exit code via main()."""
    from bmk.composition import build_production

    # Pass an invalid option to trigger a ClickException (UsageError)
    exit_code = main(
        ["--set", "invalid_no_dot=value"],
        services_factory=build_production,
    )

    assert exit_code != 0


# ---------------------------------------------------------------------------
# get_cli_context — RuntimeError when not initialized
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_cli_context_raises_when_not_initialized() -> None:
    """RuntimeError raised when Click context has no CLIContext."""
    ctx = click.Context(click.Command("test"))
    ctx.obj = "not a CLIContext"

    with pytest.raises(RuntimeError, match="CLI context not initialized"):
        get_cli_context(ctx)


# ---------------------------------------------------------------------------
# root.py — RuntimeError when services factory not callable
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_cli_root_raises_when_obj_not_callable(cli_runner: CliRunner) -> None:
    """RuntimeError when ctx.obj is not a callable services factory."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["info"], obj="not_callable")

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Traceback snapshot/restore round-trip
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_traceback_snapshot_restore_round_trip(managed_traceback_state: None) -> None:
    """snapshot → mutate → restore returns to original state."""
    original = snapshot_traceback_state()

    apply_traceback_preferences(True)
    assert lib_cli_exit_tools.config.traceback is True

    restore_traceback_state(original)
    assert lib_cli_exit_tools.config.traceback == original[0]
    assert lib_cli_exit_tools.config.traceback_force_color == original[1]


# ---------------------------------------------------------------------------
# store_cli_context / get_cli_context round-trip
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_store_and_get_cli_context_round_trip() -> None:
    """Stored CLIContext is retrievable via get_cli_context."""
    from bmk.composition import build_production

    ctx = click.Context(click.Command("test"))
    config = Config({}, {})
    services = build_production()

    store_cli_context(
        ctx,
        traceback=True,
        config=config,
        services=services,
        profile="staging",
        set_overrides=("a.b=1",),
    )
    result = get_cli_context(ctx)

    assert isinstance(result, CLIContext)
    assert result.traceback is True
    assert result.profile == "staging"
    assert result.set_overrides == ("a.b=1",)


# ---------------------------------------------------------------------------
# _nest_override — TypeError on non-dict intermediate
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_nest_override_raises_on_non_dict_intermediate() -> None:
    """TypeError raised when intermediate key is not a dict."""
    from bmk.adapters.config.overrides import ConfigOverride, _nest_override

    target: dict[str, dict[str, object]] = {"s": {"x": "scalar"}}
    override = ConfigOverride(section="s", key_path=("x", "nested"), value=42)

    with pytest.raises(TypeError, match="Expected dict"):
        _nest_override(target, override)


# ---------------------------------------------------------------------------
# permissions._get_mode — bool value fallback
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_mode_returns_default_for_bool_value() -> None:
    """Bool value in config section returns the default mode."""
    from bmk.adapters.config.permissions import _get_mode

    section: dict[str, int | str | bool] = {"app_directory": True}

    result = _get_mode(section, "app_directory", 0o755)

    assert result == 0o755


# ---------------------------------------------------------------------------
# memory adapters — uncovered paths
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_deploy_configuration_in_memory_returns_empty_list() -> None:
    """In-memory deploy returns an empty list."""
    from bmk.adapters.memory.config import deploy_configuration_in_memory
    from bmk.domain.enums import DeployTarget

    result = deploy_configuration_in_memory(targets=[DeployTarget.USER])

    assert result == []


@pytest.mark.os_agnostic
def test_email_spy_clear_resets_state() -> None:
    """EmailSpy.clear() resets all captured data."""
    from bmk.adapters.email.config import EmailConfig
    from bmk.adapters.memory.email import EmailSpy

    spy = EmailSpy()
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"])
    spy.send_email(config=config, recipients="a@b.com", subject="Hi")
    spy.send_notification(config=config, recipients="a@b.com", subject="Hi", message="msg")

    spy.clear()

    assert spy.sent_emails == []
    assert spy.sent_notifications == []
    assert spy.raise_exception is None


@pytest.mark.os_agnostic
def test_email_spy_notification_raises_when_configured() -> None:
    """EmailSpy.send_notification raises configured exception."""
    from bmk.adapters.email.config import EmailConfig
    from bmk.adapters.memory.email import EmailSpy

    spy = EmailSpy()
    spy.raise_exception = RuntimeError("test failure")
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"])

    with pytest.raises(RuntimeError, match="test failure"):
        spy.send_notification(config=config, recipients="a@b.com", subject="Hi", message="msg")
