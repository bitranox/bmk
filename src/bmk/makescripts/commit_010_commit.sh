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

# Resolve commit message:
# 1. Command line arguments
# 2. BMK_COMMIT_MESSAGE environment variable
# 3. Prompt interactively (only if terminal available)
commit_message="$*"

if [[ -z "$commit_message" ]]; then
    commit_message="${BMK_COMMIT_MESSAGE:-}"
fi

if [[ -z "$commit_message" ]]; then
    if [[ -t 0 ]]; then
        # Interactive terminal available, prompt for message
        printf 'Commit message: '
        read -r commit_message
        if [[ -z "$commit_message" ]]; then
            printf 'Error: Commit message cannot be empty\n' >&2
            exit 1
        fi
    else
        # Non-interactive, use default
        commit_message="chores"
    fi
fi

# Create timestamp prefix (local time)
timestamp=$(date '+%Y-%m-%d %H:%M:%S')
full_message="${timestamp} - ${commit_message}"

# Stage all changes
printf 'Staging changes...\n'
git add -A

# Warn about potentially sensitive files being staged
sensitive_files=$(git diff --cached --name-only | grep -iE '\.env$|\.env\.|credentials|secret|\.key$|\.pem$|id_rsa' || true)
if [[ -n "$sensitive_files" ]]; then
    printf 'Warning: Potentially sensitive files staged:\n' >&2
    printf '  %s\n' $sensitive_files >&2
    printf 'These files will be committed. Ensure .gitignore is correct.\n' >&2
fi

# Build commit arguments
commit_args=()
if git diff --cached --quiet; then
    printf 'No staged changes detected; creating empty commit\n'
    commit_args+=(--allow-empty)
fi

# Commit with timestamped message
printf 'Committing: %s\n' "$full_message"

set +e
git commit "${commit_args[@]}" -m "$full_message"
exit_code=$?
set -e

explain_exit_code "$exit_code"
exit "$exit_code"
