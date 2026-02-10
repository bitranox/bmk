# Stage 02: Apply ruff lint fixes (modifies files)
# Must run after format, before parallel checks

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Explain-ExitCode {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Lint violations remain after fix" }
        2 { Write-Error "Exit code 2: Configuration or CLI error" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Host "Running ruff lint --fix (apply)..."

ruff check --fix .
$exitCode = $LASTEXITCODE

Explain-ExitCode $exitCode
exit $exitCode
