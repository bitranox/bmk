#Requires -Version 7.0
# Stage 02: Build Python wheel and sdist artifacts

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Write-ExitCodeError {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Build failed" }
        2 { Write-Error "Exit code 2: Configuration error" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Output "Building wheel/sdist via python -m build"

& $BMK_PYTHON_CMD -m build
$exitCode = $LASTEXITCODE

Write-ExitCodeError $exitCode
exit $exitCode
