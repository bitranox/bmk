#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 01: Update dependencies before push
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_STAGES_DIR:?BMK_STAGES_DIR environment variable must be set}"

printf 'push_010_update_deps \xe2\x86\x92 deps pipeline\n'
BMK_COMMAND_PREFIX="deps" exec "${BMK_STAGES_DIR}/_btx_stagerunner.sh" --update "$@"
