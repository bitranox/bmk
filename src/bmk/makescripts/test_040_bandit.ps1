#Requires -Version 7.0
# Stage 02: Bandit security scan

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}
if (-not $env:BMK_PACKAGE_NAME) {
    throw "BMK_PACKAGE_NAME environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Write-ExitCodeError {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Security issues found" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Output "Running bandit on src/$($env:BMK_PACKAGE_NAME)..."

$outputFormat = if ($env:BMK_OUTPUT_FORMAT) { $env:BMK_OUTPUT_FORMAT } else { "json" }
$banditArgs = @()
if ($outputFormat -eq "json") {
    $banditArgs += "-f", "json"
} else {
    $banditArgs += "-q"
}

bandit -r -c pyproject.toml @banditArgs "src/$($env:BMK_PACKAGE_NAME)"
$exitCode = $LASTEXITCODE

Write-ExitCodeError $exitCode
exit $exitCode
