#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Build artifacts (runs parallel with test)
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_STAGES_DIR:?BMK_STAGES_DIR environment variable must be set}"

printf 'Building artifacts...\n'

BMK_COMMAND_PREFIX="bld" exec "${BMK_STAGES_DIR}/_btx_stagerunner.sh" "$@"
