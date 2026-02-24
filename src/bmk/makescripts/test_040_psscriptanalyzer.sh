#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 05: PowerShell linting (PSScriptAnalyzer)
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"

_output_format="${BMK_OUTPUT_FORMAT:-json}"
_pssa_args=()
if [[ "$_output_format" == "json" ]]; then
    _pssa_args+=(--output-format json)
fi

"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_psscriptanalyzer.py" --project-dir "$BMK_PROJECT_DIR" "${_pssa_args[@]}" "$@"
