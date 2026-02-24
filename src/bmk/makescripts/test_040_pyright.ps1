#Requires -Version 7.0
# Stage 02: Pyright type checking

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

function Write-ExitCodeError {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Type errors found" }
        2 { Write-Error "Exit code 2: Fatal error occurred" }
        3 { Write-Error "Exit code 3: Configuration error" }
        4 { Write-Error "Exit code 4: CLI usage error" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Output "Running pyright..."

$outputFormat = if ($env:BMK_OUTPUT_FORMAT) { $env:BMK_OUTPUT_FORMAT } else { "json" }
$pyrightArgs = @()
if ($outputFormat -eq "json") {
    $pyrightArgs += "--outputjson"
}

pyright @pyrightArgs
$exitCode = $LASTEXITCODE

Write-ExitCodeError $exitCode
exit $exitCode
