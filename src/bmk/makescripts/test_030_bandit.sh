#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Bandit security scan

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_PACKAGE_NAME:?BMK_PACKAGE_NAME environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Security issues found\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

printf 'Running bandit on src/%s...\n' "$BMK_PACKAGE_NAME"

set +e
bandit -q -r -c pyproject.toml "src/${BMK_PACKAGE_NAME}"
exit_code=$?
set -e

explain_exit_code $exit_code
exit $exit_code
