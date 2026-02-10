#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 03: Clean build artifacts before commit
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_STAGES_DIR:?BMK_STAGES_DIR environment variable must be set}"

printf 'push_030_clean \xe2\x86\x92 clean pipeline\n'
BMK_COMMAND_PREFIX="clean" exec "${BMK_STAGES_DIR}/_btx_stagerunner.sh" "$@"
