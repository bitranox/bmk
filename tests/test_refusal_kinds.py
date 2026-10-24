"""Every kind of refusal has exactly one exit code, the same on every OS."""

from __future__ import annotations

import pytest

from bmk.adapters.cli.exit_codes import REFUSAL_EXIT_CODES, ExitCode
from bmk.domain.errors import ConfigurationError, InvalidProjectVersionError, RefusalError, RefusalKind


@pytest.mark.os_agnostic
def test_every_refusal_kind_has_an_exit_code() -> None:
    assert set(REFUSAL_EXIT_CODES) == set(RefusalKind)


@pytest.mark.os_agnostic
def test_no_refusal_kind_exits_zero() -> None:
    assert ExitCode.SUCCESS not in REFUSAL_EXIT_CODES.values()


@pytest.mark.os_agnostic
def test_a_configuration_error_is_a_config_refusal() -> None:
    error = ConfigurationError("No SMTP hosts configured")

    assert isinstance(error, RefusalError)
    assert REFUSAL_EXIT_CODES[error.kind] is ExitCode.CONFIG_ERROR


@pytest.mark.os_agnostic
def test_an_invalid_project_version_is_an_invalid_argument_refusal_and_still_a_value_error() -> None:
    error = InvalidProjectVersionError('"v1.0.0" is not canonical; write it as "1.0.0"')

    assert isinstance(error, RefusalError)
    assert isinstance(error, ValueError)
    assert REFUSAL_EXIT_CODES[error.kind] is ExitCode.INVALID_ARGUMENT


@pytest.mark.os_agnostic
def test_a_kind_given_at_construction_overrides_the_class_default() -> None:
    error = RefusalError("no such file", kind=RefusalKind.NOT_FOUND)

    assert error.kind is RefusalKind.NOT_FOUND
    assert str(error) == "no such file"
