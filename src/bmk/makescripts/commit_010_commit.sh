#!/usr/bin/env bash
# shellcheck shell=bash
# Git commit with timestamp prefix

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Commit failed (nothing to commit or pre-commit hook failed)\n' >&2 ;;
        128) printf 'Exit code 128: Fatal git error\n' >&2 ;;
        129) printf 'Exit code 129: Git usage error\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

# Join all arguments as the commit message
commit_message="$*"

# If no message provided, prompt for one
if [[ -z "$commit_message" ]]; then
    printf 'Commit message: '
    read -r commit_message
    if [[ -z "$commit_message" ]]; then
        printf 'Error: Commit message cannot be empty\n' >&2
        exit 1
    fi
fi

# Create timestamp prefix (local time)
timestamp=$(date '+%Y-%m-%d %H:%M:%S')
full_message="${timestamp} - ${commit_message}"

# Stage all changes
printf 'Staging changes...\n'
git add -A

# Commit with timestamped message
printf 'Committing: %s\n' "$full_message"

set +e
git commit -m "$full_message"
exit_code=$?
set -e

explain_exit_code $exit_code
exit $exit_code
