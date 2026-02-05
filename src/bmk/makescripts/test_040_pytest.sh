#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 04: Unit tests with pytest, coverage, and Codecov upload (excludes integration tests)

set -Eeu -o pipefail

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run pytest with coverage and upload to Codecov
python3 "${SCRIPT_DIR}/_coverage.py" --run --project-dir "$BMK_PROJECT_DIR"
