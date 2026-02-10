# Stage 02: Bandit security scan

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}
if (-not $env:BMK_PACKAGE_NAME) {
    throw "BMK_PACKAGE_NAME environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Explain-ExitCode {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Security issues found" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Host "Running bandit on src/$($env:BMK_PACKAGE_NAME)..."

bandit -q -r -c pyproject.toml "src/$($env:BMK_PACKAGE_NAME)"
$exitCode = $LASTEXITCODE

Explain-ExitCode $exitCode
exit $exitCode
