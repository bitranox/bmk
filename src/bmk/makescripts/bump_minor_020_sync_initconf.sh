#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Sync __init__conf__.py version after minor bump

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

printf 'Syncing __init__conf__.py version...\n'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/_sync_initconf.py" --project-dir "$BMK_PROJECT_DIR"
