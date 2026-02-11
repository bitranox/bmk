#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 01: Clean build artifacts and cache directories
set -Eeu -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"
"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_clean.py" --project-dir "$BMK_PROJECT_DIR"
