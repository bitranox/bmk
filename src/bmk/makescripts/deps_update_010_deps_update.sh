#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 01: Update outdated dependencies to latest versions
set -Eeu -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/_dependencies.py" --update --project-dir "$BMK_PROJECT_DIR"
