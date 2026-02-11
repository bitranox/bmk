# Stage 04: Unit tests with pytest, coverage, and Codecov upload (excludes integration tests)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_resolve_python.ps1"

if (-not $env:BMK_PROJECT_DIR) {
    throw "BMK_PROJECT_DIR environment variable must be set"
}

# Run pytest with coverage and upload to Codecov
& $BMK_PYTHON_CMD "$PSScriptRoot\_coverage.py" --run --project-dir $env:BMK_PROJECT_DIR
exit $LASTEXITCODE
