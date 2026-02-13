#Requires -Version 7.0
# Stage 06: Shell linting (shellcheck + shfmt + bashate)
# Shell linting tools are not applicable on Windows — skip gracefully.

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Write-Output "Shell linting skipped (not applicable on Windows)"
exit 0
