#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 05: PowerShell linting (PSScriptAnalyzer)
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"
"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_psscriptanalyzer.py" --project-dir "$BMK_PROJECT_DIR" "$@"
