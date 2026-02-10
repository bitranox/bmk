#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 05: Git push to remote

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

# Configuration: remote and branch
BMK_GIT_REMOTE="${BMK_GIT_REMOTE:-origin}"
BMK_GIT_BRANCH="${BMK_GIT_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Push failed\n' >&2 ;;
        128) printf 'Exit code 128: Fatal git error\n' >&2 ;;
        129) printf 'Exit code 129: Git usage error\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

# Push to remote
printf 'Pushing to %s/%s...\n' "$BMK_GIT_REMOTE" "$BMK_GIT_BRANCH"

set +e
git push -u "$BMK_GIT_REMOTE" "$BMK_GIT_BRANCH"
exit_code=$?
set -e

explain_exit_code "$exit_code"
exit "$exit_code"
