#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 01: Update outdated dependencies
# Runs first to ensure pyproject.toml is up-to-date before other checks

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
: "${BMK_STAGES_DIR:?BMK_STAGES_DIR environment variable must be set}"

printf 'test_010_update_deps \xe2\x86\x92 deps_update pipeline\n'
BMK_COMMAND_PREFIX="deps_update" exec "${BMK_STAGES_DIR}/_btx_stagerunner.sh" "$@"
