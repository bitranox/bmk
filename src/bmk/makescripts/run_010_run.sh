#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 01: Run project CLI via uvx with local dependencies
set -Eeu -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/_run.py" --project-dir "$BMK_PROJECT_DIR" "$@"
