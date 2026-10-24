"""The exact lines send-email and send-notification print, for each outcome.

Both commands share one error handler that names the kind of message in its output. These tests
pin every line that carries that name, through the real ``main()`` entry point, so a change in how
the kind is spelled (an enum member rendered instead of its value, a lost ``.lower()``) shows here.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest
from lib_layered_config import Config

from bmk.adapters.cli.commands.email._common import MessageKind
from bmk.adapters.cli.main import main
from bmk.adapters.memory.email import EmailSpy
from bmk.composition import AppServices, build_testing
from bmk.domain.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable

EMAIL = {"email": {"smtp_hosts": ["smtp.test.com:587"], "from_address": "sender@test.com"}}
SEND_EMAIL = ["send-email", "--to", "recipient@test.com", "--subject", "Test", "--body", "Hello"]
SEND_NOTIFICATION = ["send-notification", "--to", "admin@test.com", "--subject", "Alert", "--message", "m"]
COMMANDS = [("Email", SEND_EMAIL), ("Notification", SEND_NOTIFICATION)]
COMMAND_IDS = ["send-email", "send-notification"]


def _services(spy: EmailSpy) -> Callable[[], AppServices]:
    config = Config(EMAIL, {})

    def get_config(**_kwargs: Any) -> Config:
        return config

    def build() -> AppServices:
        return dataclasses.replace(
            build_testing(),
            get_config=get_config,
            send_email=spy.send_email,
            send_notification=spy.send_notification,
        )

    return build


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("label", "args"), COMMANDS, ids=COMMAND_IDS)
def test_a_successful_send_prints_its_kind_sent_successfully(
    capsys: pytest.CaptureFixture[str], label: str, args: list[str]
) -> None:
    exit_code = main(args, services_factory=_services(EmailSpy()))

    assert exit_code == 0
    assert f"\n{label} sent successfully!\n" in capsys.readouterr().out


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("label", "args"), COMMANDS, ids=COMMAND_IDS)
def test_a_send_returning_false_prints_its_kind_sending_failed(
    capsys: pytest.CaptureFixture[str], label: str, args: list[str]
) -> None:
    spy = EmailSpy()
    spy.should_fail = True

    exit_code = main(args, services_factory=_services(spy))

    assert exit_code == 69
    assert f"\n{label} sending failed.\n" in capsys.readouterr().err


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("label", "args"), COMMANDS, ids=COMMAND_IDS)
def test_a_value_error_names_the_lowercase_kind(
    capsys: pytest.CaptureFixture[str], label: str, args: list[str]
) -> None:
    spy = EmailSpy()
    spy.raise_exception = ValueError("bad recipient")

    exit_code = main(args, services_factory=_services(spy))

    assert exit_code == 22
    assert f"Error: Invalid {label.lower()} parameters - bad recipient\n" in capsys.readouterr().err


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("_label", "args"), COMMANDS, ids=COMMAND_IDS)
def test_a_configuration_error_prints_the_shared_heading(
    capsys: pytest.CaptureFixture[str], _label: str, args: list[str]
) -> None:
    spy = EmailSpy()
    spy.raise_exception = ConfigurationError("no sender")

    exit_code = main(args, services_factory=_services(spy))

    assert exit_code == 78
    assert "Error: Configuration error - no sender\n" in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_no_line_spells_the_enum_member_name(capsys: pytest.CaptureFixture[str]) -> None:
    """On Python 3.11+ a str-Enum member in an f-string renders ``MessageKind.EMAIL``."""
    spy = EmailSpy()
    spy.raise_exception = ValueError("bad recipient")
    main(SEND_EMAIL, services_factory=_services(spy))
    main(SEND_NOTIFICATION, services_factory=_services(EmailSpy()))

    captured = capsys.readouterr()
    assert "MessageKind" not in captured.out + captured.err


@pytest.mark.os_agnostic
def test_message_kind_values_are_the_display_labels() -> None:
    assert [kind.value for kind in MessageKind] == ["Email", "Notification"]
    assert all(type(kind.value) is str for kind in MessageKind)
    assert [kind.noun for kind in MessageKind] == ["email", "notification"]
    assert all(type(kind.noun) is str for kind in MessageKind)
