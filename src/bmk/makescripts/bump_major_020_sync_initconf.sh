#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Sync __init__conf__.py version after major bump

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

printf 'Syncing __init__conf__.py version...\n'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"
"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_sync_initconf.py" --project-dir "$BMK_PROJECT_DIR"
