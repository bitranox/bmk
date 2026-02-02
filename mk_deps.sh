#!/usr/bin/env bash
# Dependencies checker - sets environment and calls _btx_stagerunner.sh
# For development/testing purposes only

set -Eeu -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export BMK_PROJECT_DIR="$SCRIPT_DIR"
export BMK_COMMAND_PREFIX="deps"
export BMK_STAGES_DIR="$SCRIPT_DIR/src/bmk/makescripts"

exec "$SCRIPT_DIR/src/bmk/makescripts/_btx_stagerunner.sh"
