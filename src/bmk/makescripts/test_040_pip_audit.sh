#!/usr/bin/env bash
# shellcheck shell=bash
# Stage 03: pip-audit dependency vulnerability scan
# Reads ignore-vulns from [tool.pip-audit] in pyproject.toml

set -Eeu -o pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_resolve_python.sh"

: "${BMK_PROJECT_DIR:?BMK_PROJECT_DIR environment variable must be set}"
cd "$BMK_PROJECT_DIR" || exit 1

explain_exit_code() {
    local code=$1
    case $code in
        0) ;;
        1) printf 'Exit code 1: Vulnerabilities found\n' >&2 ;;
        *) printf 'Exit code %d: unknown\n' "$code" >&2 ;;
    esac
}

# Extract ignore-vulns from pyproject.toml and build CLI flags
IGNORE_FLAGS=""
if [[ -f "pyproject.toml" ]]; then
    IGNORE_FLAGS=$("$BMK_PYTHON_CMD" -c '
import sys
import rtoml
from pathlib import Path

pyproject = Path("pyproject.toml")
if not pyproject.exists():
    sys.exit(0)

data = rtoml.load(pyproject.open("r", encoding="utf-8"))
ignores = data.get("tool", {}).get("pip-audit", {}).get("ignore-vulns", [])

for vuln_id in ignores:
    print(f"--ignore-vuln={vuln_id}")
' 2>/dev/null || true)
fi

printf 'Running pip-audit...\n'

set +e
# shellcheck disable=SC2086
pip-audit $IGNORE_FLAGS
exit_code=$?
set -e

explain_exit_code "$exit_code"
exit "$exit_code"
