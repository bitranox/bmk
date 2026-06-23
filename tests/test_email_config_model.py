"""Behaviour tests for EmailConfig model: validators, repr, and ConfMail conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmk.adapters.email.config import EmailConfig, load_email_config_from_dict

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


@pytest.mark.os_agnostic
def test_repr_includes_all_fields() -> None:
    """All fields appear in repr."""
    config = EmailConfig(smtp_hosts=["smtp.test.com:587"], from_address="a@b.com")

    text = repr(config)

    assert "smtp_hosts=" in text
    assert "from_address=" in text
    assert "use_starttls=" in text


# ---------------------------------------------------------------------------
# to_conf_mail — attachment security kwargs
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
# load_email_config_from_dict — nested attachments
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
