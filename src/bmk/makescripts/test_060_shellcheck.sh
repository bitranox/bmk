#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 06: Shell linting (shellcheck + shfmt + bashate)
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"

_output_format="${BMK_OUTPUT_FORMAT:-json}"
_shellcheck_args=()
if [[ "$_output_format" == "json" ]]; then
    _shellcheck_args+=(--output-format json)
fi

"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_shellcheck.py" --project-dir "$BMK_PROJECT_DIR" "${_shellcheck_args[@]}" "$@"
