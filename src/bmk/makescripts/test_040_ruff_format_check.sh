#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Verify ruff formatting (no changes)

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Files need formatting\n' >&2 ;;
        2) printf 'Exit code 2: Configuration or CLI error\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

printf 'Running ruff format check...\n'

# Note: ruff format --output-format json requires preview mode (unstable on stable ruff).
# The formatter only reports file counts, not per-violation data, so JSON adds no value here.

set +e
ruff format --check .
exit_code=$?
set -e

explain_exit_code "$exit_code"
exit "$exit_code"
