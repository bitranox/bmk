#!/usr/bin/env bash
# Parallel test: Unit tests with pytest

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR" || exit 1

echo "Running pytest..."
pytest --tb=short -q "$@"
