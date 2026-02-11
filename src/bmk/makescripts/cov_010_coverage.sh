#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 01: Run tests with coverage and upload to Codecov (standalone)
# Note: 'bmk test' already includes coverage via test_040_pytest.sh
#       Use 'bmk cov' to run coverage separately if needed
set -Eeu -o pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_resolve_python.sh"
"$BMK_PYTHON_CMD" "${SCRIPT_DIR}/_coverage.py" --run --project-dir "$BMK_PROJECT_DIR"
