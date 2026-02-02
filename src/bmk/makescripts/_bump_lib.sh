#!/usr/bin/env bash
# shellcheck shell=bash
# Shared library for bump scripts - source this, don't execute directly.
# Prefixed with underscore so stagerunner ignores it.

# Initialize bump environment and change to project directory.
_bump_init() {
    set -Eeu -o pipefail
    : "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
    cd "$BMK_PROJECT_DIR" || exit 1
    # BASH_SOURCE[1] is the caller's script path
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
    export SCRIPT_DIR
}

# Print human-readable explanation for exit codes.
_bump_explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Version bump failed\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

# Run the version bump for the specified part (major|minor|patch).
_bump_run() {
    local bump_type="$1"
    printf 'Bumping %s version...\n' "$bump_type"

    set +e
    python3 "${SCRIPT_DIR}/_bump_version.py" "$bump_type" --project-dir "$BMK_PROJECT_DIR"
    local exit_code=$?
    set -e

    _bump_explain_exit_code $exit_code
    exit $exit_code
}
