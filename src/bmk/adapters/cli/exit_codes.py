"""POSIX-conventional exit codes for CLI error paths.

Provides a single :class:`ExitCode` enum so every ``ctx.exit()`` call in a CLI
command carries a meaningful, grep-friendly integer instead of a bare ``1``.
Commands exit through click's ``Exit`` (what ``ctx.exit()`` raises), never a bare
``SystemExit``; ``adapters/cli/main.py`` turns it into the process exit code.

Signal codes (130, 141, 143) are informational constants only - the application
never exits with these values itself; ``lib_cli_exit_tools`` handles
signal-to-exit-code translation automatically.

Contents:
    * :class:`ExitCode` - IntEnum of all exit codes used by this application.
    * :data:`REFUSAL_EXIT_CODES` - the one exit code for each kind of refusal.
"""

from __future__ import annotations

from enum import IntEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from bmk.domain.enums import RefusalKind

if TYPE_CHECKING:
    from collections.abc import Mapping


class ExitCode(IntEnum):
    """POSIX-conventional exit codes for CLI error paths.

    Values follow sysexits.h and errno conventions where applicable:

    * 0-1: generic success / failure
    * 2-13: errno-derived codes (ENOENT, EACCES)
    * 22: EINVAL
    * 69: EX_UNAVAILABLE (sysexits.h)
    * 77: EX_NOPERM (sysexits.h): refused by policy, such as an email attachment
      btx_lib_mail's security checks reject
    * 78: EX_CONFIG (sysexits.h)
    * 110: ETIMEDOUT
    * 128+N: signal N (informational only)

    Example:
        >>> ExitCode.SUCCESS
        <ExitCode.SUCCESS: 0>
        >>> int(ExitCode.SMTP_FAILURE)
        69
    """

    SUCCESS = 0
    GENERAL_ERROR = 1
    FILE_NOT_FOUND = 2
    PERMISSION_DENIED = 13
    INVALID_ARGUMENT = 22
    SMTP_FAILURE = 69
    ATTACHMENT_REFUSED = 77
    CONFIG_ERROR = 78
    TIMEOUT = 110
    SIGNAL_INT = 130
    BROKEN_PIPE = 141
    SIGNAL_TERM = 143


#: How ``main()`` ends a :class:`~bmk.domain.errors.RefusalError` that no command handled.
#: Fixed values, so a refusal exits the same on every OS; the generic crash handler would
#: use the platform's errno for the exception type instead (EINVAL is 22 on POSIX, 87 on
#: Windows). Read-only, so no caller can re-map a kind for everyone else.
REFUSAL_EXIT_CODES: Final[Mapping[RefusalKind, ExitCode]] = MappingProxyType(
    {
        RefusalKind.CONFIG: ExitCode.CONFIG_ERROR,
        RefusalKind.INVALID_ARGUMENT: ExitCode.INVALID_ARGUMENT,
        RefusalKind.NOT_FOUND: ExitCode.FILE_NOT_FOUND,
        RefusalKind.PERMISSION: ExitCode.PERMISSION_DENIED,
        RefusalKind.PRECONDITION: ExitCode.GENERAL_ERROR,
    }
)


__all__ = ["REFUSAL_EXIT_CODES", "ExitCode"]
