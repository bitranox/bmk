#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Run tests before push
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_STAGES_DIR:?BMK_STAGES_DIR environment variable must be set}"

BMK_COMMAND_PREFIX="test" exec "${BMK_STAGES_DIR}/_btx_stagerunner.sh" "$@"
