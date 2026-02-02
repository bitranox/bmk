# Stage 01: Integration tests with pytest (marker: integration)

$ErrorActionPreference = "Stop"

if (-not $env:BMK_PROJECT_DIR) {
    Write-Error "BMK_PROJECT_DIR environment variable must be set"
    exit 1
}

Set-Location $env:BMK_PROJECT_DIR

$env:PYTHONPATH = "$env:BMK_PROJECT_DIR\src" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })

Write-Host "Running pytest (integration tests only)..."
pytest -m integration --tb=short -q @args
exit $LASTEXITCODE
