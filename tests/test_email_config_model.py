"""Behaviour tests for the EmailConfig model: password masking, repr, and the nested attachments section."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from bmk.adapters.email.config import EmailConfig, load_email_config_from_dict

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# __repr__ with password masking
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_repr_masks_password() -> None:
    """The password is shown masked in repr."""
    config = EmailConfig(smtphosts=["smtp.test.com:587"], smtp_password=SecretStr("secret123"))

    text = repr(config)

    assert "secret123" not in text
    assert "**********" in text


@pytest.mark.os_agnostic
def test_repr_shows_none_password_as_none() -> None:
    """None password is shown as None (not masked)."""
    config = EmailConfig()

    text = repr(config)

    assert "**********" not in text
    assert "smtp_password=None" in text


# ---------------------------------------------------------------------------
# Password masking on EVERY export path, not just repr()
#
# repr() was once redacted while str(), f"{config}", "%s"-logging, model_dump() and
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
def test_password_is_masked_on_every_export_path(path: str, render: Callable[[EmailConfig], str]) -> None:
    """No export path emits the plaintext password."""
    config = EmailConfig(smtphosts=["smtp.test.com:587"], smtp_password=SecretStr("secret123"))

    text = render(config)

    assert "secret123" not in text, f"{path} leaked the plaintext password"


@pytest.mark.os_agnostic
def test_percent_s_logging_does_not_leak_password(caplog: pytest.LogCaptureFixture) -> None:
    """`logger.error("%s", config)` renders via __str__ and must not leak."""
    config = EmailConfig(smtp_password=SecretStr("secret123"))

    with caplog.at_level(logging.ERROR):
        logging.getLogger(__name__).error("config=%s", config)

    assert "secret123" not in caplog.text


@pytest.mark.os_agnostic
def test_none_password_serializes_as_none_not_masked() -> None:
    """An unset password stays None rather than becoming a masked value."""
    config = EmailConfig()

    assert config.model_dump()["smtp_password"] is None


@pytest.mark.os_agnostic
def test_the_credentials_used_to_log_in_carry_the_real_password() -> None:
    """Masking must not reach the credentials that actually authenticate."""
    config = EmailConfig(smtphosts=["smtp.test.com:587"], smtp_username="u", smtp_password=SecretStr("secret123"))

    assert config.resolved_credentials() == ("u", "secret123")


@pytest.mark.os_agnostic
def test_repr_includes_all_fields() -> None:
    """All fields appear in repr."""
    config = EmailConfig(smtphosts=["smtp.test.com:587"], from_address="a@b.com")

    text = repr(config)

    assert "smtphosts=" in text
    assert "from_address=" in text
    assert "smtp_use_starttls=" in text


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

    assert config.smtphosts == []
    assert config.from_address is None
