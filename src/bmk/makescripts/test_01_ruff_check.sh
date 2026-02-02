#!/usr/bin/env bash
# Sequential test: Ruff linting
# Runs before parallel tests - must pass before continuing

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR" || exit 1

echo "Running ruff check..."
ruff check .
