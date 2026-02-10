#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 02: Create git tag and GitHub release
set -Eeu -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/_release.py" --project-dir "$BMK_PROJECT_DIR" "$@"
