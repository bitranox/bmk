#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 01: Run project CLI via uvx with local dependencies
set -Eeu -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"
"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_run.py" "$@"
