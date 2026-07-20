"""Behaviour tests for EmailConfig model: validators, redaction, and ConfMail conversion."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from bmk.adapters.cli.commands.email._common import apply_validated_overrides
from bmk.adapters.email.config import REVEAL_SECRETS, EmailConfig, load_email_config_from_dict

# ---------------------------------------------------------------------------
# Validator: _coerce_string_to_list edge cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_coerce_non_string_non_list_to_empty_list() -> None:
    """Non-string, non-list values for smtp_hosts/recipients coerce to empty list."""
    config = EmailConfig.model_validate({"smtp_hosts": 42, "recipients": None})

    assert config.smtp_hosts == []
    assert config.recipients == []


# ---------------------------------------------------------------------------
# Validator: _coerce_extension_lists edge cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_coerce_extension_unsupported_type_to_none() -> None:
    """Unsupported type for attachment extensions coerces to None."""
    config = EmailConfig.model_validate({"attachment_allowed_extensions": 42})

    assert config.attachment_allowed_extensions is None


# ---------------------------------------------------------------------------
# Validator: _coerce_directory_lists edge cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_coerce_directory_unsupported_type_to_none() -> None:
    """Unsupported type for attachment directories coerces to None."""
    config = EmailConfig.model_validate({"attachment_allowed_directories": 42})

    assert config.attachment_allowed_directories is None


# ---------------------------------------------------------------------------
# __repr__ with password redaction
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_repr_redacts_password() -> None:
    """Password is shown as [REDACTED] in repr."""
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"], smtp_password="secret123")

    text = repr(config)

    assert "secret123" not in text
    assert "[REDACTED]" in text


@pytest.mark.os_agnostic
def test_repr_shows_none_password_as_none() -> None:
    """None password is shown as None (not redacted)."""
    config = EmailConfig()

    text = repr(config)

    assert "[REDACTED]" not in text
    assert "smtp_password=None" in text


# ---------------------------------------------------------------------------
# Password redaction on EVERY export path, not just repr()
#
# repr() was redacted while str(), f"{config}", "%s"-logging, model_dump() and
# model_dump_json() all emitted the plaintext password. Only repr() was tested, which is
# exactly why the gap survived. One test per leaking path.
# ---------------------------------------------------------------------------


_EXPORT_PATHS: tuple[tuple[str, Callable[[EmailConfig], str]], ...] = (
    ("str", str),
    ("format", lambda c: f"{c}"),
    ("model_dump", lambda c: str(c.model_dump())),
    ("model_dump_json", lambda c: c.model_dump_json()),
)


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("path", "render"), _EXPORT_PATHS, ids=[name for name, _ in _EXPORT_PATHS])
def test_password_is_redacted_on_every_export_path(path: str, render: Callable[[EmailConfig], str]) -> None:
    """No export path emits the plaintext password."""
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"], smtp_password="secret123")

    text = render(config)

    assert "secret123" not in text, f"{path} leaked the plaintext password"
    assert "[REDACTED]" in text


@pytest.mark.os_agnostic
def test_percent_s_logging_does_not_leak_password(caplog: pytest.LogCaptureFixture) -> None:
    """`logger.error("%s", config)` renders via __str__ and must not leak."""
    config = EmailConfig(smtp_password="secret123")

    with caplog.at_level(logging.ERROR):
        logging.getLogger(__name__).error("config=%s", config)

    assert "secret123" not in caplog.text


@pytest.mark.os_agnostic
def test_model_dump_reveals_password_with_explicit_context() -> None:
    """The opt-out context returns the real password for round-trip callers."""
    config = EmailConfig(smtp_password="secret123")

    revealed = config.model_dump(context={REVEAL_SECRETS: True})

    assert revealed["smtp_password"] == "secret123"


@pytest.mark.os_agnostic
def test_none_password_serializes_as_none_not_redacted() -> None:
    """An unset password stays None rather than becoming the redaction string."""
    config = EmailConfig()

    assert config.model_dump()["smtp_password"] is None


@pytest.mark.os_agnostic
def test_to_conf_mail_carries_the_real_password() -> None:
    """Redaction must not reach the object that actually authenticates."""
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"], smtp_password="secret123")

    # ConfMail.smtp_password is a SecretStr (btx_lib_mail 1.4.0+): masked in repr,
    # but the plaintext must survive for the actual SMTP login.
    carried = config.to_conf_mail().smtp_password
    assert carried is not None
    assert carried.get_secret_value() == "secret123"


@pytest.mark.os_agnostic
def test_override_round_trip_preserves_the_real_password() -> None:
    """apply_validated_overrides dumps and re-validates; redaction must not break auth.

    Without the explicit reveal context this returns "[REDACTED]" as the password and SMTP
    auth fails with a credential that looks plausible in a log.
    """
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"], smtp_username="u", smtp_password="secret123")

    merged = apply_validated_overrides(config, {"timeout": 12.0})

    assert merged.smtp_password == "secret123"
    assert merged.timeout == 12.0


@pytest.mark.os_agnostic
def test_repr_includes_all_fields() -> None:
    """All fields appear in repr."""
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"], from_address="a@b.com")

    text = repr(config)

    assert "smtp_hosts=" in text
    assert "from_address=" in text
    assert "use_starttls=" in text


# ---------------------------------------------------------------------------
# to_conf_mail - attachment security kwargs
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_to_conf_mail_without_attachment_overrides() -> None:
    """ConfMail is created without attachment kwargs when defaults are None."""
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"])

    conf = config.to_conf_mail()

    assert conf.smtphosts == ["smtp.test.com:587"]


@pytest.mark.os_agnostic
def test_to_conf_mail_with_allowed_extensions() -> None:
    """ConfMail gets attachment_allowed_extensions when set."""
    config = EmailConfig(
        smtp_hosts=["smtp.test.com:587"],
        attachment_allowed_extensions=frozenset({".pdf", ".txt"}),
    )

    conf = config.to_conf_mail()

    assert conf.attachment_allowed_extensions == frozenset({".pdf", ".txt"})


@pytest.mark.os_agnostic
def test_to_conf_mail_with_blocked_extensions() -> None:
    """ConfMail gets attachment_blocked_extensions when set."""
    config = EmailConfig(
        smtp_hosts=["smtp.test.com:587"],
        attachment_blocked_extensions=frozenset({".exe", ".bat"}),
    )

    conf = config.to_conf_mail()

    assert conf.attachment_blocked_extensions == frozenset({".exe", ".bat"})


@pytest.mark.os_agnostic
def test_to_conf_mail_with_allowed_directories() -> None:
    """ConfMail gets attachment_allowed_directories when set."""
    dirs = frozenset({Path("/tmp/safe")})
    config = EmailConfig(
        smtp_hosts=["smtp.test.com:587"],
        attachment_allowed_directories=dirs,
    )

    conf = config.to_conf_mail()

    assert conf.attachment_allowed_directories == dirs


@pytest.mark.os_agnostic
def test_to_conf_mail_with_blocked_directories() -> None:
    """ConfMail gets attachment_blocked_directories when set."""
    dirs = frozenset({Path("/etc"), Path("/root")})
    config = EmailConfig(
        smtp_hosts=["smtp.test.com:587"],
        attachment_blocked_directories=dirs,
    )

    conf = config.to_conf_mail()

    assert conf.attachment_blocked_directories == dirs


@pytest.mark.os_agnostic
def test_to_conf_mail_skips_max_size_when_none() -> None:
    """ConfMail omits max_size_bytes kwarg when EmailConfig has None (library default applies)."""
    config = EmailConfig(
        smtp_hosts=["smtp.test.com:587"],
        attachment_max_size_bytes=None,
    )

    conf = config.to_conf_mail()

    # None in EmailConfig means "don't pass to ConfMail", library uses its own default (25 MiB)
    assert conf.attachment_max_size_bytes == 26_214_400


@pytest.mark.os_agnostic
def test_coerce_max_size_zero_becomes_none() -> None:
    """Setting max_size_bytes=0 in config coerces to None (disable size checking)."""
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"], attachment_max_size_bytes=0)

    assert config.attachment_max_size_bytes is None


# ---------------------------------------------------------------------------
# load_email_config_from_dict - nested attachments
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_load_flattens_nested_attachments_section() -> None:
    """Nested [email.attachments] is flattened with attachment_ prefix."""
    config_dict = {
        "email": {
            "smtp_hosts": ["smtp.test.com:587"],
            "attachments": {
                "max_size_bytes": 10_485_760,
                "allow_symlinks": True,
            },
        }
    }

    config = load_email_config_from_dict(config_dict)

    assert config.attachment_max_size_bytes == 10_485_760
    assert config.attachment_allow_symlinks is True


@pytest.mark.os_agnostic
def test_load_handles_missing_email_section() -> None:
    """Missing email section returns defaults."""
    config = load_email_config_from_dict({})

    assert config.smtp_hosts == []
    assert config.from_address is None
