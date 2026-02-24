#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 03: pip-audit dependency vulnerability scan
# Reads ignore-vulns from [tool.pip-audit] in pyproject.toml

set -Eeu -o pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_resolve_python.sh"

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Vulnerabilities found\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

# Extract ignore-vulns from pyproject.toml and build CLI flags
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IGNORE_FLAGS=""
if [[ -f "pyproject.toml" ]]; then
    IGNORE_FLAGS=$("$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_extract_pip_audit_ignores.py" 2>/dev/null || true)
fi

printf 'Running pip-audit...\n'

_output_format="${BMK_OUTPUT_FORMAT:-json}"
_pip_audit_args=()
if [[ "$_output_format" == "json" ]]; then
    _pip_audit_args+=(-f json)
fi

set +e
# shellcheck disable=SC2086
pip-audit $IGNORE_FLAGS "${_pip_audit_args[@]}"
exit_code=$?
set -e

explain_exit_code "$exit_code"
exit "$exit_code"
