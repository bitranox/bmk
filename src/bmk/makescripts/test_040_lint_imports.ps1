# Stage 02: Import-linter architecture contracts

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

# Add src to PYTHONPATH so import-linter can find the package
$srcPath = Join-Path $env:BMK_PROJECT_DIR "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$($env:PYTHONPATH)"
}
else {
    $env:PYTHONPATH = $srcPath
}

function Explain-ExitCode {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Architecture contracts broken" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Host "Running import-linter..."

lint-imports
$exitCode = $LASTEXITCODE

Explain-ExitCode $exitCode
exit $exitCode
