#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 04: Commit changes via stagerunner
set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_STAGES_DIR:?BMK_STAGES_DIR environment variable must be set}"

printf 'Committing changes...\n'

BMK_COMMAND_PREFIX="commit" exec "${BMK_STAGES_DIR}/_btx_stagerunner.sh" "$@"
