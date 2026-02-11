#!/usr/bin/env bash
# Shared helper: resolve the Python interpreter command.
# Source this from any makescript that needs to call Python:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/_resolve_python.sh"
#   "$BMK_PYTHON_CMD" "$SCRIPT_DIR/_somescript.py" ...
#
# Prefers the BMK_PYTHON_CMD environment variable set by the Python CLI
# (the uvx-managed interpreter), then falls back to python3 / python.
#
# Sets the variable BMK_PYTHON_CMD for use by the sourcing script.

if [[ -z "${BMK_PYTHON_CMD:-}" ]] || ! command -v "$BMK_PYTHON_CMD" &>/dev/null; then
    if command -v python3 &>/dev/null; then
        BMK_PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        BMK_PYTHON_CMD="python"
    else
        printf 'Error: %s\n' "Neither 'python3' nor 'python' found in PATH" >&2
        exit 1
    fi
fi
