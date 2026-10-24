"""The ``--output-format`` option of the helpers the stage runner launches as subprocesses.

``tools.py`` passes ``--output-format json|text`` to these modules; their accepted spellings come
from :class:`ToolOutputFormat`. Run as real ``python -m`` processes, the way the stage runner runs
them, so the help text and the refusal are what a user would read.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from bmk.domain.enums import ToolOutputFormat

HELPERS = [
    "bmk.adapters.stagerunner.helpers._coverage",
    "bmk.adapters.stagerunner.helpers._shellcheck",
    "bmk.adapters.stagerunner.helpers._psscriptanalyzer",
]
HELPER_IDS = ["coverage", "shellcheck", "psscriptanalyzer"]


def _run_helper(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


@pytest.mark.os_agnostic
@pytest.mark.parametrize("module", HELPERS, ids=HELPER_IDS)
def test_help_lists_every_tool_output_format_by_its_plain_value(module: str) -> None:
    """On Python 3.11+ a member list would print ``{ToolOutputFormat.TEXT,...}`` here."""
    result = _run_helper(module, "--help")

    assert result.returncode == 0, result.stderr
    choices = ",".join(fmt.value for fmt in ToolOutputFormat)
    assert f"--output-format {{{choices}}}" in result.stdout
    assert "ToolOutputFormat" not in result.stdout


@pytest.mark.os_agnostic
@pytest.mark.parametrize("module", HELPERS, ids=HELPER_IDS)
def test_an_unknown_output_format_is_refused_before_any_tool_runs(module: str) -> None:
    result = _run_helper(module, "--output-format", "xml")

    assert result.returncode == 2
    assert "xml" in result.stderr
    assert "ToolOutputFormat" not in result.stderr
