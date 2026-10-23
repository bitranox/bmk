"""Type-safe domain enums for output formats and deployment targets."""

from __future__ import annotations

from enum import Enum


class OutputFormat(str, Enum):
    """Output format options for configuration display.

    Defines valid output format choices for the config command.
    Inherits from str to allow direct string comparison and Click integration.

    Attributes:
        HUMAN: Human-readable TOML-like output format.
        JSON: Machine-readable JSON output format.

    Example:
        >>> OutputFormat.HUMAN.value
        'human'
        >>> OutputFormat.JSON == "json"
        True
    """

    HUMAN = "human"
    JSON = "json"


def _normalised(value: str | None) -> str:
    """``value`` case-folded; ``""`` when unset."""
    return (value or "").casefold()


class ToolOutputFormat(str, Enum):
    """Tool output mode for the stage runner.

    ``JSON`` captures tool output and shows it only on failure (machine-readable,
    the default); ``TEXT`` streams full verbose output. Distinct from
    :class:`OutputFormat` (which is ``human`` vs ``json`` for config display).

    Example:
        >>> ToolOutputFormat.JSON == "json"
        True
    """

    TEXT = "text"
    JSON = "json"

    @classmethod
    def from_env(cls, value: str | None) -> ToolOutputFormat:
        """Decode a raw ``BMK_OUTPUT_FORMAT`` value to a member.

        ``TEXT`` when the value is ``text`` in any case; unset or anything else is the ``JSON``
        default. The single place that env var's string is
        interpreted, so the ``BMK_OUTPUT_FORMAT`` rule cannot drift between call sites.

        Example:
            >>> ToolOutputFormat.from_env("TEXT")
            <ToolOutputFormat.TEXT: 'text'>
            >>> ToolOutputFormat.from_env(None)
            <ToolOutputFormat.JSON: 'json'>
        """
        return cls.TEXT if _normalised(value) == cls.TEXT.value else cls.JSON

    @classmethod
    def is_recognised(cls, value: str | None) -> bool:
        """Whether ``value`` is unset, empty, or a member's value in any case.

        Anything else still decodes to ``JSON`` in :meth:`from_env`; this tells the caller that
        it did so for a value nobody meant as JSON, so the fallback can be reported.

        Example:
            >>> ToolOutputFormat.is_recognised("Json"), ToolOutputFormat.is_recognised("txt")
            (True, False)
        """
        normalised = _normalised(value)
        return normalised == "" or normalised in {member.value for member in cls}


class BumpPart(str, Enum):
    """Semantic-version component to increment on a version bump.

    Inherits from str so the value crosses the CLI/subprocess boundary unchanged
    (argparse ``choices`` and the ``_bump_version`` helper argv both use the wire
    strings) while business logic dispatches on typed members.

    Which component a bump ADVANCES. It does not always increment: from a non-final
    version the same part finalizes instead, so ``1.2.3rc1`` patch-bumps to ``1.2.3``.
    :func:`bmk.domain.version.next_version` owns that rule.

    Attributes:
        MAJOR: Advance the major component (X+1.0.0).
        MINOR: Advance the minor component (X.Y+1.0).
        PATCH: Advance the patch component (X.Y.Z+1).

    Example:
        >>> BumpPart.MINOR.value
        'minor'
        >>> BumpPart.PATCH == "patch"
        True
    """

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class PipelineResult(str, Enum):
    """Overall outcome of a pipeline run, carried in its machine-readable summary line.

    Consumers grep the summary for ``"result":"pass"``, so the value is the wire string and
    must stay stable. Only a passing run emits a summary; a failing one reports its failed
    stages instead, so there is no failure member to emit.

    Attributes:
        PASSED: Every stage of every batch exited 0.

    Example:
        >>> PipelineResult.PASSED.value
        'pass'
    """

    # Named PASSED, not PASS: ruff S105 reads a member called PASS as a hardcoded password.
    PASSED = "pass"


class DeployTarget(str, Enum):
    """Configuration deployment target layers.

    Defines valid target layers for configuration file deployment.
    Inherits from str to allow direct string comparison and Click integration.

    Attributes:
        APP: System-wide application configuration (requires privileges).
        HOST: System-wide host-specific configuration (requires privileges).
        USER: User-specific configuration (~/.config on Linux).

    Example:
        >>> DeployTarget.USER.value
        'user'
        >>> DeployTarget.APP == "app"
        True
    """

    APP = "app"
    HOST = "host"
    USER = "user"


class VenvProvisioning(Enum):
    """What provisioning the project venv did before a pipeline ran.

    Stages read it from the ``StageContext``: ``deps_update`` does not repeat a sync this run already
    saw fail when its re-lock changed nothing, since that sync could only fail the same way again.

    Attributes:
        PROVISIONED: The venv was created or updated and synced.
        FAILED: Provisioning ran and did not end with a synced venv (a failed ``uv venv``, lock,
            sync or fallback install, a lock wait that gave up, or no ``pyproject.toml``).
        SKIPPED: ``BMK_NO_VENV_SYNC=1`` opted out of it.
        NOT_ATTEMPTED: The pipeline does not use the project venv, or no provisioning ran at all.

    Example:
        >>> VenvProvisioning.FAILED.value
        'failed'
    """

    PROVISIONED = "provisioned"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_ATTEMPTED = "not_attempted"


class PyrightPlatform(str, Enum):
    """A value pyright's ``--pythonplatform`` accepts.

    pyright evaluates ``sys.platform`` checks and picks typeshed stubs for ONE platform per run,
    so an error only one platform's stubs show (``os.geteuid`` on Windows) is invisible to a run
    for another.

    Example:
        >>> PyrightPlatform.WINDOWS.value
        'Windows'
    """

    LINUX = "Linux"
    WINDOWS = "Windows"
    DARWIN = "Darwin"


__all__ = [
    "BumpPart",
    "DeployTarget",
    "OutputFormat",
    "PipelineResult",
    "PyrightPlatform",
    "ToolOutputFormat",
    "VenvProvisioning",
]
