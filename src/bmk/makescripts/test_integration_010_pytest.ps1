#Requires -Version 7.0
# Stage 01: Integration tests with pytest (marker: integration)

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

Set-Location $env:BMK_PROJECT_DIR

$srcPath = Join-Path $env:BMK_PROJECT_DIR "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$($env:PYTHONPATH)"
}
else {
    $env:PYTHONPATH = $srcPath
}

function Write-ExitCodeError {
    param([int]$Code)
    switch ($Code) {
        0 { }
        1 { Write-Error "Exit code 1: Tests failed" }
        2 { Write-Error "Exit code 2: Test execution interrupted by user" }
        3 { Write-Error "Exit code 3: Internal error during test execution" }
        4 { Write-Error "Exit code 4: pytest CLI usage error" }
        5 { Write-Error "Exit code 5: No tests collected (no tests marked with @pytest.mark.integration)" }
        default { Write-Error "Exit code ${Code}: unknown" }
    }
}

Write-Output "Running pytest (integration tests only)..."

pytest -m integration --tb=short -q $args
$exitCode = $LASTEXITCODE

Write-ExitCodeError $exitCode
exit $exitCode
