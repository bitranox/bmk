#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 04: Unit tests with pytest (excludes integration tests)

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

# Add src to PYTHONPATH for subprocess tests (python -m package)
export PYTHONPATH="${BMK_PROJECT_DIR}/src${PYTHONPATH:+:$PYTHONPATH}"

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Tests failed\n' >&2 ;;
        2) printf 'Exit code 2: Test execution interrupted by user\n' >&2 ;;
        3) printf 'Exit code 3: Internal error during test execution\n' >&2 ;;
        4) printf 'Exit code 4: pytest CLI usage error\n' >&2 ;;
        5) printf 'Exit code 5: No tests collected\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

printf 'Running pytest...\n'

set +e
pytest -m "not integration" --tb=short -q
exit_code=$?
set -e

explain_exit_code $exit_code
exit $exit_code
