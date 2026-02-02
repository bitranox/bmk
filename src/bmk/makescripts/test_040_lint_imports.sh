#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Import-linter architecture contracts

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

# Add src to PYTHONPATH so import-linter can find the package
export PYTHONPATH="${BMK_PROJECT_DIR}/src${PYTHONPATH:+:$PYTHONPATH}"

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Architecture contracts broken\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

printf 'Running import-linter...\n'

set +e
lint-imports
exit_code=$?
set -e

explain_exit_code $exit_code
exit $exit_code
