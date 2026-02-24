#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 04: Unit tests with pytest, coverage, and Codecov upload (excludes integration tests)

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"

_output_format="${BMK_OUTPUT_FORMAT:-json}"
_coverage_args=()
if [[ "$_output_format" == "json" ]]; then
    _coverage_args+=(--output-format json)
fi

# Run pytest with coverage and upload to Codecov
"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_coverage.py" --run --project-dir "$BMK_PROJECT_DIR" "${_coverage_args[@]}"
