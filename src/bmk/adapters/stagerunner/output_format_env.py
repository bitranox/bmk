"""Read ``BMK_OUTPUT_FORMAT`` from the environment, and say so when its value is not one bmk knows.

Contents:
    * :func:`read_tool_output_format` - the output format the environment asks for.
"""

from __future__ import annotations

import functools
import os
import sys

from bmk.domain.enums import ToolOutputFormat

OUTPUT_FORMAT_VARIABLE = "BMK_OUTPUT_FORMAT"


def read_tool_output_format() -> ToolOutputFormat:
    """The output format ``BMK_OUTPUT_FORMAT`` selects; JSON when it is unset or unknown.

    An unknown value still runs JSON mode, but no longer silently: a misspelt ``txt`` reads
    exactly like a deliberate JSON run, and the reader concludes text mode has nothing to show.
    """
    value = os.environ.get(OUTPUT_FORMAT_VARIABLE)
    if not ToolOutputFormat.is_recognised(value):
        _warn_unrecognised(value or "")
    return ToolOutputFormat.from_env(value)


@functools.cache
def _warn_unrecognised(value: str) -> None:
    # Cached so one command warns once: the Makefile check, the CLI and the dependency
    # helper each read the variable during a single run.
    # !a (ascii) so a value the console cannot encode cannot turn the warning into a crash.
    sys.stderr.write(
        f"[bmk] {OUTPUT_FORMAT_VARIABLE}={value!a} is not 'text' or 'json' (in any case); it is ignored.\n"
    )


__all__ = ["OUTPUT_FORMAT_VARIABLE", "read_tool_output_format"]
