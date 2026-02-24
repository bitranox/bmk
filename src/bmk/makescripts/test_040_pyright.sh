#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Pyright type checking

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Type errors found\n' >&2 ;;
        2) printf 'Exit code 2: Fatal error occurred\n' >&2 ;;
        3) printf 'Exit code 3: Configuration error\n' >&2 ;;
        4) printf 'Exit code 4: CLI usage error\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

printf 'Running pyright...\n'

_output_format="${BMK_OUTPUT_FORMAT:-json}"
_pyright_args=()
if [[ "$_output_format" == "json" ]]; then
    _pyright_args+=(--outputjson)
fi

set +e
pyright "${_pyright_args[@]}"
exit_code=$?
set -e

explain_exit_code "$exit_code"
exit "$exit_code"
