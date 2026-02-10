#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Build Python wheel and sdist artifacts
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

cd "$BMK_PROJECT_DIR"

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Build failed\n' >&2 ;;
        2) printf 'Exit code 2: Configuration error\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

printf 'Building wheel/sdist via python -m build\n'

set +e
python3 -m build
exit_code=$?
set -e

explain_exit_code "$exit_code"
exit "$exit_code"
