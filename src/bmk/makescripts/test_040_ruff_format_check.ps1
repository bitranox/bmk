#Requires -Version 7.0
# Stage 02: Verify ruff formatting (no changes)

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Write-ExitCodeError {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Files need formatting" }
        2 { Write-Error "Exit code 2: Configuration or CLI error" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Output "Running ruff format check..."

# Note: ruff format --output-format json requires preview mode (unstable on stable ruff).
# The formatter only reports file counts, not per-violation data, so JSON adds no value here.

ruff format --check .
$exitCode = $LASTEXITCODE

Write-ExitCodeError $exitCode
exit $exitCode
