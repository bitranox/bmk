#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Clean build artifacts after coverage
set -Eeu -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/_clean.py" --project-dir "$BMK_PROJECT_DIR"
