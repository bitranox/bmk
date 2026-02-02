#!/usr/bin/env bash
# Parallel test: Type checking with mypy

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR" || exit 1

echo "Running mypy..."
mypy .
