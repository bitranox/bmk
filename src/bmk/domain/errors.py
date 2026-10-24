"""Domain-specific exceptions for typed error handling at boundaries."""

from __future__ import annotations

from .enums import RefusalKind


class RefusalError(Exception):
    """bmk deliberately declined to act on its input; a refusal, not a crash.

    The CLI reports it as one ``Error: <message>`` line and exits with the code its
    :attr:`kind` maps to. A subclass states its kind as a class attribute; a direct
    instance may pass one.

    Args:
        *args: The message, as for any exception.
        kind: Overrides the class's kind for this one instance.

    Example:
        >>> err = RefusalError("workers must be >= 1", kind=RefusalKind.INVALID_ARGUMENT)
        >>> err.kind
        <RefusalKind.INVALID_ARGUMENT: 'invalid_argument'>
        >>> RefusalError("x").kind
        <RefusalKind.PRECONDITION: 'precondition'>
    """

    kind: RefusalKind = RefusalKind.PRECONDITION

    def __init__(self, *args: object, kind: RefusalKind | None = None) -> None:
        super().__init__(*args)
        if kind is not None:
            self.kind = kind


class ConfigurationError(RefusalError):
    """Missing, invalid, or incomplete configuration.

    Raised when required configuration values are absent, malformed, or
    logically inconsistent. Typically caught at CLI boundaries to provide
    user-friendly error messages.

    Example:
        >>> from bmk.domain.errors import ConfigurationError
        >>> err = ConfigurationError("No SMTP hosts configured")
        >>> str(err)
        'No SMTP hosts configured'
        >>> err.kind
        <RefusalKind.CONFIG: 'config'>
    """

    kind = RefusalKind.CONFIG


class DeliveryError(Exception):
    """Email/notification delivery failed at SMTP level.

    Raised when all configured SMTP hosts fail to accept the message.
    Contains details about the delivery failure for logging and user feedback.
    Not a :class:`RefusalError`: bmk tried and the server failed, so the command
    owns its exit code (``SMTP_FAILURE``) rather than the refusal table.

    Example:
        >>> from bmk.domain.errors import DeliveryError
        >>> err = DeliveryError("Connection refused by smtp.example.com:587")
        >>> str(err)
        'Connection refused by smtp.example.com:587'
    """


class InvalidRecipientError(ValueError):
    """Email address validation failure.

    Raised when a recipient address fails RFC 5321/5322 validation.
    Inherits from ValueError so existing ``except ValueError`` handlers
    continue to catch it during the migration period.

    Example:
        >>> from bmk.domain.errors import InvalidRecipientError
        >>> err = InvalidRecipientError("Invalid email: not-an-email")
        >>> str(err)
        'Invalid email: not-an-email'
        >>> isinstance(err, ValueError)
        True
    """


class InvalidProjectVersionError(RefusalError, ValueError):
    """A project version bmk will not act on.

    Raised by :mod:`bmk.domain.version` when ``[project].version`` is not a version
    at all, is spelled non-canonically, carries a local segment, or cannot be bumped.
    Inherits from ValueError so the existing ``except ValueError`` handlers in the
    bump helper keep catching it.

    Example:
        >>> from bmk.domain.errors import InvalidProjectVersionError
        >>> err = InvalidProjectVersionError('"v1.0.0" is not canonical; write it as "1.0.0"')
        >>> isinstance(err, ValueError)
        True
        >>> err.kind
        <RefusalKind.INVALID_ARGUMENT: 'invalid_argument'>
    """

    kind = RefusalKind.INVALID_ARGUMENT


__all__ = [
    "ConfigurationError",
    "DeliveryError",
    "InvalidProjectVersionError",
    "InvalidRecipientError",
    "RefusalError",
]
